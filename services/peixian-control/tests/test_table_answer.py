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
    assert all('### '+x in output for x in ['人员基本信息','基本结论','判断依据','下一步分析建议'])
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


def test_model_proposes_only_available_next_steps():
    result,snap=fixture()
    choose(snap,source_refs=['invented'],suggestions=[{'action':'query','kind':'night'},{'action':'query','kind':'tracks'},{'action':'query','kind':'profile'}])
    view=t.build(result,snap)
    assert len(view['suggestions'])==1 and view['suggestions'][0]['kind']=='night'
    assert all('invented' not in x['source_ids'] for x in view['conclusions'])


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
    assert '0条' in view['conclusions'][0]['text'] and view['missing']


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


def test_json_selection_prefix_drops_trailing_free_text():
    result,snap=fixture()
    choose(snap,source_refs=['snapshot:1'],suggestions=[{'action':'inspect_sources','reason_source':'snapshot:1'}])
    snap['model_final_text']+='\n### 模型补充\n此人实施盗窃，错误数字999。'
    view=t.build(result,snap)
    assert view['selection_status']=='accepted' and len(view['suggestions'])==1
    assert '实施盗窃' not in t.markdown(view) and '999' not in t.markdown(view)
