from control.theft_candidates import candidate_request_n, authorize, find
from control.native_tool_scope import infer_direction, scoring_requested
import pytest
from fastapi import HTTPException


def test_candidate_request_n_parser():
    assert candidate_request_n('请核验前3名') == 3
    assert candidate_request_n('对前5人评分') == 5
    assert candidate_request_n('前2名核验') == 2
    assert candidate_request_n('核验前10名') is None
    assert candidate_request_n('查夜间') is None


def test_authorize_top_n_and_reject_empty():
    ranked = [
        {'person_ref': 'person-a', 'record_id': 'r1', 'run_id': 'run', 'snapshot_id': 's', 'result_digest': 'd', 'rate': 80, 'source_ids': ['r1']},
        {'person_ref': 'person-b', 'record_id': 'r2', 'run_id': 'run', 'snapshot_id': 's', 'result_digest': 'd', 'rate': 40, 'source_ids': ['r2']},
    ]
    out = authorize(ranked, 1)
    assert len(out) == 1 and out[0]['person_ref'] == 'person-a' and out[0]['rank'] == 1
    with pytest.raises(HTTPException):
        authorize([], 3)
    with pytest.raises(HTTPException):
        authorize(ranked, 9)


def test_find_only_authorized_refs():
    ctx = {'candidate_set': [{'person_ref': 'person-a', 'rank': 1}]}
    assert find(ctx, 'person-a')['rank'] == 1
    assert find(ctx, 'person-b') is None
    assert find(ctx, 'raw-id') is None


def test_infer_direction_and_scoring_keywords():
    assert infer_direction({'person_identity': 'x'}, [], '查一下') == 'person_to_case'
    assert infer_direction({'lon': 1, 'lat': 2}, [], '附近发生盗窃') == 'case_to_person'
    assert infer_direction({}, [], '你好') == 'unknown'
    assert scoring_requested('筛选嫌疑人列表') is True
    assert scoring_requested('核验前3名') is True
    assert scoring_requested('不要评分') is False


def test_candidate_request_n_phrases():
    from control.theft_candidates import candidate_request_n, reply_authorize_n
    assert candidate_request_n('核验前3名') == 3
    assert candidate_request_n(reply_authorize_n(2)) == 2
    assert candidate_request_n(reply_authorize_n(1)) == 1
    assert candidate_request_n('核验该候选人') == 1


def test_recommend_n_band_and_drop():
    from control.theft_candidates import recommend_n, candidate_request_n, reply_authorize_option
    ranking = {'items': [
        {'rate': 90, 'band': '关联度很高'},
        {'rate': 70, 'band': '关联度较高'},
        {'rate': 50, 'band': '关联度中等'},
        {'rate': 10, 'band': '关联度较低'},
    ]}
    # 90→70 drops >=15, cut before second
    assert recommend_n(ranking) == 1
    ranking_flat = {'items': [
        {'rate': 55, 'band': '关联度中等'},
        {'rate': 50, 'band': '关联度中等'},
        {'rate': 48, 'band': '关联度中等'},
        {'rate': 10, 'band': '关联度较低'},
    ]}
    assert recommend_n(ranking_flat) == 3
    ranking2 = {'items': [
        {'rate': 95, 'band': '关联度很高'},
        {'rate': 40, 'band': '存在一定关联'},
        {'rate': 35, 'band': '存在一定关联'},
    ]}
    assert recommend_n(ranking2) == 1
    assert recommend_n({'items': []}) == 1
    assert candidate_request_n(reply_authorize_option(3, 3)) == 3
    assert candidate_request_n('核验前2名（推荐）') == 2


def test_build_enrichment_plan_progress():
    from control.theft_candidates import build_enrichment_plan
    candidates = [
        {'rank': 1, 'person_ref': 'person-a', 'name': '甲'},
        {'rank': 2, 'person_ref': 'person-b', 'name': '乙'},
    ]
    plan = build_enrichment_plan(candidates)
    assert plan['pending'] == 8 and plan['complete'] is False
    records = [
        {'module': 'night', 'fields': {'targetIdCard': 'person-a'}, 'record_id': 'n1'},
        {'module': 'community', 'fields': {'targetIdCard': 'person-a'}, 'record_id': 'c1'},
        {'module': 'warning_detail', 'fields': {'targetIdCard': 'person-a'}, 'record_id': 'w1'},
        {'module': 'profile', 'fields': {'person': {'sfz': 'person-a'}}, 'record_id': 'p1'},
        {'module': 'night', 'fields': {'targetIdCard': 'person-b'}, 'record_id': 'n2'},
        {'module': 'community', 'fields': {'targetIdCard': 'person-b'}, 'record_id': 'c2'},
        {'module': 'warning_detail', 'fields': {'targetIdCard': 'person-b'}, 'record_id': 'w2'},
        {'module': 'profile', 'fields': {'person': {'sfz': 'person-b'}}, 'record_id': 'p2'},
    ]
    plan2 = build_enrichment_plan(candidates, records=records)
    assert plan2['complete'] is True and plan2['pending'] == 0
