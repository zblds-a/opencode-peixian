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
            raise HTTPException(409, '资料结果尚未确认，本轮不会重试。')
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
    config = app.state.settings
    prepared = await rpc('native_prepare', session_id=value['session_id'],
        message_id=parent, call_id=value['call_id'], tool=value['tool'],
        args=value['args'])
    if prepared.get('cached'):
        return prepared['response']
    body = {'call_id':prepared['review_id'], 'revision':prepared['revision'],
        'model_id':prepared['model_id'], 'system':REVIEW_PROMPT,
        'input':prepared['review_input']}
    try:
        response = await app.state.client.post(
            'http://gateway:8080/internal/runtime/planning',
            headers={'X-Peixian-Key':config.token}, json=body, timeout=55)
        response.raise_for_status()
        decision = json.loads(response.json()['content'])
    except (ValueError, KeyError, httpx.HTTPError, TimeoutError):
        with contextlib.suppress(httpx.HTTPError,HTTPException):
            await rpc('native_review_failed',run_id=prepared['run_id'],call_id=value['call_id'],digest=prepared['digest'])
        raise HTTPException(409, {'code':'intent_review_unavailable','dispatch_status':'not_dispatched',
            'message':'本次未取得有效的意图核对结论，未访问资料接口；不会自动重试。'}) from None
    approved = await rpc('native_approve', run_id=prepared['run_id'],
        call_id=value['call_id'], digest=prepared['digest'], decision=decision)
    if not approved['allowed']:
        return {'status':'needs_input',
            'message':'本次独立意图核对未通过，尚未访问资料接口。已明确的条件仍保留；仅说明具体缺项或冲突，不要求用户确认内部 person-* 引用。',
            'reason_code':approved['reason_code']}
    return await execute(request, app, value, rpc, parent, process, native=True)
