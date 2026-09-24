import pytest
from fastapi import HTTPException
from control.question_contract import project,validate
from control.skill_discovery import eligible,bind
from control.reply_presentation import source_detail


def test_question_cardinality_and_identity():
    item={'id':'q1','questions':[{'header':'来源','question':'选来源','options':[{'label':'甲'},{'label':'乙'}],'custom':False}]}
    a=project(item)
    assert a==project(item) and a['questions'][0]['selection_max']==1
    for answers,code in [([['甲','乙']],'too_many_answers'),([[]],'clarification_incomplete'),([['丙']],'invalid_answer')]:
        with pytest.raises(HTTPException) as exc:validate(item,{'answers':answers})
        assert exc.value.detail['code']==code
    item['questions'][0]['multiple']=True
    assert validate(item,{'answers':[['甲','乙']]})==[['甲','乙']]
    with pytest.raises(HTTPException) as exc:validate(item,{'answers':[['甲','甲']]})
    assert exc.value.detail['code']=='duplicate_answers'
    with pytest.raises(HTTPException) as exc:validate(item,{'answers':[['甲']],'question_version':a['question_version']})
    assert exc.value.detail['code']=='question_changed'


def test_skill_discovery_requires_applied_authority():
    applied={'skills':[{'id':'s','name':'方法','content':'正文'}]}
    items=[{'id':'s','kind':'personal_skill','available':True,'version':'2'}]
    snap={};payload={'system':'中文','tools':{'*':False,'bash':False}}
    bind(snap,payload,applied,items)
    assert payload['tools']['peixian_load_personal_skill'] is True and payload['tools']['skill'] is False and payload['tools']['bash'] is False
    assert snap['skills'][0]['version']=='2' and len(snap['skills'][0]['content_sha256'])==64
    items[0]['available']=False
    assert eligible(applied,items)==([],'skill_configuration_pending')
    assert eligible({'skills':[]},items)==([],'no_applied_skills')


def test_source_detail_never_rebuilds_history():
    with pytest.raises(HTTPException) as exc:source_detail({'run_id':'r','records':[]},'source-x')
    assert exc.value.status_code==404


from test_provider_flow import provider,accept,pid,tool
from test_trusted_results import enabled,v6
from test_task_spec import task_env
from test_multi_agent import multi
from test_native_tool_execution import native_candidate


def test_skill_load_frozen_revocation_and_replay(provider,monkeypatch):
    from control import skill_discovery,capabilities
    from control.store import encode
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    method={'id':'skill-example','name':'方法','content':'只整理已取得来源','version':1}
    item={'id':method['id'],'kind':'personal_skill','available':True,'version':'1'}
    monkeypatch.setattr(capabilities,'catalog',lambda s,u:[item] if u==uid else [])
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    skill_discovery.bind(snap,{'system':'中文','tools':{}},{'skills':[method]},[item])
    with store.tx() as db:
        db.execute('INSERT INTO skills(id,uid,name,description,content,enabled,version,history) VALUES(?,?,?,?,?,1,1,?)',(method['id'],uid,method['name'],'方法',method['content'],'[]'))
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snap),row['id']))
    args=(store,uid,'ses_multi',row['message_id'],'skill-call',{'skill_id':method['id']},1)
    assert skill_discovery.load(*args)['content']==method['content']
    assert skill_discovery.load(*args)['version']=='1'
    assert store.one("SELECT count(*) AS n FROM run_events WHERE run_id=? AND event_key=?",(row['id'],'skill-load:skill-call'))['n']==1
    with store.tx() as db:db.execute('UPDATE skills SET enabled=0 WHERE id=?',(method['id'],))
    with pytest.raises(HTTPException) as exc:skill_discovery.load(*args)
    assert exc.value.detail['code']=='skill_unavailable'
