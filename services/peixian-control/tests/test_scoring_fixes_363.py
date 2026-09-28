import asyncio

import pytest

from shared import theft_provider_v2 as v
from gateway import theft_provider_execution as ex
from control import theft_scoring as s
from control import table_answer, theft_planner
from test_provider_contract_v2 import LIMITS

AREA = {'lon': '116.9355', 'lat': '34.721', 'radius_m': '2000', 'page': 1, 'page_size': 20}


def incident(i, when='2026-09-15 03:20:08', lon=116.9355, lat=34.721):
    return {'cjbh': f'C{i:04d}', 'cjsj': when, 'gisX': lon, 'gisY': lat, 'cjxz': '龙城小区'}


def area_plan():
    return {'query': AREA, 'limits': {'max_rows': 100},
            'request': {'connection_group': 'police', 'method': 'POST', 'path': '/jq/search',
                        'json': {'lon': '116.9355', 'lat': '34.721', 'scope': 2.0, 'pageNum': 1, 'pageSize': 20}}}


def pager(total):
    calls = []

    async def invoke(req):
        calls.append(dict(req['json']))
        page, size = req['json']['pageNum'], req['json']['pageSize']
        rows = [incident(i) for i in range((page - 1) * size, min(total, page * size))]
        return {'code': 200, 'data': {'rows': rows, 'total': total, 'pageNum': page, 'pageSize': size}}
    return invoke, calls


def test_incidents_read_all_pages_and_parse_complete():
    invoke, calls = pager(250)
    merged = asyncio.run(ex.collect_incidents(area_plan(), invoke))
    assert [c['pageNum'] for c in calls] == [1, 2, 3] and {c['pageSize'] for c in calls} == {100}
    assert len(merged['data']['rows']) == 250 and 'pageNum' not in merged['data']
    assert [p['count'] for p in merged['data']['pages']] == [100, 100, 50]
    result = v.parse_response('incidents', AREA, merged, LIMITS, {})
    assert result['coverage'] == 'complete' and result['has_more'] is False and len(result['records']) == 250


def test_incidents_page_cap_marks_partial():
    invoke, calls = pager(900)
    merged = asyncio.run(ex.collect_incidents(area_plan(), invoke))
    assert len(calls) == ex.INCIDENT_MAX_PAGES and len(merged['data']['rows']) == 500
    result = v.parse_response('incidents', AREA, merged, LIMITS, {})
    assert result['coverage'] == 'partial' and result['has_more'] is True
    assert 'incidents_pages_limit' in result['missing']


def test_incident_page_receipts_must_account_for_rows():
    invoke, _ = pager(120)
    merged = asyncio.run(ex.collect_incidents(area_plan(), invoke))
    merged['data']['pages'][1]['count'] = 5
    with pytest.raises(v.ContractError):
        v.parse_response('incidents', AREA, merged, LIMITS, {})


def track(rid, when, lon=116.9355, lat=34.721):
    return {'module': 'tracks', 'record_id': rid, 'fields': {'lon': lon, 'lat': lat, 'captureTime': when}}


def inc(rid, when, lon=116.9355, lat=34.721):
    return {'module': 'incidents', 'record_id': rid, 'fields': {'cjbh': rid, 'cjsj': when, 'gisX': lon, 'gisY': lat}}


def test_d5_ignores_old_incidents_and_scores_one_pair():
    tracks = [track('t1', '2026-09-15 02:50:00'), track('t2', '2026-09-01 12:00:00', lon=117.2, lat=34.9)]
    old_close = inc('old', '2025-09-15 03:00:00')
    recent_far = inc('far', '2026-09-01 12:30:00', lon=116.99, lat=34.75)
    recent_close = inc('near', '2026-09-15 03:20:08', lon=116.936, lat=34.7212)
    d5 = s.score_d5(tracks + [old_close, recent_far, recent_close])
    assert d5['status'] == 'available' and d5['score'] == 8 + 4
    assert set(d5['source_ids']) == {'t1', 'near'}
    only_old = s.score_d5(tracks + [old_close], frozenset({'tracks', 'incidents'}))
    assert only_old['status'] == 'available' and only_old['score'] == 0 and '时间窗内无' in only_old['evidence']


