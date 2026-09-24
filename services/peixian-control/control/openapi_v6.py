"""Additive contract for backend v6. Kept separate from historical contracts."""
def extend_schemas(result):
    from .openapi import obj,ref,array,STRING,BOOL,ID,nullable
    profile={'display_name':STRING,'police_no':STRING,'position':STRING,'department_id':nullable(ID),'department':nullable(ref('Department')),'last_login_at':nullable({'type':'string','format':'date-time'}),'system_role':{'type':'string','enum':['super_admin','admin','user']}}
    result['Department']=obj({'id':ID,'name':STRING,'code':STRING,'parent_id':nullable(ID),'sort_order':{'type':'integer'},'updated_at':{'type':'string','format':'date-time'},'children':array(ref('Department'))},('id','name','code','parent_id','sort_order'))
    result['DepartmentBody']=obj({k:v for k,v in result['Department']['properties'].items() if k in ('name','code','parent_id','sort_order')})
    result['DepartmentTree']=obj({'items':array(ref('Department')),'total':{'type':'integer'},'page':{'type':'integer'},'page_size':{'type':'integer'}},('items','total','page','page_size'))
    result['UserSummary']=obj({k:{'type':'integer'} for k in ('users','enabled','disabled','departments')},('users','enabled','disabled','departments'))
    for name in ('User','UserCreateBody','UserUpdateBody'):
        if name in result:result[name]['properties'].update(profile if name=='User' else {k:v for k,v in profile.items() if k in ('display_name','police_no','position','department_id')})
    fields={'provider':STRING,'context_length':nullable({'type':'integer','minimum':256,'maximum':2000000}),'access_mode':{'type':'string','enum':['api','local']},'supports_tools':BOOL}
    for name in ('AdminModel','ModelCreateBody','ModelUpdateBody'):
        if name in result:result[name]['properties'].update(fields)
    if 'AdminModel' in result:result['AdminModel']['properties'].update({'test_status':STRING,'updated_at':nullable({'type':'string','format':'date-time'})})
    result['ModelTestResult']=obj({'ok':BOOL,'message':STRING,'elapsed_ms':{'type':'integer'}},('ok','message','elapsed_ms'))
    if 'Health' in result and 'schema_version' in result['Health'].get('properties',{}):result['Health']['properties']['schema_version']={'type':'integer','enum':[4,5,6,7,8,9]}
    result['Error']['properties']['field_errors']={'type':'object','additionalProperties':STRING}
    integer={'type':'integer'}
    dt={'type':'string','format':'date-time'}
    def paginated(item):return obj({'items':array(ref(item)),'total':integer,'page':integer,'page_size':integer},('items','total','page','page_size'))
    result['Run']=obj({'id':ID,'session_id':ID,'status':{'type':'string','enum':['queued','running','cancelling','reconciling','completed','failed','cancelled']},'phase':STRING,'cancel_requested':BOOL,'model_id':ID,'message_id':nullable(ID),'user_message_id':ID,'parent_run_id':nullable(ID),'created_at':dt,'started_at':nullable(dt),'completed_at':nullable(dt),'updated_at':dt,'error':nullable(obj({'code':STRING,'message':STRING}))},('id','session_id','status','phase','created_at'))
    from .task_spec import SPEC_SCHEMA,SPEC_V2_SCHEMA,SPEC_V3_SCHEMA,CANDIDATE_SCHEMA
    result['RunOutcome']=obj({'version':{'const':'run-outcome-v1'},'status':{'enum':['processing','unconfirmed','cancelled','failed','needs_input','historical','partial','data_ready','no_query']},'label':STRING,'message':STRING,'next_steps':array(STRING),'execution_status':STRING,'data_status':STRING,'queried':nullable(BOOL)},('version','status','label','message','next_steps','execution_status','data_status','queried'))
    result['Run']['properties']['outcome']=ref('RunOutcome')
    result['Run']['properties'].update({'status_revision':integer,'event_sequence':integer,'status_authority':{'const':'run'},'answer_delivery':{'type':'object','additionalProperties':True}})
    result['AnswerSegment']=obj({'sequence':integer,'content_revision':integer,'part_id':ID,'operation':{'const':'append'},'origin':{'const':'controlled_source'},'visibility':{'const':'user'},'display_kind':{'const':'source_answer'},'text':STRING,'source_ids':array(STRING),'claim_ids':array(ID)},('sequence','content_revision','part_id','operation','origin','visibility','display_kind','text','source_ids','claim_ids'))
    result['AnswerSegments']=obj({'version':{'const':'controlled-segments-v1'},'run_id':ID,'message_id':ID,'status':STRING,'items':array(ref('AnswerSegment')),'next_sequence':integer,'final':BOOL,'has_more':BOOL,'execution_status':STRING},('version','run_id','status','items','next_sequence','final'))

    result['TaskSpecV1']=SPEC_SCHEMA
    result['TaskSpecV2']=SPEC_V2_SCHEMA
    result['TaskSpecV3']=SPEC_V3_SCHEMA
    result['TaskSpec']={'oneOf':[ref('TaskSpecV1'),ref('TaskSpecV2'),ref('TaskSpecV3')]}
    result['TaskCandidateV1']=CANDIDATE_SCHEMA
    from .task_spec import candidate_schema
    from .agents.registry import PROFILES
    result['TaskCandidate']={'oneOf':[ref('TaskCandidateV1'),{'anyOf':[candidate_schema(p) for p in PROFILES.values()]}]}
    result['AgentPublic']=obj({k:STRING for k in ('id','name','version','domain','description')},('id','name','version','domain','description','supported_intents'))
    result['AgentPublic']['properties']['supported_intents']=array(STRING)
    result['AgentList']=obj({'items':array(ref('AgentPublic'))},('items',))
    result['AgentIdentity']=obj({k:STRING for k in ('schema_version','registry_version','id','version','domain','profile_sha256','prompt_sha256','default_scenario_id')})
    result['RunTask']=obj({'run_id':ID,'task_spec':nullable(ref('TaskSpec')),'agent_profile':nullable(ref('AgentIdentity')),'effective_system_prompt_sha256':nullable(STRING),'response':nullable(obj({'code':STRING,'message':STRING,'clarification_id':ID},('code','message')))},('run_id','task_spec','response'))
    result['TaskClarification']=obj({'schema':{'const':'peixian.task-clarification'},'version':{'const':'1.0'},'clarification_id':ID,'agent_id':ID,'field':{'const':'target_refs'},'question':STRING,'options':array(obj({'id':ID,'label':STRING},('id','label'))),'context_generation':{'type':'integer','minimum':1},'context_version':{'type':'integer','minimum':1},'status':{'enum':['pending','resolved','cancelled','expired']},'updated_at':dt},('schema','version','clarification_id','agent_id','field','question','options','context_generation','context_version','status','updated_at'))
    result['ClarificationCancelBody']=obj({'context_generation':{'type':'integer','minimum':1},'context_version':{'type':'integer','minimum':1},'client_request_id':{'type':'string','minLength':1,'maxLength':128}},('context_generation','context_version','client_request_id'))
    result['ClarificationResolveBody']=obj({**result['ClarificationCancelBody']['properties'],'option_id':ID},('option_id','context_generation','context_version','client_request_id'))
    result['ClarificationChange']=obj({'resolved':BOOL,'cancelled':BOOL,'context_generation':integer,'context_version':integer,'resume_required':BOOL},('context_generation','context_version','resume_required'))
    result['TaskContext']=obj({'schema':{'const':'session-context-v1'},'agent_id':ID,'agent_profile_sha256':STRING,'generation':{'type':'integer','minimum':1},'version':{'type':'integer','minimum':1},'last_completed_run_id':nullable(ID),'last_data_run_id':nullable(ID),'pending_clarification_id':nullable(ID),'updated_at':dt},('schema','agent_id','agent_profile_sha256','generation','version','last_completed_run_id','last_data_run_id','pending_clarification_id','updated_at'))
    result['RunSource']=obj({'run_id':ID,'run_kind':nullable({'enum':['data_query','history_explanation','clarification','ordinary_chat']}),'direct_parent_run_id':nullable(ID),'source_data_run_id':nullable(ID),'projection_version':nullable(STRING),'projection_digest':nullable(STRING)},('run_id','run_kind','direct_parent_run_id','source_data_run_id','projection_version','projection_digest'))
    result['MessageBody']['properties']['context_version']={'type':'integer','minimum':1,'description':'可选的已读取上下文版本；旧版本返回409 task_context_changed。同请求标识重放仍返回首次受理。'}
    result['RunAccepted']=obj({'accepted':{'const':True},'run_id':ID,'message_id':ID},('accepted','run_id','message_id'))
    result['RunEvent']=obj({'id':ID,'sequence':integer,'step_type':STRING,'name':STRING,'status':STRING,'started_at':nullable(dt),'completed_at':nullable(dt),'elapsed_ms':nullable(integer),'capability_id':nullable(ID),'input_summary':STRING,'output_summary':STRING,'record_count':integer,'evidence_refs':array(STRING),'error_message':nullable(STRING)},('id','sequence','step_type','name','status'))
    result['RunEvidence']=obj({**result['ScenarioEvidence']['properties'],'run_id':ID,'status':{'enum':['pending','empty','partial','complete','unavailable']}},('run_id','status','cards','summary'))
    result['Identity']['properties']['capabilities']['items']['enum'].extend(['departments.manage','invocations.read'])
    result['AnalysisResult']=obj({'schema':{'const':'peixian.analysis-result'},'version':{'const':'1.0'},'run_id':ID,'generated_at':dt,'intro':STRING,'process':result['ScenarioPresentation']['properties']['process'],'subjects':array({'type':'object'}),'conclusions':array(STRING),'evidence':result['ScenarioPresentation']['properties']['evidence'],'clues':result['ScenarioPresentation']['properties']['clues'],'next_steps':STRING,'conclusion_sources':array(obj({'text':STRING,'clue_id':STRING,'source_ids':array(STRING)})),'source_metadata':{'type':'object','additionalProperties':True},'presentation_version':STRING},('schema','version','run_id','process','subjects','conclusions','evidence','clues'))
    result['AnalysisResult']['properties']['diagram']={'anyOf':[result['ScenarioDiagram'],{'type':'null'}]}
    part=result['Message']['properties']['parts']['items']['properties']
    part['type']['enum'].append('analysis_result');part['data']=ref('AnalysisResult')
    result['Capability']=obj({'id':ID,'kind':{'enum':['personal_skill','plugin','official_skill']},'name':STRING,'description':STRING,'version':nullable({}),'category':STRING,'recommended':BOOL,'enabled':BOOL,'owned':BOOL,'scope':STRING,'available':BOOL,'unavailable_reason':nullable(STRING),'dependency_ids':array(ID)},('id','kind','name','available'))
    result['OfficialMethod']=obj({'id':STRING,'version':STRING,'state':{'enum':['draft','published','disabled']},'method':STRING,'dependency_ids':array(ID),'sha256':STRING},('id','version','state','method','dependency_ids','sha256'))
    result['Capability']['properties']['official_method']=nullable(ref('OfficialMethod'))
    result['Capability']['properties'].update({'selectable_in_message':BOOL,'selection_mode':{'enum':['preference','method','unavailable']},'selection_unavailable_reason':nullable(STRING)})
    for name in ('ScenarioEvidence','RunEvidence'):
        result[name]['properties'].update(processing_version=STRING,execution_methods=array(STRING),plugin_versions={'type':'object','additionalProperties':STRING})
    result['Invocation']=obj({'id':ID,'run_id':ID,'session_id':ID,'username':STRING,'display_name':nullable(STRING),'department_name':nullable(STRING),'model_id':ID,'model_name':nullable(STRING),'status':STRING,'query_summary':STRING,'created_at':dt,'duration_ms':nullable(integer),'record_count':integer,'skill_ids':array(ID),'plugin_ids':array(ID),'actual_plugin_ids':array(ID),'steps':array(ref('RunEvent'))},('id','run_id','status','query_summary','created_at'))
    for name in ('Run','RunEvent','Capability','Invocation'):result[name+'Page']=paginated(name)
    result['CapabilityPage']['properties']['message_support']={'type':'object','additionalProperties':True}
    result['MessageBody']['properties'].update({'client_request_id':{'type':'string','format':'uuid','description':'新客户端必须发送。旧客户端省略时服务端生成，不具备客户端重试去重保证。'},'plugin_ids':array(ID,maxItems=5),'agent_id':{'type':'string','enum':['gambling-assistant','theft-assistant'],'description':'新客户端显式选择；省略兼容涉赌。盗窃需双白名单；同会话更换助手返回409，不增加授权。'},'mode':{'enum':['standard']}})
    result['RerunBody']=obj(dict(result['MessageBody']['properties']),('client_request_id',))
    for name in ('Skill','SkillCreateBody','SkillUpdateBody'):result[name]['properties']['dependency_ids']=array(ID,maxItems=20)
    fields={'name':STRING,'description':STRING,'content':STRING,'dependency_ids':array(ID),'input_schema':{'type':'object','additionalProperties':True},'default_rules':array(STRING)}
    result['SkillDraftBody']=obj(fields)
    result['SkillDraft']=obj({**fields,'id':ID,'session_id':nullable(ID),'source_type':STRING,'status':{'enum':['preparing','generating','ready','needs_review','failed','saved']},'run_id':nullable(ID),'saved_skill_id':nullable(ID),'scope':{'const':'personal'},'error':nullable(obj({'code':STRING,'message':STRING})),'created_at':dt,'updated_at':dt},('id','status','source_type','scope','created_at','updated_at'))
    result['DraftGenerateBody']=obj({'requirement':STRING,'session_id':ID,'model_id':ID,'client_request_id':{'type':'string','format':'uuid'}},('client_request_id',))
    result['DraftTestBody']=obj({'mode':{'enum':['validation','model']},'text':STRING,'model_id':ID,'client_request_id':{'type':'string','format':'uuid'}})
    result['DraftTestResult']=obj({'mode':{'enum':['validation','model']},'ok':BOOL,'field_errors':{'type':'object','additionalProperties':STRING},'model_executed':nullable(BOOL),'accepted':BOOL,'session_id':ID,'run_id':ID,'message_id':ID},('mode','model_executed'))
    result['EmptyBody']=obj({})
    result['DraftSaveResult']=obj({'skill_id':ID,'scope':{'const':'personal'},'enabled':BOOL,'job':ref('Job'),'already_saved':BOOL},('skill_id','scope','already_saved'))
    from .openapi_v9 import extend_schemas
    return extend_schemas(result)


