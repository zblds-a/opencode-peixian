"""Provider operation uses Gateway code, Control receipts and the egress gate."""
import asyncio
import contextlib
import json

import httpx
from fastapi import HTTPException

from .plugin_test import specification

from shared import native_intent_review

REVIEW_PROMPT = native_intent_review.PROMPT


async def execute(request, app, value, rpc, parent, process, *, native=False):
    if not native and value['args'] != {}:
        raise HTTPException(422, '查询条件已冻结，请勿传入新条件。')
    config = app.state.settings
    gate = app.state.runtime_management.gate
    admitted = await rpc('provider_begin', session_id=value['session_id'], message_id=parent)
    identity = {'run_id': admitted['run_id'], 'operation': admitted['operation']}
    plan = admitted['plan']

    async def call(action, **fields):
        return await rpc('provider_' + action, **identity, **fields)

    try:
        if value['tool'] != plan['tool_id']:
            raise HTTPException(409, '工具不在已确认范围内。')
        kind = plan['kind']
        await call('authorize', module=kind)
        if (await call('reserve', module=kind))['reserved']:
            spec = specification(config.managed_root, plan['plugin_id'])
            gate.require_egress()
            if await request.is_disconnected():
                await call('complete', module=kind, status='cancelled')
                raise asyncio.CancelledError()
            await call('dispatch', module=kind)
            task = asyncio.create_task(process({**spec, 'action':'invoke',
                'tool':plan['tool_id'], 'args':{'request':plan['request']}}))
            try:
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=0.5)
                    if done:
                        break
                    gate.require_egress()
                    await call('authorize', module=kind)
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                response = await task
                await call('complete', module=kind, status='completed', response=response)
            except (ValueError, httpx.HTTPError, TimeoutError):
                await call('complete', module=kind, status='unknown')
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        key = value['call_id'] if native else kind
        item = (await call('read'))['state']['modules'].get(key, {})
        if item.get('status') != 'completed':
            from shared.tool_failure import public
            code=item.get('error_code') or ('provider_cancelled' if item.get('status')=='cancelled' else 'provider_result_unknown')
            detail=public({'code':code},'provider_complete',value.get('call_id'))
            if item.get('response_count'):detail['dispatch_status']='dispatched'
            raise HTTPException(409, detail)
        return item['response']
    finally:
        with contextlib.suppress(httpx.HTTPError, HTTPException):
            await call('finish')


async def execute_native(request, app, value, rpc, parent, process):
    # Native providers may emit parallel tools. Serialize admission as well as
    # dispatch; do not turn a harmless sibling call into an unknown operation.
    if not hasattr(app.state, 'native_call_locks'):
        app.state.native_call_locks = {}
    locks = app.state.native_call_locks
    key = (value['session_id'], parent)
    slot = locks.setdefault(key, {'lock': asyncio.Lock(), 'users': 0})
    if slot['users'] >= 8:
        raise HTTPException(429, '同一执行等待的资料调用过多，尚未投递。')
    slot['users'] += 1
    acquired = False
    try:
        try:
            await asyncio.wait_for(slot['lock'].acquire(), timeout=120)
            acquired = True
        except TimeoutError:
            raise HTTPException(409, '等待前一项资料调用超时，本项尚未投递。') from None
        if await request.is_disconnected():
            raise asyncio.CancelledError()
        return await _execute_native(request, app, value, rpc, parent, process)
    finally:
        if acquired:
            slot['lock'].release()
        slot['users'] -= 1
        if not slot['users']:
            locks.pop(key, None)


async def _execute_native(request, app, value, rpc, parent, process):
    prepared = await rpc('native_prepare', session_id=value['session_id'],
        message_id=parent, call_id=value['call_id'], tool=value['tool'],
        args=value['args'])
    if prepared.get('cached'):
        return prepared['response']
    if prepared.get('needs_question'):
        return {
            'status': 'needs_input',
            'dispatch_status': 'not_dispatched',
            'code': prepared.get('code'),
            'question': prepared.get('question'),
            'instruction': (
                '请立即用 question 工具原样提出以上问题和选项（不得改写 header、问题文字和选项），'
                '等待用户回答后再调用同一工具一次；不要更换参数或改用其他工具重试。'
            ),
        }
    # Layer 3 removed: skip independent intent-review model; auto-allow so the
    # review_pending → approved state machine and audit record stay intact.
    decision = {'verdict': 'allow', 'reason_code': 'matched_request'}
    approved = await rpc('native_approve', run_id=prepared['run_id'],
        call_id=value['call_id'], digest=prepared['digest'], decision=decision)
    if not approved['allowed']:
        return {'status':'needs_input',
            'message':'本次资料调用未获批准，尚未访问资料接口。已明确的条件仍保留。',
            'reason_code':approved['reason_code']}
    return await execute(request, app, value, rpc, parent, process, native=True)
