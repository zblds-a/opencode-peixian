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
    assert payload['tools']['skill'] is True and payload['tools']['bash'] is False
    assert snap['skills'][0]['version']=='2' and len(snap['skills'][0]['content_sha256'])==64
    items[0]['available']=False
    assert eligible(applied,items)==([],'skill_configuration_pending')
    assert eligible({'skills':[]},items)==([],'no_applied_skills')


def test_source_detail_never_rebuilds_history():
    with pytest.raises(HTTPException) as exc:source_detail({'run_id':'r','records':[]},'source-x')
    assert exc.value.status_code==404
