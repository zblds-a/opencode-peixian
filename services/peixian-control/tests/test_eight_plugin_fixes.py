import asyncio
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from shared import theft_provider_v2 as v
from shared.tool_failure import public
from gateway import theft_provider_execution as ex
from control import native_tool_scope, native_precheck_questions, question_contract, provider_contracts
from control.theft_provider_state import ProviderState
from test_provider_contract_v2 import ID, LIMITS, REF

F = ex.TIME_FORMAT


def plan(start='2026-08-01 00:00:00', end='2026-09-01 00:00:00'):
    return {'query': {'start': start, 'end': end}, 'limits': {'max_rows': 100},
            'request': {'connection_group': 'police', 'method': 'POST', 'path': '/tracks',
                        'json': {'idCard': ID, 'beginTime': start, 'endTime': end, 'trackTypes': [0, 1, 2]}}}


def envelope(points):
    return {'code': 200, 'data': {'targetIdCard': ID, 'points': points, 'photos': []}}


def run(p, invoke):
    return asyncio.run(ex.collect_tracks(p, invoke))


def span_days(req):
    body = req['json']
    return (datetime.strptime(body['endTime'], F) - datetime.strptime(body['beginTime'], F)).total_seconds() / 86400


def tiles(segments, p):
    assert segments[0]['start'] == p['query']['start'] and segments[-1]['end'] == p['query']['end']
    assert all(a['end'] == b['start'] for a, b in zip(segments, segments[1:]))


def test_tracks_split_into_three_day_windows_and_merge_points():
    p, seen = plan(), []

    async def invoke(req):
        seen.append(req)
        body = req['json']
        return envelope([{'deviceId': 'd', 'captureTime': body['endTime'], 'lon': 1, 'lat': 2},
                         {'deviceId': 'same', 'captureTime': '2026-08-01 00:00:00', 'lon': 1, 'lat': 2}])

    merged = run(p, invoke)
    assert len(seen) == 11 and all(span_days(r) <= 3 for r in seen)
    assert all(r['json']['trackTypes'] == [0, 1, 2] and r['path'] == '/tracks' for r in seen)
    assert p['request']['json']['beginTime'] == '2026-08-01 00:00:00'
    points = merged['data']['points']
    assert len(points) == 12 and points == sorted(points, key=lambda x: x['captureTime'])
    segments = merged['data']['segments']
    tiles(segments, p)
    assert {s['status'] for s in segments} == {'ok'}
    result = v.parse_response('tracks', {'person_ref': REF, **p['query']}, merged, LIMITS, {REF: ID})
    assert result['coverage'] == 'complete' and result['segments'] == segments and not result['missing']


def test_rows_limit_bisects_down_to_one_day():
    p = plan('2026-08-01 00:00:00', '2026-08-04 00:00:00')

    async def invoke(req):
        if span_days(req) > 1:
            raise ex.TrackRowsLimit()
        return envelope([{'deviceId': 'd', 'captureTime': req['json']['beginTime'], 'lon': 1, 'lat': 2}])

    segments = run(p, invoke)['data']['segments']
    tiles(segments, p)
    assert {s['status'] for s in segments} == {'ok'} and len(segments) == 4


def test_oversized_one_day_window_stays_unverified_and_calls_are_capped():
    p, calls = plan(), []

    async def invoke(req):
        calls.append(req)
        if req['json']['beginTime'] < '2026-08-04 00:00:00':
            return envelope([{'deviceId': 'd', 'captureTime': str(i), 'lon': 1, 'lat': 2} for i in range(101)])
        return envelope([])

    merged = run(p, invoke)
    assert len(calls) <= ex.TRACK_MAX_CALLS
    segments = merged['data']['segments']
    tiles(segments, p)
    statuses = [s['status'] for s in segments]
    assert 'too_many' in statuses and 'ok' in statuses
    result = v.parse_response('tracks', {'person_ref': REF, **p['query']}, merged, LIMITS, {REF: ID})
    assert result['coverage'] == 'partial' and 'track_segments_unverified' in result['missing']


def test_all_segments_too_many_is_rows_limit():
    p = plan('2026-08-01 00:00:00', '2026-08-02 00:00:00')

    async def invoke(req):
        raise ex.TrackRowsLimit()

    with pytest.raises(ex.TrackRowsLimit):
        run(p, invoke)
    assert ex.FAILURE_CODES[ex.TrackRowsLimit.code] == 'provider_rows_limit'


def test_consecutive_failures_stop_querying():
    p, calls = plan(), []

    async def invoke(req):
        calls.append(req)
        raise ValueError('upstream')

    with pytest.raises(ValueError, match='track_segments_failed'):
        run(p, invoke)
    assert len(calls) == ex.TRACK_MAX_CONSECUTIVE_FAILURES


def test_sub_window_never_leaves_frozen_window():
    p = plan('2026-08-01 00:00:00', '2026-08-02 00:00:00')
    with pytest.raises(ValueError, match='outside'):
        ex.track_request(p, datetime(2026, 7, 31), datetime(2026, 8, 1, 12))