def test_d5_pairs_distance_and_time_from_the_same_incident():
    tracks = [track('t1', '2026-09-10 12:00:00')]
    near_but_later = inc('a', '2026-09-16 12:00:00')
    far_but_same_time = inc('b', '2026-09-10 12:10:00', lon=117.0, lat=34.721)
    d5 = s.score_d5(tracks + [near_but_later, far_but_same_time])
    assert d5['score'] == 8 + 1 and set(d5['source_ids']) == {'t1', 'a'}


def test_case_checks_drop_incidents_outside_track_window():
    tracks = [track('t1', '2026-09-15 02:50:00')]
    view = s.case_checks(tracks, [inc('old', '2025-01-01 00:00:00'), inc('near', '2026-09-15 03:20:08')])
    assert [row['cjbh'] for row in view['items']] == ['near']


def test_case_reference_prefers_stated_time_then_matching_incident():
    stated = s.case_reference('116.9355', '34.721', '2026-09-15 03:20:08')
    assert stated['time'].hour == 3 and stated['record_id'] is None
    incidents = [inc('far', '2026-09-15 03:00:00', lon=116.95), inc('old', '2025-09-15 03:00:00'), inc('hit', '2026-09-15 03:20:08', lon=116.9356)]
    matched = s.case_reference('116.9355', '34.721', None, incidents, '2026-08-31 03:20:08', '2026-09-16 03:20:08')
    assert matched['record_id'] == 'hit'
    assert s.case_reference('116.9355', '34.721', None, [], '2026-08-31 03:20:08', '2026-09-16 03:20:08')['time'] is None


def test_case_to_person_d5_three_ways():
    rows = [track('t1', '2026-09-15 03:00:00', lon=116.936, lat=34.7212)]
    ref = s.case_reference('116.9355', '34.721', '2026-09-15 03:20:08')
    assert s.score_d5_case(rows, ref)['score'] == 12
    assert s.score_d5_case(rows, s.case_reference('116.9355', '34.721'))['evidence'] == '缺少案发时间'
    assert s.score_d5_case([], ref)['evidence'] == '未补查轨迹'
    view = s.rank({'person-a': rows}, case_ref=ref)
    d5 = next(d for d in view['insufficient'][0]['scoring']['dimensions'] if d['id'] == 'd5')
    assert d5['status'] == 'available'
    plain = s.rank({'person-a': rows}, include_d5=False)
    d5 = next(d for d in plain['insufficient'][0]['scoring']['dimensions'] if d['id'] == 'd5')
    assert d5['evidence'] == '本次排序不计时空耦合'


def test_table_answer_case_reference_uses_confirmed_values():
    context = {'confirmed': {'lon': '116.9355', 'lat': '34.721', 'start': '2026-08-31 03:20:08', 'end': '2026-09-16 03:20:08'},
               'capture_conditions': {'start': '2026-08-31 03:20:08', 'end': '2026-09-16 03:20:08'}}
    ref = table_answer.case_reference(context, [inc('hit', '2026-09-15 03:20:08')])
    assert ref['record_id'] == 'hit'


def slots(text):
    return {x['field']: x['value'] for x in theft_planner.slots(text).values()}


def test_slots_reads_case_time_without_breaking_window():
    values = slots('处警时间：2026-09-15 03:20:08，查 2026-08-31 03:20:08 至 2026-09-16 03:20:08 的抓拍')
    assert values['case_time'] == '2026-09-15 03:20:08'
    assert values['start'] == '2026-08-31 03:20:08' and values['end'] == '2026-09-16 03:20:08'
    with pytest.raises(Exception):
        slots('案发时间 2026-09-15 03:20:08，处警时间 2026-09-15 04:00:00')


def test_subject_ref_survives_across_runs():
    prior = {'native_calls': {'c2': {'status': 'completed', 'frozen': {'kind': 'tracks', 'query': {'person_ref': 'person-a'}}}}}
    result = {'records': [{'record_id': 'r2', 'call_id': 'c2', 'module': 'tracks', 'fields': {}}]}
    kept = table_answer.select_records(result, prior, None, subjects={'person-a'})
    assert kept[0]['subject_ref'] == 'person-a'
    current = {'native_calls': {}}
    assert s.subject_of(kept[0], current) == 'person-a'
    assert s.group_by_person(kept, current) == {'person-a': kept}
