"""Unit tests for theft-score-v1 person grouping and ranking."""
from control import theft_scoring as s


def rec(module, rid, person=None, **fields):
    item = {'record_id': rid, 'module': module, 'fields': fields, 'snapshot_id': 'snap',
            'source_run_id': 'run', 'call_id': 'c', 'result_digest': 'digest'}
    if person and module == 'captures':
        item['fields'].setdefault('target_id_card', person)
    return item


def test_group_by_person_does_not_mix_subjects():
    records = [
        rec('captures', 'a1', person='person-a', capture_count=7, tags='夜间'),
        rec('captures', 'b1', person='person-b', capture_count=2, tags='盗窃'),
        rec('night', 'n1'),
    ]
    snap = {'native_calls': {'c': {'status': 'completed', 'frozen': {'query': {'person_ref': 'person-a'}, 'kind': 'night'}}}}
    # night without subject_of from fields uses snapshot call
    groups = s.group_by_person(records, snap)
    assert set(groups) >= {'person-a', 'person-b'}
    assert {r['record_id'] for r in groups['person-a']} == {'a1', 'n1'}
    assert {r['record_id'] for r in groups['person-b']} == {'b1'}


def test_stage1_rank_orders_by_capture_only():
    records = [
        rec('captures', 'a1', person='person-a', capture_count=12, tags='盗窃前科', target_name='甲'),
        rec('captures', 'b1', person='person-b', capture_count=1, tags='', target_name='乙'),
        rec('captures', 'c1', person='person-c', capture_count=7, tags='夜间', target_name='丙'),
    ]
    view = s.stage1_rank(records)
    assert view['status'] == 'ready'
    assert [x['person_ref'] for x in view['items']][0] == 'person-a'
    assert view['items'][0]['stage'] == '初排'
    assert all(x['rank'] == i for i, x in enumerate(view['items'], 1))


def test_rank_full_six_dim_per_person():
    by_person = {
        'person-a': [
            rec('captures', 'a1', person='person-a', capture_count=7, tags='夜间'),
            rec('night', 'n1'),
            rec('community', 'c1', communityCount=5),
            rec('warning_detail', 'w1', warningCount=3),
        ],
        'person-b': [
            rec('captures', 'b1', person='person-b', capture_count=1),
        ],
    }
    snap = {'native_calls': {'c': {'status': 'completed', 'frozen': {'query': {'person_ref': 'person-a'}, 'kind': 'night'}}}}
    # attach person for night via subject - manually set fields
    by_person['person-a'][1]['fields']['targetIdCard'] = 'person-a'
    by_person['person-a'][2]['fields']['idCard'] = 'person-a'
    by_person['person-a'][3]['fields']['idCard'] = 'person-a'
    view = s.rank(by_person, include_d5=False)
    assert view['items'][0]['person_ref'] == 'person-a'
    assert view['items'][0]['status'] == 'ready'
    assert any(x['person_ref'] == 'person-b' for x in view['insufficient'])


def test_case_checks_pending_only():
    tracks = [rec('tracks', 't1', lon=118.0, lat=34.0, captureTime='2026-09-10 12:00:00')]
    incidents = [rec('incidents', 'i1', gisX=118.001, gisY=34.0, cjsj='2026-09-10 12:30:00', cjbh='CJ1')]
    view = s.case_checks(tracks, incidents)
    assert view['items'][0]['status'] == '待核验'
    assert view['items'][0]['distance_m'] is not None


def test_compute_single_person_buckets():
    records = [
        rec('captures', 'r1', person='person-a', capture_count=7, tags='夜间'),
        rec('night', 'r2'),
        rec('night', 'r3'),
        rec('community', 'r4', communityCount=5),
        rec('warning_detail', 'r5', warningCount=4),
    ]
    for r in records:
        if r['module'] != 'captures':
            r['fields']['targetIdCard' if r['module'] == 'night' else 'idCard'] = 'person-a'
    view = s.compute(records, include_d5=False)
    assert view['status'] == 'ready'
    by_id = {d['id']: d for d in view['dimensions']}
    assert by_id['d1']['score'] == 18
    assert by_id['d5']['status'] == 'unavailable'


def test_reasons_and_next_checks_on_stage1():
    import control.theft_scoring as s
    records = [
        rec('captures', 'a', 'person-a', capture_count=12, tags='盗窃', target_name='甲'),
        rec('captures', 'b', 'person-b', capture_count=1, tags='', target_name='乙'),
    ]
    view = s.stage1_rank(records)
    assert view['title'].startswith('初步关注排序')
    top = view['items'][0]
    assert top['reasons']
    assert top['next_checks']
    assert '抓拍' in top['reasons'][0] or '标签' in ''.join(top['reasons'])
