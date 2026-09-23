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
