import copy
import hashlib
import json
from pathlib import Path
import pytest
from test_provider_flow import provider
from test_multi_agent import multi
from test_task_spec import task_env
from test_trusted_results import enabled, v6
from test_native_tool_execution import ARGS
from test_adaptive_dialogue import setup_run, messages
from test_table_answer import fixture, choose
from control import native_tool_scope as scope, table_answer as tables


def test_one_prompt_and_version():
    from control.agents.registry import require, ROOT
    from control.agents.runtime import bind, freeze
    profile=require('theft-assistant');payload={};snapshot={}
    bind(payload,profile,None,[]);freeze(snapshot,payload,profile)
    assert profile.data['version']=='3.6.1'
    assert snapshot['agent_profile']['prompt_resource']=='theft_prompt.md'
    assert snapshot['agent_profile']['prompt_sha256']==hashlib.sha256(profile.prompt.encode()).hexdigest()
    assert snapshot['effective_system_prompt_sha256']==hashlib.sha256(payload['system'].encode()).hexdigest()
    assert payload['system'].count(profile.prompt)==1
    assert not (ROOT/'theft_dialogue_prompt.md').exists()
    assert 'person_case_plan' not in profile.prompt and '打满八' not in profile.prompt


def test_new_context_never_inherits_full_plan(provider,monkeypatch):
    from control import native_tool_gate
    s,u,row,snap=setup_run(provider,monkeypatch)
    c=snap['native_tool_context'];c.update(scoring_requested=True,person_case_plan={'items':[{'kind':'tracks'}]},center_set=[{'record_id':'old'}],candidate_set=[{'person_ref':'old'}])
    c['capture_conditions']={'start':ARGS['start'],'end':ARGS['end'],'radius_m':600}
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),row['id']))
    context=scope.freeze_context(s,u,row['session_id'],{'text':'继续核对同一人员'})
    assert context['task_id']==c['task_id']
    assert context['confirmed']['person_identity']==c['confirmed']['person_identity']
    assert context['capture_conditions']==c['capture_conditions']
    assert context['source_selection']=='explicit'
    assert context['scoring_requested'] is True
    assert context['person_case_plan'] is None and context['enrichment_plan'] is None
    assert context['center_set']==[] and context['candidate_set']==[]
    assert 'dialogue_policy' not in context
    assert 'radius_m' not in context['confirmed']
    assert 'person_case_plan' not in scope.model_context(context)
    assert not s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])['native_tool_context']['scoring_requested'] is False


def test_four_sections_and_model_suggestions():
    result,snapshot=fixture()
    snapshot['native_tool_context']['query_rules_version']='on-demand-v1'
    snapshot['table_answer_policy']['layout_version']='theft-four-sections-v1'
    choose(snapshot,source_refs=[result['records'][0]['record_id']],scoring={'requested':True},suggestions=[
        {'action':'query','kind':'night','text':'核对夜间记录','reason':'补充观察时间','conditions':'提供时间范围'},
        {'action':'query','kind':'tracks','text':'未授权建议'},
        {'action':'authorize_candidates','text':'补查全部候选'}])
    view=tables.build(result,snapshot);text=tables.markdown(view)
    assert len(view['suggestions'])==1 and view['suggestions'][0]['text']=='核对夜间记录'
    assert view['scoring'] is None and view['ranking'] is None and view['coverage'] is None
    assert view['selection_status']=='accepted'
    for title in ('人员基本信息','研判摘要','分析依据','下一步研判'):assert '### '+title in text
    assert '核对夜间记录' in text
    import jsonschema
    from control.openapi import schemas
    from control.openapi_v9 import extend_schemas
    jsonschema.validate(view,extend_schemas(schemas())['PersonTableAnswer'])


def test_old_layout_not_changed():
    result,snapshot=fixture();before=copy.deepcopy(snapshot)
    view=tables.build(result,snapshot)
    assert 'layout_version' not in view
    text=tables.markdown(view)
    assert '### 基本结论' in text and '### 判断依据' in text
    assert '### 研判摘要' not in text and '### 下一步研判' not in text
    assert snapshot==before


def test_historical_adaptive_cancellation_compatible(provider,monkeypatch):
    from control.conversation_completion import finish_dismissed
    s,u,row,snap=setup_run(provider,monkeypatch)
    snap.pop('clarification_completion_version');snap['dialogue_policy']='adaptive-dialogue-v1'
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),row['id']))
    assert finish_dismissed(s,row,messages(row))


def test_capture_time_requires_its_own_scope():
    from fastapi import HTTPException
    c={'confirmed':{'start':ARGS['start'],'end':ARGS['end'],'radius_m':500},'source_refs':[],
       'capture_scope_version':'capture-purpose-v1','capture_conditions':{}}
    assert scope.resolve_arguments('captures',{},c)=={}
    with pytest.raises(HTTPException) as exc:scope.arguments('captures',{},c)
    assert set(exc.value.detail['field_errors'])=={'start','end','radius_m'}


def test_registry_public_matches_schema():
    import jsonschema
    from control.agents.registry import require
    from control.openapi import schemas
    from control.openapi_v6 import extend_schemas
    jsonschema.validate(require('theft-assistant').public(),extend_schemas(schemas())['AgentPublic'])


def test_real_admission_freezes_unique_prompt_and_replay(provider,monkeypatch):
    import uuid
    from control import business_runs as runs, native_tool_gate
    from control.agents.registry import require
    s,u,old,snap=setup_run(provider,monkeypatch)
    app=provider[1];provider[2].portal.call(app.state.run_coordinator.close)
    monkeypatch.setenv('PX_MULTI_AGENT_V1_UIDS',u)
    monkeypatch.setenv('PX_THEFT_NATIVE_UIDS',u)
    monkeypatch.setattr(native_tool_gate,'enabled',lambda store,uid:uid==u)
    runs.set_state(s,old['id'],'completed','completed')
    data={**provider[5],'agent_id':'theft-assistant','text':'你好','skill_ids':[],'plugin_ids':[],'client_request_id':str(uuid.uuid4())}
    accepted=runs.submit(s,provider[4],old['session_id'],data,copy.deepcopy(provider[6]),provider[-1],1)
    row=s.one('SELECT * FROM business_runs WHERE id=?',(accepted['run_id'],));snapshot=s.decrypt(row['request_ciphertext'])
    assert snapshot['query_rules_version']=='on-demand-v1' and 'dialogue_policy' not in snapshot
    assert snapshot['clarification_completion_version']=='clarification-completion-v1'
    assert snapshot['agent_profile']['version']=='3.6.1'
    assert require('theft-assistant').prompt in snapshot['payload']['system']
    assert snapshot['native_calls']=={}
    assert snapshot['table_answer_policy']['layout_version']=='theft-four-sections-v1'
    assert runs.submit(s,provider[4],old['session_id'],data,copy.deepcopy(provider[6]),provider[-1],1)==accepted
    assert s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext']==row['request_ciphertext']
