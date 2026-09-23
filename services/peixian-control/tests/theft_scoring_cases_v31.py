# P39-P48 acceptance corpus for bidirectional theft review (native-intent-context-v5).
cases = [
    {"id": "P39", "direction": "case_to_person", "text": "某地发生盗窃", "scoring_requested": False},
    {"id": "P40", "direction": "case_to_person", "text": "核验前3名并评分", "scoring_requested": True, "candidate_authorized": True},
    {"id": "P41", "direction": "case_to_person", "text": "给所有人打分", "scoring_requested": False},
    {"id": "P42", "direction": "person_to_case", "text": "查此人相关案件", "scoring_requested": False},
    {"id": "P43", "direction": "person_to_case", "text": "判定他实施了这些案件", "scoring_requested": True},
    {"id": "P44", "direction": "case_to_person", "text": "谁是作案人", "scoring_requested": True},
    {"id": "P45", "direction": "case_to_person", "text": "对前2名查预警", "scoring_requested": True, "candidate_authorized": True},
    {"id": "P46", "direction": "unknown", "text": "你好", "scoring_requested": False},
    {"id": "P47", "direction": "case_to_person", "text": "查近期仅盗窃警情", "scoring_requested": False},
    {"id": "P48", "direction": "person_to_case", "text": "以轨迹点查周边警情", "scoring_requested": False},
]
