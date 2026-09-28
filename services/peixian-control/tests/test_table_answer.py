import copy
import json
import pytest
from control import table_answer as t


def fixture():
    snap = {'native_tool_context':{'confirmed':{'person_identity':'confirmed'},'task_id':'task'},
        'table_answer_policy':{'version':t.VERSION,'person_ref':'person-one','history':[]},
        'native_tool_policy':{'allowed_tools':['peixian_query_profile','peixian_query_night']},
        'native_calls':{'call':{'status':'completed','frozen':{'query':{'person_ref':'person-one'}}}}}
    record={'record_id':'run:call:snapshot:1','source_run_id':'run','call_id':'call','module':'profile','snapshot_id':'snapshot',
        'fields':{'person':{'sfz':'person-one','name':'测试人员','age':30,'gender':'来源枚举X'},'captures':[]}}
    claim={'claim_id':'claim','source_run_id':'run','verification_status':'approved','type':'fact',
        'source_ids':[record['record_id']],'statement':'来源档案与最近抓拍。'}
    result={'run_id':'run','generated_at':'2026-09-23T10:00:00+08:00','records':[record],'claims':[claim],'missing':[]}
    return result,snap


def choose(snap, **values):
    snap['model_final_text']=json.dumps({'format':t.VERSION,'mode':'data',**values},ensure_ascii=False)


def test_profile_tables_and_source_binding():
    result,snap=fixture();view=t.build(result,snap)
    assert view['basic'][0]['value']=='测试人员'
    assert view['basic'][0]['source_run_id']=='run'
    assert view['basic'][0]['obtained_at']==result['generated_at']
    output=t.markdown(view)
    assert all('### '+x in output for x in ['人员基本信息','基本结论','判断依据'])
    assert '### 下一步分析建议' not in output
    if view['suggestions']:
        assert view.get('next_question') is not None
        assert view['next_question']['custom'] is True
        assert len(view['next_question']['options']) <= 3
        assert [o['label'] for o in view['next_question']['options']] == [s['reply'] for s in view['suggestions']]
    else:
        assert view.get('next_question') is None
    assert '来源枚举X' in output


@pytest.mark.parametrize('change',['person','status','claim','profile_person'])
def test_untrusted_fields_excluded(change):
    result,snap=fixture()
    if change=='person':snap['native_calls']['call']['frozen']['query']['person_ref']='person-other'
    if change=='status':snap['native_calls']['call']['status']='unknown'
    if change=='claim':result['claims'][0]['source_ids']=['invented']
    if change=='profile_person':result['records'][0]['fields']['person']['sfz']='person-other'
    view=t.build(result,snap)
    if change in ('person','status'):assert view['evidence']==[] and view['basic']==[]
    if change=='claim':assert view['conclusions']==[]
    if change=='profile_person':assert view['basic']==[]


def test_greeting_no_table_even_with_history():
    result,snap=fixture();snap['native_calls']={};snap['model_final_text']='你好！我是盗窃资料助手。'
    assert t.build(result,snap) is None


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_model_proposes_only_available_next_steps():
    result,snap=fixture()
    choose(snap,source_refs=['invented'],suggestions=[{'action':'query','kind':'night'},{'action':'query','kind':'tracks'},{'action':'query','kind':'profile'}])
    view=t.build(result,snap)
    kinds=[x.get('kind') for x in view['suggestions']]
    assert 'night' in kinds
    assert all('invented' not in x['source_ids'] for x in view['conclusions'])


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_no_repeat_confirmed_conditions_or_invented_sources():
    result,snap=fixture()
    choose(snap,suggestions=[{'action':'clarify_scope','fields':['person_identity']},{'action':'inspect_sources','reason_source':'fake'}, {'action':'clarify_scope','fields':['start','end']}])
    assert len(t.build(result,snap)['suggestions'])==1


