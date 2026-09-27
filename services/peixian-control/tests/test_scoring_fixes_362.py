from control import theft_scoring as s
from control import theft_candidates, table_answer
from control import theft_planner
from shared import theft_provider_v2 as adapter
import pytest
from fastapi import HTTPException


def slots(text):
    return {v['field']: v['value'] for v in theft_planner.slots(text).values()}


KEY = 'k' * 32
ID = '320322198503061234'


class Store:
    worker_key = KEY

    def __init__(self, snapshots):
        self.snapshots = snapshots

    def rows(self, sql, params):
        return [{'id': rid, 'request_ciphertext': snap} for rid, snap in self.snapshots]

    def decrypt(self, value):
        return value


def capture_run(task_id='t1', status='completed'):
    return ('run-1', {
        'native_tool_context': {'task_id': task_id},
        'native_calls': {'call-a': {'status': status, 'frozen': {'kind': 'captures'}}},
        'provider_state': {'modules': {'call-a': {'status': 'completed', 'response': {
            'response_snapshot_id': 'snap-1',
            'records': [{'source_ref': 'r0', 'fields': {'target_id_card': '320322197811203456', 'target_name': '王芳'}},
                        {'source_ref': 'r1', 'fields': {'target_id_card': ID, 'target_name': '张建国'}}]}}}},
    })


def test_capture_person_resolves_from_current_run_raw_rows():
    ref = adapter.person_ref(adapter.person_id(ID), KEY.encode(), 'u/s')
    store = Store([capture_run()])
    found = theft_candidates.find_capture_person(store, 'u', 's', {'task_id': 't1'}, ref)
    assert found['identity'] == ID and found['name'] == '张建国'
    assert found['record_id'] == 'run-1:call-a:r1' and found['snapshot_id'] == 'snap-1'
    assert theft_candidates.resolve_capture_person(store, 'u', 's', {'task_id': 't1'}, ref) == (ID, ref)


def test_capture_person_ignores_other_tasks_and_unknown_refs():
    ref = adapter.person_ref(adapter.person_id(ID), KEY.encode(), 'u/s')
    assert theft_candidates.find_capture_person(Store([capture_run('t2')]), 'u', 's', {'task_id': 't1'}, ref) is None
    assert theft_candidates.find_capture_person(Store([capture_run(status='rejected')]), 'u', 's', {'task_id': 't1'}, ref) is None
    other = adapter.person_ref(adapter.person_id(ID), KEY.encode(), 'u/other')
    with pytest.raises(HTTPException):
        theft_candidates.resolve_capture_person(Store([capture_run()]), 'u', 's', {'task_id': 't1'}, other)


def test_zero_row_query_scores_zero_not_unavailable():
    records = [{'module': 'night', 'record_id': 'n1', 'fields': {}},
               {'module': 'warning_detail', 'record_id': 'w1', 'fields': {'warningCount': 3}}]
    before = s.compute(records)
    assert before['status'] == 'insufficient'
    view = s.compute(records, queried={'night', 'community', 'warning_detail', 'tracks', 'incidents'})
    dims = {d['id']: d for d in view['dimensions']}
    assert dims['d3']['status'] == 'available' and dims['d3']['score'] == 0
    assert dims['d5']['status'] == 'available' and dims['d5']['score'] == 0
    assert dims['d1']['status'] == 'unavailable'
    assert view['status'] == 'ready' and view['available_max'] == 20 + 15 + 20 + 12


def test_d5_still_unavailable_when_incidents_never_queried():
    records = [{'module': 'tracks', 'record_id': 't1', 'fields': {'lon': 116.9, 'lat': 34.7, 'captureTime': '2026-09-15 03:00:00'}}]
    d5 = s.score_d5(records, frozenset({'tracks'}))
    assert d5['status'] == 'unavailable' and '警情' in d5['evidence']


def test_queried_kinds_scopes_person_calls_and_counts_location_calls():
    snapshot = {'native_calls': {
        'c1': {'status': 'completed', 'frozen': {'kind': 'community', 'query': {'person_ref': 'person-a'}}},
        'c2': {'status': 'completed', 'frozen': {'kind': 'night', 'query': {'person_ref': 'person-b'}}},
        'c3': {'status': 'completed', 'frozen': {'kind': 'incidents', 'query': {'lon': '1', 'lat': '2'}}},
        'c4': {'status': 'rejected', 'frozen': {'kind': 'profile', 'query': {'person_ref': 'person-a'}}},
    }}
    policy = {'queried': [['warning_detail', 'person-a']]}
    assert table_answer.queried_kinds(policy, snapshot, 'person-a') == {'community', 'incidents', 'warning_detail'}


def test_slots_reads_coordinate_pair_and_radius_within():
    text = 'CASE-2025-001 龙城小区入室盗窃，坐标 116.9355, 34.721。查案发点 500 米内 2026-08-31 03:20:08 至 2026-09-16 03:20:08 的抓拍人员'
    values = slots(text)
    assert values['lon'] == '116.9355' and values['lat'] == '34.721' and values['radius_m'] == 500
    assert slots('坐标（34.721，116.9355），方圆2公里以内')['lon'] == '116.9355'
    assert slots('坐标（34.721，116.9355），方圆2公里以内')['radius_m'] == 2000


def test_slots_labeled_values_win_and_conflicts_are_ambiguous():
    values = slots('坐标 116.9355, 34.721 经度：116.9355；纬度：34.721 半径：500 米 查 500 米内')
    assert values['lon'] == '116.9355' and values['radius_m'] == 500
    with pytest.raises(HTTPException):
        slots('坐标 116.9355, 34.721，另一个坐标 117.1, 34.8')
    with pytest.raises(HTTPException):
        slots('查 300 米内和 500 米内')
