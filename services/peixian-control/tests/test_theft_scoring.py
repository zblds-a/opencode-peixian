"""Unit tests for theft-score-v1 deterministic scoring."""
from control import theft_scoring as s


def rec(module, rid, **fields):
    return {'record_id': rid, 'module': module, 'fields': fields, 'snapshot_id': 'snap', 'source_run_id': 'run', 'call_id': 'c'}


def test_buckets_and_ready_status():
    records = [
        rec('captures', 'r1', capture_count=7, tags='夜间活动'),
        rec('night', 'r2'),
        rec('night', 'r3'),
        rec('community', 'r4', communityCount=5),
        rec('warning_detail', 'r5', warningCount=4),
    ]
    view = s.compute(records)
    assert view['status'] == 'ready'
    assert view['version'] == 'theft-score-v1'
    by_id = {d['id']: d for d in view['dimensions']}
    assert by_id['d1']['score'] == 18
    assert by_id['d2']['score'] == 8
    assert by_id['d3']['score'] == 8
    assert by_id['d4']['score'] == 14
    assert by_id['d5']['status'] == 'unavailable'
    assert by_id['d6']['score'] == 5
    assert view['available_count'] >= 3
    assert view['earned'] == 18 + 8 + 8 + 14 + 5
    assert view['band']


def test_missing_dimensions_not_zero():
    view = s.compute([rec('captures', 'r1', capture_count=0)])
    assert view['status'] == 'insufficient'
    by_id = {d['id']: d for d in view['dimensions']}
    assert by_id['d1']['score'] == 0 and by_id['d1']['status'] == 'available'
    assert by_id['d2']['status'] == 'unavailable' and by_id['d2']['score'] is None
    assert view['earned'] is None


def test_d5_distance_and_time():
    records = [
        rec('tracks', 't1', lon=118.0, lat=34.0, captureTime='2026-09-10 12:00:00'),
        rec('incidents', 'i1', gisX=118.001, gisY=34.0, cjsj='2026-09-10 12:30:00'),
        rec('captures', 'c1', capture_count=12, tags='盗窃前科'),
        rec('night', 'n1'),
        rec('night', 'n2'),
        rec('night', 'n3'),
        rec('night', 'n4'),
        rec('warning_detail', 'w1', warningCount=6),
    ]
    view = s.compute(records)
    by_id = {d['id']: d for d in view['dimensions']}
    assert by_id['d5']['status'] == 'available'
    # ~111m → space 8; 0.5h → time 4 → 12
    assert by_id['d5']['score'] == 12
    assert by_id['d1']['score'] == 25
    assert by_id['d6']['score'] == 8
    assert '直线' in by_id['d5']['limitation'] or '路网' in by_id['d5']['limitation']


def test_community_under_four_is_zero():
    records = [
        rec('community', 'r1', communityCount=2),
        rec('captures', 'r2', capture_count=1),
        rec('night', 'r3'),
    ]
    view = s.compute(records)
    assert {d['id']: d['score'] for d in view['dimensions'] if d['status'] == 'available'}['d3'] == 0


def test_warning_does_not_use_deduct_score():
    records = [
        rec('warning_detail', 'r1', warningCount=1, deductScore=99),
        rec('captures', 'r2', capture_count=3),
        rec('profile', 'r3', person={'sfz': 'x'}, captures=[]),
    ]
    view = s.compute(records)
    by_id = {d['id']: d for d in view['dimensions']}
    assert by_id['d4']['score'] == 8
    assert 'deductScore' not in by_id['d4']['evidence']
