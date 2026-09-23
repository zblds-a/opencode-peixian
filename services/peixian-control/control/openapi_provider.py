"""Versioned provider and owner-review frontend contract."""
def extend(s):
 from .openapi import obj,ref,array,STRING,BOOL,ID,nullable
 from shared.theft_provider import CATALOG
 kinds={'enum':list(CATALOG)}
 s['ProviderQuery']=obj({'start':STRING,'end':STRING,'subject':{'enum':['DEMO-PERSON-001','DEMO-PERSON-002']},'address':STRING,'center':{'enum':['DEMO-LOCATION-A','DEMO-LOCATION-B']},'radius_m':{'type':'integer','minimum':1,'maximum':5000},'page':{'type':'integer','minimum':1,'maximum':10000},'page_size':{'type':'integer','minimum':1,'maximum':100}})
 s['ProviderPreviewBody']=obj({'kind':kinds,'query':ref('ProviderQuery')},('kind','query'))
 s['ProviderPlan']=obj({'version':{'const':'theft-provider-contract-v1'},'kind':kinds,'query':ref('ProviderQuery'),'revision':{'type':'integer'},'generation':{},'expires':{'type':'integer'}},('version','kind','query','revision','generation','expires'))
 from shared.theft_provider_v2 import CATALOG as V2_CATALOG,VERSION as V2
 v2_query=obj({'lon':STRING,'lat':STRING,'radius_m':{'type':['number','string']},'start':STRING,'end':STRING,'start_date':STRING,'end_date':STRING,'track_types':array({'enum':[0,1,2]},minItems=1,maxItems=3,uniqueItems=True),'page':{'type':'integer','minimum':1},'page_size':{'type':'integer','minimum':1,'maximum':100}})
 s['ProviderPreviewBody']={'oneOf':[s['ProviderPreviewBody'],obj({'contract_version':{'const':V2},'kind':{'enum':list(V2_CATALOG)},'query':v2_query,'person_identity':{'type':'string','pattern':'^[0-9]{17}[0-9X]$'}},('contract_version','kind','query'))]}
 s['ProviderPreviewBody'].update(type='object',properties={'kind':{'enum':list(V2_CATALOG)},'query':{'type':'object'},'contract_version':{'const':V2},'person_identity':{'type':'string','writeOnly':True}})
 source_ref=obj({'run_id':ID,'result_digest':STRING,'record_id':STRING,'snapshot_id':STRING},('run_id','result_digest','record_id','snapshot_id'))
 task_fields={'analysis_task_id':ID,'context_version':{'type':'integer','minimum':1},'step_request_id':{'type':'string','format':'uuid'},'source_refs':array(source_ref),'analysis_direction':{'enum':['single_query','case_to_person','person_to_case']},'direct_parent_run_id':nullable(ID)}
 s['ProviderPreviewBody']['properties'].update(task_fields)
 s['ProviderPreviewBody']['oneOf'][1]['properties'].update(task_fields)
 s['ProviderPlan']={'oneOf':[s['ProviderPlan'],obj({'version':{'const':V2},'token':STRING},('version','token'))]}
 s['ProviderConfirmation']=obj({'plan':ref('ProviderPlan'),'confirmation':STRING},('plan','confirmation'))
 s['ProviderPreview']=obj({**s['ProviderConfirmation']['properties'],'summary':STRING},('plan','confirmation','summary'))
 s['ProviderPreview']['properties'].update(data_environment={'enum':['synthetic','acceptance_real']},contract_version=STRING)
 s['ProviderCapabilities']=obj({'items':array(obj({'kind':kinds,'name':STRING,'plugin_id':ID,'available':BOOL},('kind','name','plugin_id','available'))),'data_environment':{'const':'synthetic'},'contract_version':STRING},('items','data_environment','contract_version'))
 s['ProviderCapabilities']['properties']['contract_versions']=array(STRING)
 s['ProviderCapabilities']['properties']['items']['items']['properties'].update(kind={'enum':list(V2_CATALOG)},reason=nullable(STRING),data_environment={'enum':['synthetic','acceptance_real']},contract_version=STRING)
 s['MessageBody']['properties']['provider_query']=ref('ProviderConfirmation')
 s['MessageBody']['properties'].update(analysis_task_id=ID,source_refs=array(source_ref),scope=obj({'lon':STRING,'lat':STRING,'radius_m':{'type':'integer','minimum':1},'start':STRING,'end':STRING,'page':{'type':'integer','minimum':1},'page_size':{'type':'integer','minimum':1,'maximum':100},'person_identity':{'type':'string','writeOnly':True}}))
 s['Health']['properties']['schema_version']['enum'].append(10)
 s['Health']['properties']['schema_version']['enum'].append(11)
 s['AnalysisTaskBody']=obj({'goal':{'type':'string','minLength':1,'maxLength':4000},'client_request_id':{'type':'string','format':'uuid'},'data_environment':{'enum':['synthetic','acceptance_real']}},('goal','client_request_id','data_environment'))
 s['AnalysisTask']=obj({'analysis_task_id':ID,'scenario_id':ID,'session_id':ID,'goal':STRING,'context_version':{'type':'integer'},'scope_version':{'type':'integer'},'steps':array({'type':'object'}),'planning':array({'type':'object'}),'selected_refs':array(source_ref),'budget':{'type':'object'},'data_environment':{'enum':['synthetic','acceptance_real']},'updated_at':STRING},('analysis_task_id','scenario_id','session_id','goal','context_version','scope_version','steps','selected_refs','budget','data_environment','updated_at'))
 s['PlannerClarification']=obj({'version':{'const':'theft-clarification-v1'},'id':ID,'missing':array({'enum':['lon','lat','radius_m','start','end','page','page_size','person_identity','source','supported_scope']})},('version','id','missing'))
 s['Run']['properties']['clarification']=nullable(ref('PlannerClarification'))
 s['ClarificationDismissed']=obj({'dismissed':{'const':True}},('dismissed',))
 s['TaskSpec']['oneOf'].append(obj({'schema_version':{'const':'task-spec-v4'},'domain':{'const':'theft'},'agent_id':{'const':'theft-assistant'},'query_mode':{'enum':['new_query','explain_existing','clarify']},'methods':array(kinds,minItems=0,maxItems=1)},('schema_version','domain','agent_id','query_mode','methods'),extra=True))
 s['TaskSpec']['oneOf'][-1]['properties']['methods']['items']={'enum':list(V2_CATALOG)}
 status={'enum':['consistent','needs_information','inconsistent']}
 s['ReviewBody']=obj({'result_digest':STRING,'status':status,'note':{'type':'string','minLength':1,'maxLength':2000},'claim_ids':array(STRING,maxItems=100,uniqueItems=True),'record_refs':array(obj({'record_id':STRING,'snapshot_id':STRING},('record_id','snapshot_id')),maxItems=100),'supersedes':nullable(ID)},('result_digest','status','note'))
 s['Review']=obj({**s['ReviewBody']['properties'],'id':ID,'run_id':ID,'status_label':STRING,'reviewer':STRING,'created_at':STRING},('id','run_id','result_digest','status','note','claim_ids','reviewer','created_at','supersedes','status_label'))
 s['ReviewList']=obj({'items':array(ref('Review')),'result_digest':STRING,'unreviewed':BOOL,'total':{'type':'integer'},'page':{'type':'integer'},'page_size':{'type':'integer'}},('items','result_digest','unreviewed','total','page','page_size'))

