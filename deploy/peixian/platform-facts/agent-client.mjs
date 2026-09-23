// Account-scoped facts token only; Agent never receives these plugins' Relay bindings.
export function remoteTool(token, name, definition) {
 return {...definition, async execute(args, ctx) {
  if(!ctx?.sessionID || !ctx?.messageID || !ctx?.callID)throw new Error('资料调用缺少受控执行身份。');
  const response=await fetch('http://gateway:8080/internal/facts/execute',{
   method:'POST',headers:{'Content-Type':'application/json','X-Facts-Key':token},
   body:JSON.stringify({session_id:ctx.sessionID,message_id:ctx.messageID,call_id:ctx.callID,tool:name,args}),
   signal:ctx.abort ?? AbortSignal.timeout(300000),redirect:'error'
  });
  if(!response.ok) {
   const body=await response.json().catch(()=>null);
   const detail=body?.detail;
   const codes=new Set(['scope_unconfirmed','scope_missing','unsupported_scope','real_provider_disabled','real_provider_configuration_invalid','provider_connection_mismatch','outside_acceptance_scope']);
   if(detail?.dispatch_status==='not_dispatched' && codes.has(detail.code))
    throw new Error(`${detail.message} [${detail.code}; not_dispatched]`);
   throw new Error('资料操作未完成，请查看本轮执行状态；结果未知时不会自动重新取数。');
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