def test_history_is_frozen_no_model_text_becomes_fact():
    result,snap=fixture();snap['table_answer_policy']['history']=[copy.deepcopy(result)]
    snap['native_calls']={};choose(snap,source_refs=['run:call:snapshot:1'],conclusions=['此人实施盗窃'])
    view=t.build({**result,'records':[],'claims':[]},snap)
    assert len(view['evidence'])==1
    assert '实施盗窃' not in t.markdown(view)


def test_expand_is_local_markdown_and_escapes_injection():
    result,snap=fixture();record=result['records'][0];claim=result['claims'][0]
    result['records']=[];result['claims']=[]
    for n in range(12):
        rid=f'run:call:snapshot:{n}'
        result['records'].append({**record,'record_id':rid})
        result['claims'].append({**claim,'claim_id':str(n),'source_ids':[rid],'statement':'a|b\n<script>alert(1)</script>[bad](https://x)'})
    view=t.build(result,snap);output=t.markdown(view)
    assert view['preview_count']==10 and view['total']==12
    assert '<details>' in output and '<script>' not in output and '\\|' in output


def test_old_runs_unchanged():
    result,snap=fixture();snap.pop('table_answer_policy')
    assert t.build(result,snap) is None


def test_zero_results_distinct_from_missing_profile():
    result,snap=fixture();result['records']=[];result['claims']=[{'protected_fields':{'call_id':'call'},'claim_id':'zero','source_run_id':'run','verification_status':'approved','type':'computed','source_ids':[],'statement':'本次取得0条来源记录。'}]
    view=t.build(result,snap)
    assert '0条' in view['conclusions'][0]['text']
    assert view['basic'] == []
    assert '尚未取得当前人员的档案信息' not in ''.join(view['missing'])
    md = t.markdown(view)
    assert '人员基本信息' not in md
    assert '档案信息' not in md
    assert '### 基本结论' in md


