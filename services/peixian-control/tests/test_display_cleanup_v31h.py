
"""Display cleanup, multiselect next_question, and stop_followup (20260924h)."""
from control import table_answer
from control import native_tool_scope as scope
from control.theft_provider_result import sentence, track_type_label
from shared import theft_provider_v2 as v2


def test_next_question_multiple_true_by_default():
    q = table_answer.next_question('run-1', [
        {'reply': '补查轨迹', 'reason': 'r', 'action': 'query', 'kind': 'tracks'},
        {'reply': '补查预警', 'reason': 'r', 'action': 'query', 'kind': 'warning_detail'},
    ])
    assert q and q['multiple'] is True
    assert len(q['options']) == 2


def test_next_question_respects_model_multiple_false():
    chosen = {
        'next_question': {
            'header': '下一步分析',
            'question': '请选',
            'multiple': False,
            'options': [{'label': '仅一项', 'description': 'd'}],
        }
    }
    q = table_answer.next_question('run-2', [], chosen=chosen)
    assert q and q['multiple'] is False


def test_next_question_suppressed_when_stop_followup():
    q = table_answer.next_question(
        'run-3',
        [{'reply': '补查', 'reason': 'r', 'action': 'query'}],
        context={'stop_followup': True},
    )
    assert q is None


def test_model_context_mentions_stop_followup():
    text = scope.model_context({
        'scope_version': 1,
        'confirmed': {},
        'source_refs': [],
        'stop_followup': True,
    })
    assert '停止追问' in text
    assert '不要再调用 question' in text


def test_markdown_omits_empty_basic_and_placeholders():
    view = {
        'version': table_answer.VERSION,
        'basic': [],
        'conclusions': [],
        'evidence': [],
        'missing': ['预警类型数量表示来源预警类型数量，不是事件数或个人嫌疑评分。'],
        'preview_count': 0,
        'total': 0,
    }
    md = table_answer.markdown(view)
    assert '人员基本信息' not in md
    assert '档案信息' not in md
    assert '暂无可确认结论' not in md
    assert '判断依据' not in md
    assert '当前展示 0 条' not in md
    assert '预警类型数量表示来源预警类型数量' in md
    assert 'warningCount' not in md


def test_markdown_keeps_basic_when_present():
    view = {
        'version': table_answer.VERSION,
        'basic': [{'label': '姓名', 'value': '甲', 'source_ids': ['r1'], 'obtained_at': 't'}],
        'conclusions': [{'text': '有结论', 'source_ids': ['r1'], 'limitation': '局限'}],
        'evidence': [{'label': '预警概况', 'time': 't', 'text': '摘要', 'source_ids': ['r1'], 'source_run_id': 'run-1', 'snapshot_id': 'snap-1'}],
        'missing': [],
        'preview_count': 1,
        'total': 1,
    }
    md = table_answer.markdown(view)
    assert '### 人员基本信息' in md
    assert '### 基本结论' in md
    assert '### 判断依据' in md
    assert '甲' in md


def test_warning_limitation_is_chinese():
    assert 'warningCount' not in v2.LIMITATIONS['warning_detail']
    assert '预警类型数量' in v2.LIMITATIONS['warning_detail']


def test_wifi_probe_is_nonmotor():
    assert track_type_label({'trackType': 2, 'trackTypeDesc': 'WiFi探针'}) == '非机动车'
    text = sentence('tracks', {'trackType': 2, 'trackTypeDesc': 'WiFi探针',
                               'captureTime': 't', 'deviceId': 'd', 'deviceName': 'n'})
    assert '非机动车' in text
    assert 'WiFi探针' not in text
