// Account-scoped facts token only; Agent never receives these plugins' Relay bindings.
export function remoteTool(token, name, definition) {
 const fields=definition.args;
 const args=fields?.person_identity ? {...fields,person_identity:{...fields.person_identity,description:'用户已确认的原始单人身份号码，或本人本会话同一已确认对象的 person-* 引用。平台严格核对等值；不能用其他对象或其他会话引用替换。'}} : fields;
 return {...definition,...(args ? {args} : {}), async execute(args, ctx) {
  if(!ctx?.sessionID || !ctx?.messageID || !ctx?.callID)throw new Error('资料调用缺少受控执行身份。');
  const response=await fetch('http://gateway:8080/internal/facts/execute',{
   method:'POST',headers:{'Content-Type':'application/json','X-Facts-Key':token},
   body:JSON.stringify({session_id:ctx.sessionID,message_id:ctx.messageID,call_id:ctx.callID,tool:name,args}),
   signal:ctx.abort ?? AbortSignal.timeout(300000),redirect:'error'
  });
  if(!response.ok) {
   const body=await response.json().catch(()=>null);
   const detail=body?.detail;
   const codes=new Set(['source_selection_required','explicit_source_required','source_selection_limit','source_value_override','source_record_unavailable','source_version_changed','source_integrity_failed','source_coordinates_missing','source_identity_missing','identity_parameter_invalid','scope_unconfirmed','scope_parameter_invalid','scope_missing','unsupported_scope','unsupported_query_conditions','precise_time_required','time_range_limit','pagination_limit','native_tool_invalid','coordinate_contract_unconfirmed','real_provider_disabled','real_provider_configuration_invalid','provider_connection_mismatch','provider_connection_unavailable','provider_connection_unconfigured','provider_not_applied','native_authority_changed','native_tool_unavailable','tool_archived','intent_review_unavailable','tool_call_busy','tool_call_unconfirmed','tool_call_conflict','native_duplicate_call','native_no_progress','run_not_active','provider_business_error','provider_response_invalid','provider_cancelled','provider_result_unknown','provider_binding_changed']);
   const safe = detail?.version==='tool-failure-v1' && codes.has(detail.code);
   const message = safe ? detail.message : '本次资料操作未完成，请凭调用标识核对执行状态。';
   const fields = safe && detail.field_errors ? Object.keys(detail.field_errors).filter(k=>['person_identity','start','end','lon','lat','radius_m','page','page_size'].includes(k)) : [];
   throw new Error(JSON.stringify({code:safe?detail.code:'tool_execution_unavailable',message,stage:safe?detail.stage:'execution',dispatch_status:safe?detail.dispatch_status:'unknown',field_errors:fields,recovery_action:safe?detail.recovery_action:'reconcile',call_id:ctx.callID}));
  }
  return JSON.stringify(await response.json());
 }};
}
export function helpers(token) {
 const scenario={type:'string',enum:['DEMO-CASE-GAMBLING','DEMO-CASE-THEFT']};
 const definitions={
  peixian_get_scenario_context:{description:'读取本轮已冻结的场景和资料范围，不查询业务记录。',args:{scenario_id:scenario}},
  peixian_prepare_scenario_facts:{description:'按本轮平台固定方法查询必要插件、复用本轮已取得资料并生成代码事实。未知结果不重发。',args:{scenario_id:scenario,methods:{type:'array',minItems:1,maxItems:6,items:{type:'string',enum:['night','companions','funds','relations','calls','vehicles']}}}},
  peixian_check_scenario_summary:{description:'核对本轮事实原句与来源，不重新取数。',args:{scenario_id:scenario,claims:{type:'array',maxItems:40,items:{type:'object',additionalProperties:false,required:['fact_id','statement','source_ids'],properties:{fact_id:{type:'string'},statement:{type:'string'},source_ids:{type:'array',items:{type:'string'}}}}}}}
 };
 return {tool:Object.fromEntries(Object.entries(definitions).map(([name,definition])=>[name,remoteTool(token,name,definition)]))};
}