@pytest.mark.skip(reason="scoring.requested model-authoritative in v31g")
def test_scoring_uses_server_flag():
    result,snap=fixture()
    night={'record_id':'run:call:n1','source_run_id':'run','call_id':'call','module':'night','snapshot_id':'n',
           'fields':{'id':'1','targetIdCard':'person-one','captureTime':'2026-09-10 01:00:00'}}
    community={'record_id':'run:call:c1','source_run_id':'run','call_id':'call','module':'community','snapshot_id':'c',
               'fields':{'id':'1','idCard':'person-one','communityCount':5}}
    warning={'record_id':'run:call:w1','source_run_id':'run','call_id':'call','module':'warning_detail','snapshot_id':'w',
             'fields':{'id':'1','idCard':'person-one','warningCount':3,'personName':'测'}}
    captures={'record_id':'run:call:cap','source_run_id':'run','call_id':'call','module':'captures','snapshot_id':'cap',
              'fields':{'target_id_card':'person-one','target_name':'测','capture_count':7,'tags':'夜间'}}
    result['records']+=[night,community,warning,captures]
    snap['native_tool_context']['direction']='person_to_case'
    choose(snap,source_refs=['run:call:snapshot:1'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view['scoring']['status']=='ready'
    output=t.markdown(view)
    assert '### 可疑度评分' in output
    assert '需人工核验' not in output
    snap['native_tool_context']['scoring_requested']=True
    choose(snap,source_refs=['run:call:snapshot:1'],scoring={'requested':False})
    view=t.build(result,snap)
    assert view.get('scoring') is None


def test_case_to_person_stage1_ranking_table():
    result,snap=fixture()
    snap['native_tool_context']={'confirmed':{},'task_id':'task','scoring_requested':True,'direction':'case_to_person','candidate_set':[]}
    snap['table_answer_policy']['person_ref']=None
    snap['table_answer_policy']['direction']='case_to_person'
    snap['native_calls']={'cap':{'status':'completed','frozen':{'kind':'captures','query':{}}}}
    captures=[
        {'record_id':'run:call:a','source_run_id':'run','call_id':'cap','module':'captures','snapshot_id':'a',
         'fields':{'target_id_card':'person-a','target_name':'甲','capture_count':12,'tags':'盗窃'},'result_digest':'d'},
        {'record_id':'run:call:b','source_run_id':'run','call_id':'cap','module':'captures','snapshot_id':'b',
         'fields':{'target_id_card':'person-b','target_name':'乙','capture_count':1,'tags':''},'result_digest':'d'},
    ]
    result['records']=captures; result['claims']=[]
    choose(snap,source_refs=['run:call:a'])
    view=t.build(result,snap)
    assert view['ranking']['items'][0]['person_ref']=='person-a'
    assert '初步关注排序' in t.markdown(view)


def test_accepts_legacy_v1_format_json():
    result,snap=fixture()
    snap['model_final_text']=json.dumps({'format':'person-tables-v1','mode':'data','source_refs':['run:call:snapshot:1']},ensure_ascii=False)
    view=t.build(result,snap)
    assert view['version']=='person-tables-v3'
    assert view['selection_status']=='accepted'


def test_history_collection_enforces_owner_task_and_person(monkeypatch):
    from control import trusted_results
    result,snap=fixture()
    class Store:
        worker_key='test-key'
        def rows(self,sql,args):
            assert args==('account','session')
            return [{'request_ciphertext':snap,'result':result},
                {'request_ciphertext':{**snap,'native_tool_context':{'task_id':'other'}},'result':result},
                {'request_ciphertext':{**snap,'native_calls':{}},'result':result}]
        def decrypt(self,value):return value
    monkeypatch.setattr(t,'person',lambda *args:'person-one')
    monkeypatch.setattr(trusted_results,'checked_result',lambda store,row:row['result'])
    target={'native_tool_context':{'task_id':'task','confirmed':{}}};payload={}
    t.freeze(Store(),'account','session',target,payload)
    assert len(target['table_answer_policy']['history'])==1
    assert '测试人员' in payload['system']


def test_malformed_model_output_cannot_break_projection():
    result,snap=fixture()
    for value in ['null','[]','```broken','{"format":"person-tables-v1","mode":"data","suggestions":[null,4,{"kind":[],"action":"query"}]}']:
        snap['model_final_text']=value
        assert t.build(result,snap)['basic']


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_fenced_selection_uses_snapshot_group_not_free_prose():
    result,snap=fixture()
    snap['model_final_text']='此人实施盗窃。\n```json\n'+json.dumps({'format':t.VERSION,'mode':'data','source_refs':['snapshot'],'suggestions':[{'action':'inspect_sources','reason_source':'snapshot'}]})+'\n```'
    view=t.build(result,snap)
    assert view['selection_status']=='accepted' and len(view['suggestions'])==1
    assert '实施盗窃' not in t.markdown(view)
    assert '[来源1](#source-run-1)' in t.markdown(view)


def test_openapi_matches_table_projection():
    import jsonschema
    from control.openapi import schemas
    from control.openapi_v9 import extend_schemas
    result,snap=fixture()
    jsonschema.validate(t.build(result,snap), extend_schemas(schemas())['PersonTableAnswer'])


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_json_selection_prefix_drops_trailing_free_text():
    result,snap=fixture()
    choose(snap,source_refs=['snapshot:1'],suggestions=[{'action':'inspect_sources','reason_source':'snapshot:1'}])
    snap['model_final_text']+='\n### 模型补充\n此人实施盗窃，错误数字999。'
    view=t.build(result,snap)
    assert view['selection_status']=='accepted' and len(view['suggestions'])==1
    assert '实施盗窃' not in t.markdown(view) and '999' not in t.markdown(view)


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_platform_suggestions_outrank_model_and_dedupe():
    """Platform flow steps come first even when model fills 3 generic queries."""
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {}, 'task_id': 'task', 'scoring_requested': True,
        'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    snap['native_tool_policy'] = {
        'allowed_tools': [
            'peixian_query_captures', 'peixian_query_night',
            'peixian_query_community', 'peixian_query_warning_detail', 'peixian_query_profile',
        ]
    }
    snap['native_calls'] = {'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}}}
    captures = [
        {'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'a',
         'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 12, 'tags': '盗窃'}, 'result_digest': 'd'},
        {'record_id': 'run:call:b', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'b',
         'fields': {'target_id_card': 'person-b', 'target_name': '乙', 'capture_count': 1, 'tags': ''}, 'result_digest': 'd'},
    ]
    result['records'] = captures
    result['claims'] = []
    choose(snap, source_refs=['run:call:a'], suggestions=[
        {'action': 'query', 'kind': 'night'},
        {'action': 'query', 'kind': 'community'},
        {'action': 'query', 'kind': 'profile'},
    ])
    view = t.build(result, snap)
    assert view['suggestions'][0]['action'] == 'authorize_candidates'
    assert view['suggestions'][0]['origin'] == 'platform_direction'
    from control.theft_candidates import candidate_request_n, recommend_n
    n = recommend_n(view['ranking'])
    assert candidate_request_n(view['suggestions'][0]['reply']) == n
    assert view['suggestions'][0].get('recommended') == n
    labels = [o['label'] for o in view['next_question']['options']]
    assert any('推荐' in lab for lab in labels)
    assert len(view['next_question']['options']) == min(5, len(view['ranking']['items']))
    assert all(o['action'] == 'authorize_candidates' for o in view['next_question']['options'])
    output = t.markdown(view)
    assert '### 下一步分析建议' not in output
    assert '| 建议 |' not in output
    nq = view['next_question']
    assert all(o['send'] is True for o in nq['options'])
    assert any('推荐' in o['label'] for o in nq['options'])


def test_platform_skips_closed_tools_and_per_person_enrich():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {'start': '2026-09-10 20:00:00', 'end': '2026-09-10 23:00:00', 'radius_m': 500},
        'task_id': 'task', 'scoring_requested': True, 'direction': 'case_to_person',
        'candidate_set': [
            {'rank': 1, 'person_ref': 'person-a', 'name': '甲', 'run_id': 'run', 'record_id': 'run:call:a',
             'snapshot_id': 'a', 'result_digest': 'd'},
            {'rank': 2, 'person_ref': 'person-b', 'name': '乙', 'run_id': 'run', 'record_id': 'run:call:b',
             'snapshot_id': 'b', 'result_digest': 'd'},
        ],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    # tracks not allowed — must not suggest tracks; night allowed
    snap['native_tool_policy'] = {
        'allowed_tools': ['peixian_query_captures', 'peixian_query_night', 'peixian_query_warning_detail']
    }
    snap['native_calls'] = {
        'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}},
        'n1': {'status': 'completed', 'frozen': {'kind': 'night', 'query': {'person_ref': 'person-a'}}},
    }
    records = [
        {'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'a',
         'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 12, 'tags': '盗窃'}, 'result_digest': 'd'},
        {'record_id': 'run:call:b', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'b',
         'fields': {'target_id_card': 'person-b', 'target_name': '乙', 'capture_count': 1, 'tags': ''}, 'result_digest': 'd'},
        {'record_id': 'run:call:n', 'source_run_id': 'run', 'call_id': 'n1', 'module': 'night', 'snapshot_id': 'n',
         'fields': {'targetIdCard': 'person-a', 'captureTime': '2026-09-10 01:00:00'}, 'result_digest': 'd'},
    ]
    result['records'] = records
    result['claims'] = []
    choose(snap, source_refs=['run:call:a'])
    view = t.build(result, snap)
    # Batch enrichment: while plan still pending, do not ask officer per person
    assert all(x.get('action') != 'query' or '乙' not in x.get('text', '') for x in view['suggestions'])
    assert all('轨迹' not in x.get('text', '') for x in view['suggestions'])


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_no_duplicate_clarify_when_model_already_asked():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {}, 'task_id': 'task', 'scoring_requested': False,
        'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['native_calls'] = {}
    choose(snap, suggestions=[{'action': 'clarify_scope', 'fields': ['start', 'end', 'radius_m']}])
    view = t.build({**result, 'records': [], 'claims': []}, snap)
    clarify = [x for x in view['suggestions'] if x.get('action') == 'clarify_scope']
    assert len(clarify) == 1
    assert clarify[0]['origin'] == 'model_selection'


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_semantic_dedup_keeps_platform_over_model():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {'person_identity': 'x', 'start': 'a', 'end': 'b'},
        'task_id': 'task', 'direction': 'person_to_case', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = 'person-one'
    snap['native_tool_policy'] = {'allowed_tools': ['peixian_query_tracks', 'peixian_query_incidents']}
    snap['native_calls'] = {'tr': {'status': 'completed', 'frozen': {'kind': 'tracks', 'query': {'person_ref': 'person-one'}}}}
    result['records'] = [
        {'record_id': 'run:call:t', 'source_run_id': 'run', 'call_id': 'tr', 'module': 'tracks', 'snapshot_id': 't',
         'fields': {'lon': 118.0, 'lat': 34.0, 'captureTime': '2026-09-10 12:00:00'}, 'result_digest': 'd'},
    ]
    result['claims'] = []
    choose(snap, suggestions=[{'action': 'query', 'kind': 'incidents'}])
    view = t.build(result, snap)
    incidents = [x for x in view['suggestions'] if x.get('kind') == 'incidents']
    assert len(incidents) == 1
    assert incidents[0]['origin'] == 'platform_direction'
    from control.theft_candidates import reply_query_incidents
    assert incidents[0]['reply'] == reply_query_incidents()


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_model_query_reply_is_natural_phrase_not_label():
    result, snap = fixture()
    choose(snap, suggestions=[{'action': 'query', 'kind': 'night'}, {'action': 'inspect_sources'}])
    view = t.build(result, snap)
    replies = [x['reply'] for x in view['suggestions']]
    assert '查询此人夜间活动记录' in replies
    assert '说明已取得的来源记录' in replies
    assert all(x['reply'] != x['text'] for x in view['suggestions'])
    output = t.markdown(view)
    assert '### 下一步分析建议' not in output
    nq = view['next_question']
    assert [o['label'] for o in nq['options']] == [s['reply'] for s in view['suggestions']]
    assert all(o['send'] is True for o in nq['options'])


def test_clarify_reply_is_example():
    from control.theft_candidates import reply_clarify
    assert reply_clarify(['start', 'end', 'radius_m']) == '时间 2026-09-10 20:00 至 2026-09-10 23:00，半径 500 米'

@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_next_question_clarify_send_false():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {}, 'task_id': 'task', 'scoring_requested': False,
        'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['native_calls'] = {}
    choose(snap, suggestions=[{'action': 'clarify_scope', 'fields': ['start', 'end', 'radius_m']}])
    view = t.build({**result, 'records': [], 'claims': []}, snap)
    nq = view['next_question']
    assert nq is not None
    assert nq['custom'] is True
    assert len(nq['options']) <= 3
    clarify = [o for o in nq['options'] if o['action'] == 'clarify_scope']
    assert clarify and all(o['send'] is False for o in clarify)
    assert [o['label'] for o in nq['options']] == [s['reply'] for s in view['suggestions']]
    assert '### 下一步分析建议' not in t.markdown(view)


def test_stage1_requires_two_persons():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {}, 'task_id': 'task', 'scoring_requested': True,
        'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    snap['native_calls'] = {'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}}}
    result['records'] = [
        {'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'a',
         'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 12, 'tags': '盗窃'}, 'result_digest': 'd'},
    ]
    result['claims'] = []
    choose(snap, source_refs=['run:call:a'])
    view = t.build(result, snap)
    assert view.get('ranking') is None


@pytest.mark.skip(reason="platform suggestions removed in v31g")
def test_entry_suggests_captures_after_incidents():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {'start': '2026-09-10 20:00:00', 'end': '2026-09-10 23:00:00', 'radius_m': 500, 'lon': 1, 'lat': 2},
        'task_id': 'task', 'scoring_requested': True, 'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    snap['native_tool_policy'] = {'allowed_tools': ['peixian_query_captures', 'peixian_query_incidents']}
    snap['native_calls'] = {'inc': {'status': 'completed', 'frozen': {'kind': 'incidents', 'query': {}}}}
    result['records'] = [
        {'record_id': 'run:call:i', 'source_run_id': 'run', 'call_id': 'inc', 'module': 'incidents', 'snapshot_id': 'i',
         'fields': {'gisX': 1, 'gisY': 2, 'cjbh': 'A1'}, 'result_digest': 'd'},
    ]
    result['claims'] = []
    choose(snap)
    view = t.build(result, snap)
    assert view['suggestions'][0]['action'] == 'query'
    assert view['suggestions'][0]['kind'] == 'captures'
    assert '初排' in view['suggestions'][0]['text']


def test_no_per_person_while_enrichment_pending():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {'start': '2026-09-10 20:00:00', 'end': '2026-09-10 23:00:00', 'radius_m': 500},
        'task_id': 'task', 'scoring_requested': True, 'direction': 'case_to_person',
        'candidate_set': [
            {'rank': 1, 'person_ref': 'person-a', 'name': '甲', 'run_id': 'run', 'record_id': 'run:call:a',
             'snapshot_id': 'a', 'result_digest': 'd'},
        ],
        'enrichment_plan': {'pending': 4, 'complete': False},
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    snap['native_tool_policy'] = {
        'allowed_tools': ['peixian_query_night', 'peixian_query_community', 'peixian_query_warning_detail', 'peixian_query_profile']
    }
    snap['native_calls'] = {'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}}}
    result['records'] = [
        {'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'a',
         'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 12, 'tags': '盗窃'}, 'result_digest': 'd'},
    ]
    result['claims'] = []
    choose(snap)
    view = t.build(result, snap)
    assert not any(x.get('action') == 'query' for x in view['suggestions'])


def test_forbidden_wording_absent_in_ranking_markdown():
    result, snap = fixture()
    snap['native_tool_context'] = {
        'confirmed': {}, 'task_id': 'task', 'scoring_requested': True,
        'direction': 'case_to_person', 'candidate_set': [],
    }
    snap['table_answer_policy']['person_ref'] = None
    snap['table_answer_policy']['direction'] = 'case_to_person'
    snap['native_calls'] = {'cap': {'status': 'completed', 'frozen': {'kind': 'captures', 'query': {}}}}
    result['records'] = [
        {'record_id': 'run:call:a', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'a',
         'fields': {'target_id_card': 'person-a', 'target_name': '甲', 'capture_count': 12, 'tags': '盗窃'}, 'result_digest': 'd'},
        {'record_id': 'run:call:b', 'source_run_id': 'run', 'call_id': 'cap', 'module': 'captures', 'snapshot_id': 'b',
         'fields': {'target_id_card': 'person-b', 'target_name': '乙', 'capture_count': 3, 'tags': ''}, 'result_digest': 'd'},
    ]
    result['claims'] = []
    choose(snap, source_refs=['run:call:a'])
    view = t.build(result, snap)
    output = t.markdown(view)
    for banned in ('合成', 'Mock', 'mock', '测试范围', '验收范围', '仅供参考', '辅助参考', '需人工核验', '辅助研判', '当前展示', '资料缺口'):
        assert banned not in output, banned
    assert '主要依据' in output
    assert '建议核验' in output


def test_next_question_skips_non_query_suggestions():
    for action in ('inspect_sources', 'inspect_cases'):
        assert t.next_question('r', [{'reply': '查看来源', 'reason': 'x', 'action': action}]) is None


def test_next_question_keeps_query_and_clarify_only():
    q = t.next_question('r', [
        {'reply': '查看本次来源明细', 'reason': 'x', 'action': 'inspect_sources'},
        {'reply': '补查夜间活动', 'reason': 'x', 'action': 'query', 'kind': 'night'},
        {'reply': '确认抓拍时段与半径', 'reason': 'x', 'action': 'clarify_scope'},
    ])
    assert [o['action'] for o in q['options']] == ['query', 'clarify_scope']
    assert [o['send'] for o in q['options']] == [True, False]
    assert [o['id'] for o in q['options']] == ['option-1', 'option-2']


def test_next_question_caps_card_options():
    q = t.next_question('r', [{'reply': f'补查{i}', 'reason': 'x', 'action': 'query'} for i in range(4)])
    assert [o['label'] for o in q['options']] == ['补查0', '补查1']


def test_model_next_question_filters_actions():
    chosen = {'next_question': {'options': [
        {'label': '查看来源', 'action': 'inspect_sources'},
        {'label': '无动作'},
        {'label': '确认半径', 'action': 'clarify_scope', 'send': True},
    ]}}
    q = t.next_question('r', [], chosen=chosen)
    assert [(o['label'], o['send']) for o in q['options']] == [('确认半径', False)]
    only_sources = {'next_question': {'options': [{'label': '查看来源', 'action': 'inspect_sources'}]}}
    assert t.next_question('r', [], chosen=only_sources) is None


def test_prompts_default_to_no_suggestions():
    assert '"suggestions":[]' in t.INSTRUCTION
    assert 'inspect_sources' not in t.INSTRUCTION


def community_fixture():
    result, snap = fixture()
    result['records'].append({'record_id': 'run:call:snap-c:1', 'source_run_id': 'run', 'call_id': 'call',
        'module': 'community', 'snapshot_id': 'snap-c',
        'fields': {'timeRangeStart': '2026-09-03 07:10:00', 'timeRangeEnd': '2026-09-03 18:40:00',
                   'crossHours': 11.5, 'communityCount': 4, 'communityList': '甲苑、乙苑、丙苑、丁苑'}})
    return result, snap


def test_query_with_missing_fields_becomes_clarify_on_card():
    q = t.next_question('r', [{'reply': '核对案发地周边抓拍：位置＿＿', 'reason': 'x', 'action': 'query',
                               'kind': 'captures', 'fields': ['lon', 'lat']}])
    assert [(o['action'], o['send']) for o in q['options']] == [('clarify_scope', False)]


def test_activity_summary_bound_to_same_kind_is_rendered():
    result, snap = community_fixture()
    choose(snap, activity_summaries=[
        {'kind': 'community', 'text': '9月3日07:10至18:40跨甲苑、乙苑、丙苑、丁苑共4个小区流动。研判：疑似踩点。',
         'source_refs': ['run:call:snap-c:1']},
        {'kind': 'night', 'text': '引用错误类型', 'source_refs': ['run:call:snap-c:1']},
        {'kind': 'tracks', 'text': '引用不存在的记录', 'source_refs': ['missing']},
    ])
    view = t.build(result, snap)
    assert [x['kind'] for x in view['activity_summaries']] == ['community']
    output = t.markdown(view)
    assert '**活动概括与研判**' in output and '研判：疑似踩点' in output
    assert output.index('活动概括与研判') < output.index('判断依据')


def test_no_activity_summary_without_matching_records():
    result, snap = fixture()
    choose(snap, activity_summaries=[{'kind': 'community', 'text': '跨小区', 'source_refs': ['run:call:snapshot:1']}])
    view = t.build(result, snap)
    assert view['activity_summaries'] == []
    assert '活动概括' not in t.markdown(view)


def test_judgement_limits_removed_from_prompts():
    from control.agents.runtime import POLICY
    from control import native_tool_scope as scope
    rules = scope.model_context({'scope_version': 1, 'confirmed': {}, 'source_refs': []})
    for text in (t.INSTRUCTION, POLICY, rules):
        for phrase in ('犯罪倾向', '罪责结论，评分', '作案人认定', '犯罪结论'):
            assert phrase not in text, phrase
    assert 'activity_summaries' in t.INSTRUCTION
