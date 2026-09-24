import copy
import pytest
from html.parser import HTMLParser
from test_trusted_results import v6, enabled, finish
from test_multi_agent import multi
from test_task_spec import task_env
from test_control import context, P, create_user, login_user
from control.trusted_report import render, sections


def report_result():
    return {'schema':'peixian.analysis-result','version':'2.0','run_id':'run-demo',
      'agent':{'id':'theft-assistant','version':'1.0'},'task':{'query_mode':'new_query','target_refs':['DEMO-PERSON-A']},
      'data_environment':'synthetic','data_usage':{'status':'unknown'},'generated_at':'2026-09-22T00:00:00+00:00',
      'claims':[{'claim_id':'demo-claim','type':'fact','statement':'DEMO 记录','source_ids':['DEMO-001'],'verification_status':'approved'}],
      'records':[{'record_id':'DEMO-001','occurred_at':'2026-09-22T00:00:00+08:00'}],
      'missing':['车辆资料尚未取得，不代表零条。'],
      'versions':{'records_snapshot_id':'DEMO-SNAPSHOT'},
      'narrative':{'status':'conflicted','text':'未经核验的说明','conflicts':[{'message':'说明与资料不一致'}]}}


@pytest.mark.parametrize('format',['md','html'])
def test_report_same_claims_unknown_missing_narrative(format):
    value=report_result();original=copy.deepcopy(value);text=render(value,[],format)
    for required in ('demo-claim','DEMO-001','DEMO-SNAPSHOT','车辆资料尚未取得','结果未确认','存在冲突','已取得的来源资料'):
        assert required in text
    assert value==original and text==render(value,[],format)


def test_html_does_not_execute_source_or_narrative():
    value=report_result();value['narrative']['text']='<script>alert(1)</script><img src=https://evil.invalid/>'
    value['claims'][0]['statement']='</li><iframe src=//evil.invalid>'
    text=render(value,[])
    class Tags(HTMLParser):
        def __init__(self):super().__init__();self.tags=[]
        def handle_starttag(self,tag,attrs):self.tags.append(tag)
    tags=Tags();tags.feed(text)
    assert not {'script','img','iframe'}&set(tags.tags)
    assert '&lt;script&gt;' in text


def test_legacy_does_not_invent_claims():
    text=render({'run_id':'old','version':'legacy'},[])
    assert 'Legacy' in text and '未转换' in text and '当前结果未提供' in text


def test_report_endpoint_ownership_and_formats(enabled):
    store,app,admin,client,user,*_=enabled
    row,_=finish(enabled);base=P+'/sessions/ses_multi/runs/'+row['id']
    result=client.get(base+'/result').json()
    response=client.get(base+'/report?format=html')
    assert response.status_code==200,response.text
    assert 'text/html' in response.headers['content-type']
    assert response.headers['cache-control']=='no-store'
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert response.text==render(result,store.rows('SELECT name,status FROM run_events WHERE run_id=? ORDER BY sequence',(row['id'],)))
    assert client.get(base+'/report?format=pdf').status_code==422
    create_user(admin,'report-other');other=login_user(app,'report-other')
    try:assert other.get(base+'/report?format=html').status_code==404
    finally:other.__exit__(None,None,None)
