"""Provider operation uses Gateway code, Control receipts and the egress gate."""
import asyncio
import contextlib
import copy
import json
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException

from .plugin_test import specification

from shared import native_intent_review
from shared import theft_provider_v2

REVIEW_PROMPT = native_intent_review.PROMPT
FAILURE_CODES = {'upstream_rows_limit': 'provider_rows_limit', 'response_too_large': 'provider_response_too_large'}
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
TRACK_SEGMENT = timedelta(days=3)
TRACK_MIN_SEGMENT = timedelta(days=1)
TRACK_MAX_CALLS = 20
TRACK_MAX_CONSECUTIVE_FAILURES = 3
INCIDENT_PAGE_SIZE = 100
INCIDENT_MAX_PAGES = 5


class TrackRowsLimit(ValueError):
    code = 'upstream_rows_limit'


def track_windows(start, end, size=TRACK_SEGMENT):
    left, right = datetime.strptime(start, TIME_FORMAT), datetime.strptime(end, TIME_FORMAT)
    windows = []
    while left < right:
        stop = min(left + size, right)
        windows.append((left, stop))
        left = stop
    return windows


def track_request(plan, left, right):
    low = datetime.strptime(plan['query']['start'], TIME_FORMAT)
    high = datetime.strptime(plan['query']['end'], TIME_FORMAT)
    if not low <= left < right <= high:
        raise ValueError('track_segment_outside_window')
    request = copy.deepcopy(plan['request'])
    request['json'].update(beginTime=left.strftime(TIME_FORMAT), endTime=right.strftime(TIME_FORMAT))
    return request


def track_points(response):
    if not isinstance(response, dict) or response.get('code') != 200:
        return None
    data = response.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('points'), list):
        return None
    return data['points']


async def collect_tracks(plan, invoke):
    """Split one frozen track window into sub-windows; never widen the frozen window."""
    row_limit = plan['limits']['max_rows']
    pending = track_windows(plan['query']['start'], plan['query']['end'])
    segments, points, seen = [], [], set()
    base, calls, failures = None, 0, 0
    while pending:
        left, right = pending.pop(0)
        if calls >= TRACK_MAX_CALLS or failures >= TRACK_MAX_CONSECUTIVE_FAILURES:
            segments.append((left, right, 'not_queried'))
            continue
        calls += 1
        found = None
        try:
            response = await invoke(track_request(plan, left, right))
            found = track_points(response)
            status = 'failed' if found is None else 'too_many' if len(found) > row_limit else 'ok'
        except (ValueError, httpx.HTTPError, TimeoutError) as exc:
            status = 'too_many' if getattr(exc, 'code', None) == 'upstream_rows_limit' else 'failed'
        if status == 'too_many' and right - left > TRACK_MIN_SEGMENT:
            middle = left + timedelta(seconds=int((right - left).total_seconds()) // 2)
            pending[:0] = [(left, middle), (middle, right)]
            continue
        failures = failures + 1 if status == 'failed' else 0
        if status == 'ok':
            base = base or response
            for point in found:
                key = theft_provider_v2.canonical(point)
                if key not in seen:
                    seen.add(key)
                    points.append(point)
        segments.append((left, right, status))
    segments.sort()
    if base is None:
        if segments and all(s[2] in ('too_many', 'not_queried') for s in segments):
            raise TrackRowsLimit()
        raise ValueError('track_segments_failed')
    points.sort(key=lambda p: str(p.get('captureTime', '')) if isinstance(p, dict) else '')
    merged = copy.deepcopy(base)
    merged['data'] = {**merged['data'], 'points': points, 'segments': [
        {'start': a.strftime(TIME_FORMAT), 'end': b.strftime(TIME_FORMAT), 'status': status}
        for a, b, status in segments]}
    return merged


def incident_request(plan, page, size):
    request = copy.deepcopy(plan['request'])
    request['json'].update(pageNum=page, pageSize=size)
    return request


async def collect_incidents(plan, invoke):
    """Read every page of one frozen area query, up to INCIDENT_MAX_PAGES."""
    size = min(INCIDENT_PAGE_SIZE, plan['limits']['max_rows'])
    rows, pages, base, total = [], [], None, None
    for page in range(1, INCIDENT_MAX_PAGES + 1):
        try:
            response = await invoke(incident_request(plan, page, size))
        except (ValueError, httpx.HTTPError, TimeoutError):
            if base is None:
                raise
            pages.append({'page': page, 'status': 'failed', 'count': 0})
            break
        data = response.get('data') if isinstance(response, dict) and response.get('code') == 200 else None
        if not isinstance(data, dict) or not isinstance(data.get('rows'), list) or type(data.get('total')) is not int:
            if base is None:
                return response
            pages.append({'page': page, 'status': 'failed', 'count': 0})
            break
        base = base or response
        total = data['total']
        rows.extend(data['rows'])
        pages.append({'page': page, 'status': 'ok', 'count': len(data['rows'])})
        if not data['rows'] or len(rows) >= total:
            break
    merged = copy.deepcopy(base)
    data = {k: v for k, v in merged['data'].items() if k not in ('pageNum', 'pageSize')}
    merged['data'] = {**data, 'rows': rows, 'total': total, 'pages': pages}
    return merged


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

            async def invoke(provider_request):
                task = asyncio.create_task(process({**spec, 'action':'invoke',
                    'tool':plan['tool_id'], 'args':{'request':provider_request}}))
                try:
                    while not task.done():
                        done, _ = await asyncio.wait({task}, timeout=0.5)
                        if done:
                            break
                        gate.require_egress()
                        await call('authorize', module=kind)
                        if await request.is_disconnected():
                            raise asyncio.CancelledError()
                    return await task
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            try:
                if kind == 'tracks' and plan.get('version') == theft_provider_v2.VERSION and isinstance(plan['request'].get('json'), dict):
                    response = await collect_tracks(plan, invoke)
                elif kind == 'incidents' and plan.get('version') == theft_provider_v2.VERSION and isinstance(plan['request'].get('json'), dict):
                    response = await collect_incidents(plan, invoke)
                else:
                    response = await invoke(plan['request'])
                await call('complete', module=kind, status='completed', response=response)
            except (ValueError, httpx.HTTPError, TimeoutError) as exc:
                code = FAILURE_CODES.get(getattr(exc, 'code', None))
                if code:
                    await call('complete', module=kind, status='rejected', error_code=code)
                else:
                    await call('complete', module=kind, status='unknown')
        key = value['call_id'] if native else kind
        item = (await call('read'))['state']['modules'].get(key, {})
        if item.get('status') != 'completed':
            from shared.tool_failure import public
            code=item.get('error_code') or ('provider_cancelled' if item.get('status')=='cancelled' else 'provider_result_unknown')
            detail=public({'code':code},'provider_complete',value.get('call_id'))
            if item.get('response_count'):detail['dispatch_status']='dispatched'
            raise HTTPException(409, detail)
        return theft_provider_v2.model_view(item['response']) if native else item['response']
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
        return theft_provider_v2.model_view(prepared['response'])
    if prepared.get('needs_question'):
        return {
            'status': 'needs_input',
            'dispatch_status': 'not_dispatched',
            'code': prepared.get('code'),
            'question': prepared.get('question'),
            'instruction': (
                '请使用 question 工具补充以上缺项，题干可自然改写；保持 header、选项和 custom 不变以绑定来源，'
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
