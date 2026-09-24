from control.native_tool_scope import scoring_requested, infer_direction


def test_scoring_requested_keywords_and_negation():
    assert scoring_requested('请对该人做可疑度评分') is True
    assert scoring_requested('帮我打分') is True
    assert scoring_requested('研判优先级看一下') is True
    assert scoring_requested('筛选嫌疑人列表') is True
    assert scoring_requested('核验前3名') is True
    assert scoring_requested('不要评分，只要档案') is False
    assert scoring_requested('不要排序') is False
    assert scoring_requested('查夜间记录') is False
    assert scoring_requested('继续查档案', {'scoring_requested': True}) is True
    assert scoring_requested('不要评分', {'scoring_requested': True}) is False


def test_case_to_person_defaults_scoring_on():
    assert scoring_requested('查周边抓拍', None, 'case_to_person') is False
    assert scoring_requested('查周边抓拍', None, 'person_to_case') is False
    assert scoring_requested('不要排序', None, 'case_to_person') is False
    assert scoring_requested('继续', {'scoring_requested': False}, 'case_to_person') is False
    assert scoring_requested('继续', {'scoring_requested': True}, 'case_to_person') is True


def test_infer_direction_basic():
    assert infer_direction({'person_identity': 'x'}, [], '') == 'person_to_case'
    assert infer_direction({'lon': 1, 'lat': 2}, [], '附近警情') == 'case_to_person'
    assert infer_direction({}, [], '你好') == 'unknown'