def contracts():
 from .openapi import ref
 return {
 ('post','/sessions/{sid}/scenarios'):('AnalysisTaskBody',ref('AnalysisTask'),'创建资料任务','会话','任务组织同会话多个Run；不是用户必须选择的分析模式。'),
 ('get','/sessions/{sid}/scenarios/{scenario_id}/report'):(None,{'type':'string'},'任务资料包','会话','HTML或Markdown；同一只读快照；执行未结束409；不新增取数。'),
 ('get','/sessions/{sid}/scenarios/{scenario_id}'):(None,ref('AnalysisTask'),'读取资料任务','会话','本人任务、步骤和来源版本；跨账号404。'),
 ('get','/theft-provider/capabilities'):(None,ref('ProviderCapabilities'),'可用资料查询','会话','只列当前账号授权且已生效能力；合成接口，不访问供应方。'),
 ('post','/sessions/{sid}/provider-query/preview'):('ProviderPreviewBody',ref('ProviderPreview'),'确认资料范围','会话','只检查范围，签名有效期600秒，绑定账号、会话、配置、清除边界；不调用模型和资料服务。'),
 ('get','/sessions/{sid}/runs/{rid}/reviews'):(None,ref('ReviewList'),'本人来源复核','会话','分页读取；跨账号404，不授予管理员读取正文权限。'),
 ('post','/sessions/{sid}/runs/{rid}/clarification/reject'):(None,ref('ClarificationDismissed'),'暂不回答规划问题','会话','仅本人可操作；幂等关闭当前待补充问题，不查询资料或调用模型。'),
 ('post','/sessions/{sid}/runs/{rid}/reviews'):('ReviewBody',ref('Review'),'追加来源复核','会话','Idempotency-Key必填。终态且结果摘要匹配；追加更正保留原记录，不修改可信事实。')}
