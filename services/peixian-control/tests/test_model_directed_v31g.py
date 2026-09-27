"""Model-directed decisions and open authorization (v31g)."""
import json
from control import native_tool_scope as scope
from control import table_answer as t
from control import theft_scoring as s
from control import theft_candidates as c


def test_scoring_defaults_off_for_case_to_person():
    assert scope.scoring_requested('查周边抓拍', None, 'case_to_person') is True
    assert scope.scoring_requested('请做可疑度评分', None, 'case_to_person') is True
    assert scope.scoring_requested('不要评分，只要档案', None, 'case_to_person') is False


def test_arguments_accepts_unconfirmed_values():
    ctx = {
        'confirmed': {},
        'user_conditions': {},
        'source_refs': [{'run_id': 'r', 'record_id': 'r:1', 'snapshot_id': 's', 'result_digest': 'd'}],
        'current_text': '查抓拍',
        'constraints_text': '查抓拍',
        'scope_version': 1,
    }
    # captures requires radius_m + start + end; source_refs present so lon/lat not required
    q = scope.arguments('captures', {
        'radius_m': 500,
        'start': '2026-09-10 20:00:00',
        'end': '2026-09-10 23:00:00',
    }, ctx)
    assert q['radius_m'] == '500'
    assert ctx['confirmed']['radius_m'] == '500'


def test_arguments_page_without_user_request():
    ctx = {
        'confirmed': {'person_identity': '320322199001011234'},
        'user_conditions': {},
        'source_refs': [],
        'current_text': '翻页',
        'constraints_text': '翻页',
        'scope_version': 1,
    }
    q = scope.arguments('night', {
        'person_identity': '320322199001011234',
        'start': '2026-09-10 00:00:00',
        'end': '2026-09-11 00:00:00',
        'page': 2,
        'page_size': 20,
    }, ctx)
    assert q['page'] == 2


def test_model_suggestions_and_next_question():
    chosen = {
        'format': t.VERSION,
        'mode': 'data',
        'direction': 'case_to_person',
        'scoring': {'requested': True},
        'source_refs': ['run:call:a'],
        'suggestions': [
            {'action': 'query', 'kind': 'night', 'text': '补查夜间', 'reply': '查询此人夜间活动记录', 'reason': '补维度'},
            {'action': 'inspect_cases', 'text': '核对案件', 'reply': '核对处警记录原文'},
        ],
        'next_question': {
            'header': '下一步',
            'question': '选一项',
            'options': [{'label': '查询此人夜间活动记录', 'description': '补维度', 'send': True}],
        },
        'case_checks': {
            'items': [{
                'cjbh': 'A1', 'cjsj': '2026-09-10', 'relation': '时空接近',
                'status': '已核对', 'follow_up': '无', 'source_ids': ['run:call:a'],
            }, {
                'cjbh': 'B1', 'source_ids': ['fabricated'],  # dropped
            }],
        },
    }
    snap = {
        'native_tool_context': {
            'confirmed': {}, 'task_id': 't', 'scoring_requested': False,
            'direction': 'unknown', 'candidate_set': [],
        },
        'table_answer_policy': {'version': t.VERSION, 'person_ref': None, 'direction': 'unknown', 'history': []},
        'native_tool_policy': {'allowed_tools': []},
        'native_calls': {
            'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}},
        },
        'model_final_text': json.dumps(chosen, ensure_ascii=False),
    }
    records = [{
        'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap',
        'module': 'captures', 'snapshot_id': 'a',
        'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 3, 'tags': ''},
        'result_digest': 'd',
    }]
    result = {'run_id': 'run', 'generated_at': '2026-09-24T10:00:00+08:00',
              'records': records, 'claims': [], 'missing': []}
    view = t.build(result, snap)
    assert view['direction'] == 'case_to_person'
    assert [x['action'] for x in view['suggestions']] == ['query', 'inspect_cases']
    assert view['suggestions'][0]['reply'] == '查询此人夜间活动记录'
    assert view['next_question']['header'] == '下一步'
    assert view['next_question']['options'][0]['label'] == '查询此人夜间活动记录'
    assert view['case_checks'] and len(view['case_checks']['items']) == 1
    assert view['case_checks']['items'][0]['status'] == '已核对'
    assert s.DISCLAIMER == ''


def test_authorize_allows_large_n():
    items = [{
        'person_ref': f'person-{i}', 'record_id': f'r{i}', 'run_id': 'run',
        'snapshot_id': 's', 'result_digest': 'd', 'rate': 50, 'source_ids': [f'r{i}'],
    } for i in range(1, 12)]
    out = c.authorize(items, 10)
    assert len(out) == 10