def contracts():
    from .openapi import ref
    result = {
      ('get','/admin/users/summary'):(None,ref('UserSummary'),'查询可管理用户汇总','管理：账号','管理员仅统计普通用户；超管统计普通用户和管理员。'),
      ('get','/admin/departments/tree'):(None,ref('DepartmentTree'),'查询部门树','管理：账号','三角色中的两个管理角色可读。'),
      ('post','/admin/departments'):('DepartmentBody',ref('Department'),'创建部门','管理：账号','仅超级管理员；幂等写入。'),
      ('patch','/admin/departments/{did}'):('DepartmentBody',ref('Department'),'修改部门','管理：账号','仅超级管理员；禁止环。'),
      ('delete','/admin/departments/{did}'):(None,ref('Ok'),'删除空部门','管理：账号','仅超级管理员；非空返回409。'),
      ('post','/admin/models/test'):('ModelCreateBody',ref('ModelTestResult'),'保存前模型连接测试','管理：模型','不落模型配置；只验证连接和模型ID，不验证推理或工具能力。'),
      ('post','/admin/models/{mid}/test'):(None,ref('ModelTestResult'),'测试已保存模型','管理：模型','只验证连接和模型ID，返回真实耗时。'),
    }

    def add(method,path,body,out,title,tag='执行记录',desc='当前账号资源；不属于本人返回404。'):
        result[(method,path)]=(body,out,title,tag,desc)
    add('get','/agents',None,ref('AgentList'),'查询可用助手','助手目录','只返回当前账号可用助手的公开信息，不返回 Prompt 或连接配置。')
    add('get','/agents/{agent_id}',None,ref('AgentPublic'),'查询助手公开信息','助手目录')
    add('post','/sessions/{sid}/messages','MessageBody',ref('RunAccepted'),'提交消息并受理持久执行',desc='HTTP 202返回持久run_id和固定message_id；plugin_ids 是偏好；同 client_request_id 同内容返回首次受理，不自动重发未知执行。')
    add('get','/sessions/{sid}/context',None,{'type':'object','properties':{'scenario_id':{'type':['string','null']},'name':{'type':['string','null']},'source':{'type':'string'},'generation':{'type':['string','null']}}},'读取本人会话场景')
    add('delete','/sessions/{sid}/context',None,{'type':'object'},'清除本人会话场景',desc='需要 Idempotency-Key；执行未结束返回409；持久清除边界不删除历史。')
    add('get','/sessions/{sid}/task-context',None,ref('TaskContext'),'读取本人会话任务上下文',desc='schema v7 及以上且账号灰度开启；新会话可指定 agent_id，已绑定会话不能切换。')
    add('delete','/sessions/{sid}/task-context',None,ref('TaskContext'),'重置本人会话任务上下文',desc='需要 Idempotency-Key；增加 generation/version，清空指针，不改变助手、不删除历史；迟到执行不能恢复旧上下文。')
    add('get','/sessions/{sid}/runs/{rid}/source',None,ref('RunSource'),'读取本人执行的冻结历史来源',desc='只返回归属核对后的来源标识及投影摘要，不返回 Prompt、插件配置或规则实现。')
    add('get','/sessions/{sid}/clarifications/{cid}',None,ref('TaskClarification'),'读取本人对象确认选项',desc='选项来自冻结的可信结构化资料；只公开选项 ID 与名称。')
    add('post','/sessions/{sid}/clarifications/{cid}/resolve','ClarificationResolveBody',ref('ClarificationChange'),'确认对象',desc='零模型、零插件；需上下文代次及版本。成功返回 resume_required=true，随后标准消息才能查询。')
    add('post','/sessions/{sid}/clarifications/{cid}/cancel','ClarificationCancelBody',ref('ClarificationChange'),'取消对象确认',desc='零查询；client_request_id 为此确认操作的幂等标识。')
    add('get','/capabilities',None,ref('CapabilityPage'),'查询当前可用能力','能力目录')
    add('get','/sessions/{sid}/runs',None,ref('RunPage'),'查询会话执行记录')
    add('get','/sessions/{sid}/runs/{rid}',None,ref('Run'),'查询执行状态')
    add('get','/sessions/{sid}/runs/{rid}/task',None,ref('RunTask'),'读取本轮冻结任务',desc='仅本人可读；TaskSpec 为服务端生成，不接受客户端写入。schema v7 的历史解释使用冻结可信资料；旧 Run 按原契约返回。')
    for suffix,schema,title in [('result','TrustedResultResponse','读取不可变可信结果'),('claims','RunClaims','读取已核对声明'),('data-usage','RunDataUsage','读取资料实际使用状态')]:
        add('get','/sessions/{sid}/runs/{rid}/'+suffix,None,ref(schema),title,desc='本人资源；schema v9及账号灰度只影响新Run。终态结果不可变；旧Run返回legacy；活动Run仅返回pending状态，不重新取数。')
    add('get','/sessions/{sid}/runs/{rid}/sources/{evidence_id}',None,ref('SourceDetail'),'读取本人已保存的来源记录',desc='按证据ID匹配冻结Result；不查上游，不重建旧结果；跨账号及不存在均404。')
    add('get','/sessions/{sid}/runs/{rid}/answer-segments',None,ref('AnswerSegments'),'读取可重放的受控资料片段',desc='仅本人；after为已收到的序号，limit为1至100；只读，不产生模型或资料调用。final表示片段流封闭，不表示执行成功。')
    add('get','/sessions/{sid}/runs/{rid}/events',None,ref('RunEventPage'),'增量查询持久步骤')
    add('get','/sessions/{sid}/runs/{rid}/evidence',None,ref('RunEvidence'),'查询固定执行证据',desc='按本人账号/会话/Run鉴权读取已保存证据；旧插件卸载不删除历史证据，读取不重新取数。')
    add('post','/sessions/{sid}/runs/{rid}/abort',None,ref('Run'),'请求停止执行')
    add('post','/sessions/{sid}/runs/{rid}/rerun','RerunBody',ref('RunAccepted'),'明确创建关联重跑')
    add('get','/sessions/{sid}/runs/{rid}/report',None,{'type':'string'},'导出 HTML 或 Markdown 执行报告')
    add('get','/admin/invocations',None,ref('InvocationPage'),'查询脱敏调用元数据','调用审计')
    add('get','/admin/invocations/{iid}',None,ref('Invocation'),'查询脱敏调用详情','调用审计')
    add('get','/admin/invocations/export',None,{'type':'string'},'导出 UTF-8 BOM CSV','调用审计')
    for path in ('from-requirement','from-session'):
        add('post','/skill-drafts/'+path,'DraftGenerateBody',ref('SkillDraft'),'受理模型辅助草稿','技能草稿','新客户端提供请求标识；生成不调用工具，不发布技能。')
    add('get','/skill-drafts/{did}',None,ref('SkillDraft'),'查询本人草稿','技能草稿')
    add('patch','/skill-drafts/{did}','SkillDraftBody',ref('SkillDraft'),'编辑本人草稿','技能草稿')
    add('post','/skill-drafts/{did}/test','DraftTestBody',ref('DraftTestResult'),'检查或试运行草稿','技能草稿','validation不调用模型；model需要客户端请求标识并创建独立会话。')
    add('post','/skill-drafts/{did}/save','EmptyBody',ref('DraftSaveResult'),'明确保存为个人技能','技能草稿','默认停用，等待用户启用及配置生效；保存不能获得公共发布权限。')
    return result
