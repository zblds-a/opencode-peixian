"""Scoring gate v3.5.0: scoring/ranking allowed only in the two workflow directions."""
import json
from control import table_answer as t
from control import native_tool_scope as nts


def fixture():
    snap = {'native_tool_context':{'confirmed':{'person_identity':'person-one'},'task_id':'task'},
        'table_answer_policy':{'version':t.VERSION,'person_ref':'person-one','history':[]},
        'native_tool_policy':{'allowed_tools':['peixian_query_profile']},
        'native_calls':{'call':{'status':'completed','frozen':{'query':{'person_ref':'person-one'}}}}}
    record={'record_id':'run:call:snapshot:1','source_run_id':'run','call_id':'call','module':'profile','snapshot_id':'snapshot',
        'fields':{'person':{'sfz':'person-one','name':'测试人员','age':30,'gender':'男'},'captures':[]}}
    claim={'claim_id':'claim','source_run_id':'run','verification_status':'approved','type':'fact',
        'source_ids':[record['record_id']],'statement':'来源档案与最近抓拍。'}
    result={'run_id':'run','generated_at':'2026-09-27T10:00:00+08:00','records':[record],'claims':[claim],'missing':[]}
    return result,snap


def choose(snap, **values):
    snap['model_final_text']=json.dumps({'format':t.VERSION,'mode':'data',**values},ensure_ascii=False)


def _scoring_records(result):
    night={'record_id':'run:call:n1','source_run_id':'run','call_id':'call','module':'night','snapshot_id':'n',
           'fields':{'id':'1','targetIdCard':'person-one','captureTime':'2026-09-10 01:00:00'}}
    warning={'record_id':'run:call:w1','source_run_id':'run','call_id':'call','module':'warning_detail','snapshot_id':'w',
             'fields':{'id':'1','idCard':'person-one','warningCount':3,'personName':'测'}}
    result['records']+=[night,warning]


def test_p2c_scoring_open_in_workflow_direction():
    result,snap=fixture();_scoring_records(result)
    snap['native_tool_context']['direction']='person_to_case'
    choose(snap,source_refs=['run:call:snapshot:1'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view['scoring']['status']=='ready'
    assert '### 可疑度评分' in t.markdown(view)


def test_scoring_closed_when_direction_unknown():
    result,snap=fixture();_scoring_records(result)
    snap['native_tool_context']['direction']='unknown'
    choose(snap,source_refs=['run:call:snapshot:1'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view.get('scoring') is None


def test_scoring_closed_under_legacy_adaptive_policy():
    result,snap=fixture();_scoring_records(result)
    snap['native_tool_context']['direction']='person_to_case'
    snap['dialogue_policy']='adaptive-dialogue-v1'
    choose(snap,source_refs=['run:call:snapshot:1'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view.get('scoring') is None


def test_scoring_closed_without_request():
    result,snap=fixture();_scoring_records(result)
    snap['native_tool_context']['direction']='person_to_case'
    choose(snap,source_refs=['run:call:snapshot:1'])
    view=t.build(result,snap)
    assert view.get('scoring') is None


def test_c2p_ranking_open_in_workflow_direction():
    result,snap=fixture()
    snap['native_tool_context']={'confirmed':{},'task_id':'task','direction':'case_to_person','scoring_requested':True,'candidate_set':[]}
    snap['table_answer_policy']['person_ref']=None
    snap['table_answer_policy']['direction']='case_to_person'
    snap['native_calls']={'cap':{'status':'completed','frozen':{'kind':'captures','query':{}}}}
    result['records']=[
        {'record_id':'run:call:a','source_run_id':'run','call_id':'cap','module':'captures','snapshot_id':'a',
         'fields':{'target_id_card':'person-a','target_name':'甲','capture_count':12,'tags':'盗窃'},'result_digest':'d'},
        {'record_id':'run:call:b','source_run_id':'run','call_id':'cap','module':'captures','snapshot_id':'b',
         'fields':{'target_id_card':'person-b','target_name':'乙','capture_count':1,'tags':''},'result_digest':'d'},
    ]
    result['claims']=[]
    choose(snap,source_refs=['run:call:a'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view['ranking']['items'][0]['person_ref']=='person-a'
    assert '初步关注排序' in t.markdown(view)


def test_c2p_ranking_closed_when_direction_not_workflow():
    result,snap=fixture()
    snap['native_tool_context']={'confirmed':{},'task_id':'task','direction':'unknown','scoring_requested':True,'candidate_set':[]}
    snap['table_answer_policy']['person_ref']=None
    snap['table_answer_policy']['direction']='unknown'
    snap['native_calls']={'cap':{'status':'completed','frozen':{'kind':'captures','query':{}}}}
    result['records']=[
        {'record_id':'run:call:a','source_run_id':'run','call_id':'cap','module':'captures','snapshot_id':'a',
         'fields':{'target_id_card':'person-a','target_name':'甲','capture_count':12,'tags':'盗窃'},'result_digest':'d'},
    ]
    result['claims']=[]
    choose(snap,source_refs=['run:call:a'],scoring={'requested':True})
    view=t.build(result,snap)
    assert view.get('ranking') is None


def test_instruction_documents_scoring_field():
    assert '"scoring":{"requested":true}' in t.INSTRUCTION
    assert '嫌疑评分或排名' not in t.INSTRUCTION
    assert '由人到案或由案到人工作流' in t.INSTRUCTION


def test_freeze_context_scoring_fallback():
    # scoring_requested() keyword fallback is wired into freeze_context (v3.5.0 fix).
    assert nts.scoring_requested('帮我评估这个人涉案可能性并评分') is True
    assert nts.scoring_requested('不要评分，只要资料') is False
    # direction default: p2c/c2p imply scoring on unless negated
    assert nts.scoring_requested('查这个人', None, 'person_to_case') is True
    assert nts.scoring_requested('不要评分', None, 'person_to_case') is False
