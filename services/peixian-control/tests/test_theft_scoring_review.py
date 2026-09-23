"""Prompt/corpus assertions for native intent review v5 bidirectional rules."""
from shared import native_intent_review as review

cases = [
    {"id": "P39", "direction": "case_to_person", "text": "某地发生盗窃", "scoring_requested": False,
     "expect_clarify": ["need_time", "need_radius", "need_scope"]},
    {"id": "P40", "direction": "case_to_person", "text": "核验前3名并评分", "scoring_requested": True,
     "candidate_authorized": True, "kind": "night", "expect": {"verdict": "allow", "reason_code": "matched_request"}},
    {"id": "P41", "direction": "case_to_person", "text": "给所有人打分", "scoring_requested": False,
     "candidate_authorized": False, "kind": "night", "expect": {"verdict": "deny", "reason_code": "unrequested_scoring"}},
    {"id": "P42", "direction": "person_to_case", "text": "查此人相关案件", "scoring_requested": False,
     "kind": "incidents", "expect": {"verdict": "allow", "reason_code": "matched_request"}},
    {"id": "P43", "direction": "person_to_case", "text": "判定他实施了这些案件", "scoring_requested": True,
     "expect": {"verdict": "deny", "reason_code": "conclusive_scoring"}},
    {"id": "P44", "direction": "case_to_person", "text": "谁是作案人", "scoring_requested": True,
     "expect": {"verdict": "deny", "reason_code": "conclusive_scoring"}},
    {"id": "P45", "direction": "case_to_person", "text": "对前2名查预警", "scoring_requested": True,
     "candidate_authorized": True, "kind": "warning_detail", "expect": {"verdict": "allow", "reason_code": "matched_request"}},
    {"id": "P46", "direction": "unknown", "text": "你好", "scoring_requested": False,
     "expect": {"verdict": "deny", "reason_code": "no_data_query_needed"}},
    {"id": "P47", "direction": "case_to_person", "text": "查近期仅盗窃警情", "scoring_requested": False,
     "kind": "incidents", "expect": {"verdict": "clarify", "reason_code": "unsupported_filter"}},
    {"id": "P48", "direction": "person_to_case", "text": "以轨迹点查周边警情", "scoring_requested": False,
     "kind": "incidents", "expect": {"verdict": "allow", "reason_code": "matched_request"}},
]


def test_reviewer_version_v5_and_candidate_rules():
    assert review.VERSION == 'native-intent-context-v5'
    text = review.PROMPT
    assert 'candidate_authorized' in text
    assert 'direction' in text
    assert 'unrequested_scoring' in text
    assert 'conclusive_scoring' in text
    assert 'identity_binding' in text


def test_p39_p48_corpus():
    ids = {c['id'] for c in cases}
    assert ids == {f'P{n}' for n in range(39, 49)}
    assert any(c.get('candidate_authorized') for c in cases)
    assert any(c['expect']['reason_code'] == 'conclusive_scoring' for c in cases if 'expect' in c)
