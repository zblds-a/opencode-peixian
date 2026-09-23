from control.native_tool_scope import scoring_requested


def test_scoring_requested_keywords_and_negation():
    assert scoring_requested('请对该人做可疑度评分') is True
    assert scoring_requested('帮我打分') is True
    assert scoring_requested('研判优先级看一下') is True
    assert scoring_requested('不要评分，只要档案') is False
    assert scoring_requested('查夜间记录') is False
    assert scoring_requested('继续查档案', {'scoring_requested': True}) is True
    assert scoring_requested('不要评分', {'scoring_requested': True}) is False
