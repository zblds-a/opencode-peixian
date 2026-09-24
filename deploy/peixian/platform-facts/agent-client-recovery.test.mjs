import { test } from "bun:test";
import assert from "node:assert/strict";
import { remoteTool } from "./agent-client.mjs";
test("failure boundary carries safe source error", async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{version:"tool-failure-v1",code:"source_selection_required",message:"请选择位置来源",stage:"precheck",dispatch_status:"not_dispatched",recovery_action:"select_source",field_errors:{}}}),{status:409});
 try { await assert.rejects(remoteTool("test","peixian_query_captures",{}).execute({}, {sessionID:"s",messageID:"m",callID:"c"}),e=>JSON.parse(e.message).code==="source_selection_required"); }
 finally {globalThis.fetch=original;}
});
test("unknown error body cannot escape", async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:"private_secret",message:"http://secret token"}}),{status:500});
 try {await assert.rejects(remoteTool("test","peixian_query_tracks",{}).execute({}, {sessionID:"s",messageID:"m",callID:"c"}),e=>!e.message.includes("http://secret")&&JSON.parse(e.message).dispatch_status==="unknown");}
 finally {globalThis.fetch=original;}
});
