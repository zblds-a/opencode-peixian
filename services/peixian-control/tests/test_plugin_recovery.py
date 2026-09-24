import copy
import pytest
from shared.tool_failure import public
from control import native_tool_scope as scope
from fastapi import HTTPException

@pytest.mark.parametrize('code', ['source_selection_required','source_value_override','scope_missing','provider_not_applied','coordinate_contract_unconfirmed'])
def test_safe_failure(code):
    value=public({'code':code,'message':'private body','field_errors':{'start':'private body','unexpected':'secret'}},call_id='call-1')
    assert value['code']==code and value['dispatch_status']=='not_dispatched'
    assert 'private' not in str(value) and 'secret' not in str(value)
    assert set(value['field_errors'])=={'start'}

@pytest.mark.parametrize('code',['tool_call_unconfirmed','tool_call_busy','native_duplicate_call','unrecognized'])
def test_unknown_does_not_claim_not_sent(code):
    assert public({'code':code})['dispatch_status']=='unknown'

def test_source_required_is_not_success():
    context={'confirmed':{},'user_conditions':{},'source_refs':[]}
    with pytest.raises(HTTPException) as exc:
        scope.arguments('captures',{'start':'2026-09-20 00:00:00','end':'2026-09-21 00:00:00','radius_m':500},context)
    assert exc.value.detail['code']=='source_selection_required'

def test_same_coordinate_preserves_source(monkeypatch):
    ref={'run_id':'r','record_id':'s','snapshot_id':'snap','result_digest':'digest'}
    prior={'task_id':'t','scope_version':1,'confirmed':{'lon':'116.1','lat':'34.1'},'source_refs':[ref],'scoring_requested':False}
    class Store:
        def rows(self,*a):return [{'request_ciphertext':'x'}]
        def decrypt(self,*a):return {'native_tool_context':copy.deepcopy(prior)}
    monkeypatch.setattr(scope,'slots',lambda *a:{'a':{'field':'lon','value':'116.100'},'b':{'field':'lat','value':34.1}})
    monkeypatch.setattr(scope,'named_sources',lambda *a:[])
    from control import analysis_tasks
    monkeypatch.setattr(analysis_tasks,'source',lambda *a:None)
    result=scope.freeze_context(Store(),'u','s',{'text':'沿用相同地点，不要评分'})
    assert result['source_refs']==[ref]
    prior['confirmed']['lon']='115'
    assert scope.freeze_context(Store(),'u','s',{'text':'更换地点，不要评分'})['source_refs']==[]

from test_provider_flow import provider
from test_multi_agent import multi
from test_task_spec import task_env
from test_trusted_results import enabled, v6
from test_native_tool_execution import native_candidate, ARGS, tool

def test_rejected_call_is_audited_without_dispatch(provider, monkeypatch):
    from control import native_tool_gate as gate
    store=provider[0];uid=provider[4]['uid'];run=native_candidate(provider,monkeypatch)
    def missing(*args):raise HTTPException(409,{'code':'scope_missing','field_errors':{'start':'secret'}})
    monkeypatch.setattr(gate,'arguments',missing)
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:gate.prepare(store,uid,'ses_multi',run['message_id'],'reject-one',tool('tracks'),ARGS,1)
        assert exc.value.detail['dispatch_status']=='not_dispatched'
    events=store.rows('SELECT * FROM run_events WHERE run_id=? AND event_key=?',(run['id'],'native-rejection:reject-one'))
    assert len(events)==1 and events[0]['error_code']=='scope_missing'
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(run['id'],))['request_ciphertext'])
    assert not snap.get('native_calls') and not snap.get('native_pending_questions')
