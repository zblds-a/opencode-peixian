import {test} from 'node:test';
import assert from 'node:assert/strict';
import {remoteTool} from './agent-client.mjs';
const context={sessionID:'s',messageID:'m',callID:'c'};
test('known preflight rejection remains not dispatched; unknown errors stay opaque',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'scope_missing',dispatch_status:'not_dispatched',message:'请补充范围。本次未访问资料接口。'}}),{status:409});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),/not_dispatched/);
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'identity_parameter_invalid',dispatch_status:'not_dispatched',message:'请使用已确认身份号码。'}}),{status:409});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),/identity_parameter_invalid; not_dispatched/);
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'private',message:'secret'}}),{status:500});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),e=>!e.message.includes('secret')&&e.message.includes('结果未知'));
 } finally {globalThis.fetch=original;}
});