def test_segments_must_tile_window_and_legacy_envelope_still_parses():
    q = {'person_ref': REF, 'start': '2026-08-01 00:00:00', 'end': '2026-08-02 00:00:00'}
    legacy = v.parse_response('tracks', q, envelope([]), LIMITS, {REF: ID})
    assert legacy['coverage'] == 'unknown' and 'segments' not in legacy
    bad = envelope([])
    bad['data']['segments'] = [{'start': q['start'], 'end': '2026-08-01 12:00:00', 'status': 'ok'}]
    with pytest.raises(v.ContractError):
        v.parse_response('tracks', q, bad, LIMITS, {REF: ID})


def test_time_window_over_31_days_is_clarified_before_dispatch():
    native_tool_scope.check_time_window('2026-08-01 00:00:00', '2026-09-01 00:00:00')
    with pytest.raises(HTTPException) as caught:
        native_tool_scope.check_time_window('2026-03-01 00:00:00', '2026-09-01 00:00:00')
    assert caught.value.status_code == 409 and caught.value.detail['code'] == 'time_range_limit'
    assert caught.value.detail['limits'] == {'max_days': 31}
    with pytest.raises(HTTPException):
        native_tool_scope.check_time_window('2026-09-02 00:00:00', '2026-09-01 00:00:00')


def test_precheck_presets_and_reply_never_exceed_31_days():
    options, values = native_precheck_questions.recent_time_presets(datetime(2026, 9, 27, 12))
    assert len(options) == 3 and set(values) == {o['label'] for o in options}
    for value in values.values():
        native_precheck_questions.check_window(value['start'], value['end'])
    native_precheck_questions.check_window('2026-08-27 12:00:00', '2026-09-27 12:00:00')
    with pytest.raises(HTTPException):
        native_precheck_questions.check_window('2026-06-27 12:00:00', '2026-09-27 12:00:00')


@pytest.mark.parametrize('label,days', [('近7天', 7), ('近一个月', 30), ('近三个月', 90), ('近半年', 182),
                                        ('2026-03-01 至 2026-09-01', 184), ('其他', None)])
def test_option_span_reading(label, days):
    got = question_contract.label_span_days(label)
    assert (got is None) if days is None else round(got) == days


def test_model_time_options_over_31_days_are_dropped():
    questions = [{'header': '时间范围', 'question': '查询哪个时段？', 'options': [
        {'label': '近7天'}, {'label': '近一个月'}, {'label': '近三个月'}, {'label': '近半年'}]},
        {'header': '地点', 'question': '哪里？', 'options': [{'label': '近三个月常去地点'}]}]
    kept = question_contract.limit_time_options(questions, date(2026, 9, 27))
    assert [o['label'] for o in kept[0]['options']] == ['近7天', '近一个月']
    assert kept[1]['options'] == [{'label': '近三个月常去地点'}]
    only_long = question_contract.limit_time_options(
        [{'header': '时间范围', 'question': '', 'options': [{'label': '近半年'}]}], date(2026, 9, 27))
    labels = [o['label'] for o in only_long[0]['options']]
    assert labels and all(question_contract.label_span_days(x) <= 31 for x in labels)


def test_failure_messages_carry_limits():
    with pytest.raises(HTTPException) as caught:
        provider_contracts.contract_error('time_range_limit', LIMITS)
    detail = public(caught.value.detail)
    assert detail['code'] == 'time_range_limit' and '31 天' in detail['message']
    assert detail['dispatch_status'] == 'not_dispatched'
    assert all('超出接口限制' in text for text in detail['field_errors'].values())
    rows = public({'code': 'provider_rows_limit'}, 'provider_complete')
    assert rows['code'] == 'provider_rows_limit' and rows['stage'] == 'response'
    assert public({'code': 'number_out_of_range', 'limits': {'max_radius_m': 5000}})['message'].count('5000') == 1


def test_source_links_do_not_collide_on_shared_prefixes():
    from control import table_answer
    ids = [f'run:call:snapshot:{i}' for i in range(1, 13)]
    view = {'version': table_answer.VERSION, 'run_id': 'run', 'basic': [], 'missing': [], 'preview_count': 12, 'total': 12,
            'conclusions': [{'text': '人员轨迹：本次取得 12 条来源记录。', 'source_ids': ids}],
            'evidence': [{'module': 'tracks', 'label': '人员轨迹', 'time': f'2025-07-01 0{i % 10}:00:00', 'text': f'点位{i}',
                          'source_ids': [rid], 'source_run_id': 'run', 'snapshot_id': 'snapshot'} for i, rid in enumerate(ids, 1)]}
    md = table_answer.markdown(view)
    assert '[来源10](#source-run-10)' in md and '[来源12](#source-run-12)' in md
    assert '(#source-run-1)0' not in md and '(#source-run-1)1' not in md


@pytest.mark.parametrize('status,code', [('rejected', None), ('rejected', 'provider_result_unknown'), ('completed', 'provider_rows_limit')])
def test_rejected_requires_determinate_failure_code(status, code):
    state = ProviderState.__new__(ProviderState)
    with pytest.raises(HTTPException):
        state.complete('uid', 'run', 1, 'op', 'tracks', status, error_code=code)
