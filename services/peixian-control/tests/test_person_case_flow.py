"""Unit tests for person-to-case stay points and plan."""
from control import person_case_flow as pcf
from control import theft_scoring as s


def _track(rid, lon, lat, time, name='点位A'):
    return {
        'record_id': rid, 'module': 'tracks', 'snapshot_id': 'snap',
        'source_run_id': 'run', 'call_id': 'c', 'result_digest': 'd',
        'fields': {'lon': lon, 'lat': lat, 'captureTime': time, 'deviceName': name},
    }


def test_stay_points_cluster_and_domicile_demote():
    tracks = [
        _track('t1', 117.19, 34.73, '2026-09-10 02:00:00', '幸福路1号'),
        _track('t2', 117.1901, 34.7301, '2026-09-10 02:30:00', '幸福路1号'),
        _track('t3', 117.20, 34.74, '2026-09-10 14:00:00', '工业园门口'),
    ]
    centers = pcf.stay_points_from_tracks(tracks, domicile='沛县幸福路1号小区')
    assert len(centers) >= 1
    assert centers[0]['coordinate_reusable'] is True
    # domicile-like cluster should not always rank first if demoted
    labels = [c['label'] for c in centers]
    assert any('工业园' in x or '幸福' in x for x in labels)


def test_authorize_centers_max_three():
    tracks = [
        _track(f't{i}', 117.19 + i * 0.01, 34.73 + i * 0.01, f'2026-09-10 0{i}:00:00', f'点{i}')
        for i in range(5)
    ]
    centers = pcf.stay_points_from_tracks(tracks)
    auth = pcf.authorize_centers(centers, n=5)
    assert len(auth) <= 3
    assert auth[0]['source_ref']['record_id']


def test_case_checks_grades_and_sort():
    tracks = [
        {'record_id': 't1', 'module': 'tracks', 'fields': {
            'lon': 117.19, 'lat': 34.73, 'captureTime': '2026-09-10 02:00:00', 'deviceName': '摄像头A'}},
    ]
    incidents = [
        {'record_id': 'i1', 'module': 'incidents', 'fields': {
            'cjbh': '远', 'cjsj': '2026-09-01 12:00:00', 'gisX': 118.0, 'gisY': 35.0}},
        {'record_id': 'i2', 'module': 'incidents', 'fields': {
            'cjbh': '近', 'cjsj': '2026-09-10 02:20:00', 'gisX': 117.1902, 'gisY': 34.7301}},
    ]
    view = s.case_checks(tracks, incidents)
    assert view['items'][0]['cjbh'] == '近'
    assert view['items'][0].get('grade')
    assert view['items'][0].get('reasons')
    assert view['items'][0].get('next_checks')


def test_coverage_appendix_rows():
    plan = {'coverage': {k: 'pending' for k in pcf.ALL_KINDS}}
    plan['coverage']['tracks'] = 'done'
    rows = pcf.coverage_appendix(plan)
    assert len(rows) == 8
    assert ('轨迹', '已查') in rows
