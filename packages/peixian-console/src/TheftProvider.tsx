import TheftTaskQuery from "./TheftTaskQuery"
import { createEffect, createSignal, For, Show, onCleanup } from "solid-js"
import { api, post, ApiError, safeMessage } from "./api"
import { Button, Field, Modal, ErrorLine } from "./components"
type Choice={kind:string;name:string;available:boolean;contract_version?:string}
type Confirmation={plan:Record<string,unknown>;confirmation:string;summary:string}
type Row={record_id:string;module:string;fields:Record<string,unknown>}
type Result={agent?:{id:string};records?:Row[];versions?:{query?:Record<string,unknown>};claims?:{claim_id:string}[]}
export function ProviderQuery(props:{model:string;disabled:boolean;sessionID?:string;runID?:string;onAccepted:(sid:string)=>void}) {
 const [choices,setChoices]=createSignal<Choice[]>([]),[open,setOpen]=createSignal(false),[kind,setKind]=createSignal("incidents")
 const [sid,setSid]=createSignal(""),[start,setStart]=createSignal("2026-09-20"),[end,setEnd]=createSignal("2026-09-20")
 const [subject,setSubject]=createSignal("DEMO-PERSON-001"),[center,setCenter]=createSignal("DEMO-LOCATION-A"),[radius,setRadius]=createSignal(500)
 const [page,setPage]=createSignal(1),[confirmed,setConfirmed]=createSignal<Confirmation>(),[busy,setBusy]=createSignal(false),[error,setError]=createSignal("")
 const [uncertain,setUncertain]=createSignal(false),[result,setResult]=createSignal<Result>(),[refresh,setRefresh]=createSignal(0)
 let generation=0,alive=true,trigger:HTMLElement|undefined
 api<{items:Choice[]}>("/theft-provider/capabilities").then(v=>{if(alive)setChoices(v.items)}).catch(()=>{})
 onCleanup(()=>{alive=false;generation++})
 createEffect(()=>{const session=props.sessionID,run=props.runID;refresh();const g=++generation;setResult(undefined)
   if(session&&run)api<Result>(`/sessions/${session}/runs/${run}/result`).then(v=>{if(alive&&g===generation)setResult(v)}).catch(()=>{})
 })
 const query=()=>({...(kind().startsWith("warning_")?{}:{start:start()+" 00:00:00",end:end()+" 23:59:59"}),...(["tracks","warnings","warning_detail","warning_logs"].includes(kind())?{subject:subject()}:{}),...(["incidents","captures"].includes(kind())?{center:center(),radius_m:radius()}:{}),...(["incidents","captures","warnings"].includes(kind())?{page:page(),page_size:20}:{})})
 const change=()=>{setConfirmed(undefined);setError("")}
 async function launch(next="incidents",row?:Row){
   trigger=document.activeElement instanceof HTMLElement?document.activeElement:undefined;setError("");setConfirmed(undefined);setKind(next);setPage(1);setUncertain(false);setBusy(true)
   if(row?.fields.target_id_card)setSubject(String(row.fields.target_id_card))
   if(row?.fields.idCard)setSubject(String(row.fields.idCard))
   if(row?.fields.deviceName==="DEMO-LOCATION-A"||row?.fields.deviceName==="DEMO-LOCATION-B")setCenter(String(row.fields.deviceName))
   if(row?.module==="incidents"&&["0.001","0.002"].includes(String(row.fields.gisX))&&String(row.fields.gisY)==="0.001")setCenter(row.fields.gisX==="0.002"?"DEMO-LOCATION-B":"DEMO-LOCATION-A")
   try{const existing=result()?.agent?.id==="theft-assistant"&&props.sessionID;const s=existing|| (await post<{id:string}>("/sessions",{title:"盗窃资料核对"})).id;setSid(s);setOpen(true)}catch(e){setError(safeMessage((e as Error).message))}finally{setBusy(false)}
 }
 async function preview(){setBusy(true);setError("");try{setConfirmed(await post<Confirmation>(`/sessions/${sid()}/provider-query/preview`,{kind:kind(),query:query()}))}catch(e){setError(safeMessage((e as Error).message))}finally{setBusy(false)}}
 async function execute(){const v=confirmed();if(!v||uncertain())return;setBusy(true);setError("");try{
   await post(`/sessions/${sid()}/messages`,{text:`请按我确认的范围查询${choices().find(c=>c.kind===kind())?.name}，并核对来源。`,agent_id:"theft-assistant",model_id:props.model,skill_ids:[],plugin_ids:[],file_ids:[],mode:"standard",client_request_id:crypto.randomUUID(),provider_query:{plan:v.plan,confirmation:v.confirmation}})
   setOpen(false);props.onAccepted(sid());setRefresh(x=>x+1)
 }catch(e){if(!(e instanceof ApiError)||e.status===0||e.status>=500){setUncertain(true);props.onAccepted(sid())}setError(safeMessage((e as Error).message))}finally{setBusy(false)}}
 return <><Show when={choices().some(c=>c.contract_version==="theft-provider-contract-v2")}><TheftTaskQuery {...props}/></Show><Show when={!choices().some(c=>c.contract_version==="theft-provider-contract-v2")&&choices().some(c=>c.available)}>
   <div class="provider-actions"><Button disabled={props.disabled||busy()} onClick={()=>void launch()}>盗窃资料查询</Button><ErrorLine message={!open()&&error()}/></div>
   <Show when={result()?.versions?.query}><details class="provider-records"><summary>查看本轮来源与下一步查询（{result()?.records?.length??0} 条）</summary><p>仅依据选定记录继续；先核对时间和范围，再确认发起。资料不用于人员嫌疑评分。</p>
     <For each={result()?.records}>{(row,index)=><article><strong>来源记录 {index()+1}</strong><small>　{row.record_id}</small><dl><For each={Object.entries(row.fields)}>{([k,v])=><><dt>{({cjbh:"处警编号",jjbh:"接警编号",ajType:"来源警情类型",tags:"来源标签",records:"来源明细",lon:"来源经度字段",lat:"来源纬度字段",cjsj:"处警时间",address:"来源地址",target_name:"来源对象",target_id_card:"对象引用",capture_count:"抓拍汇总次数",deviceName:"来源地点",captureTime:"观测时间",idCard:"对象引用",personName:"来源名称",warningTypes:"来源预警类型",warningCount:"来源类型数",deviceId:"设备引用",trackType:"来源轨迹类型",latestTime:"最近触发时间",warningType:"来源预警类型",count:"来源规则触发次数",gisX:"来源经度字段",gisY:"来源纬度字段",longitude:"来源经度字段",latitude:"来源纬度字段",logs:"来源明细",communityName:"来源区域名称",id:"来源编号"} as Record<string,string>)[k]??k}</dt><dd>{typeof v==="object"?JSON.stringify(v):String(v??"未提供")}</dd></>}</For></dl>
       <Show when={row.module==="incidents"&&["0.001","0.002"].includes(String(row.fields.gisX))&&String(row.fields.gisY)==="0.001"}><Button disabled={props.disabled} onClick={()=>void launch("captures",row)}>以此位置核对抓拍范围</Button></Show>
       <Show when={row.module==="captures"||row.module==="warnings"||row.module==="warning_detail"}><Button disabled={props.disabled} onClick={()=>void launch("tracks",row)}>核对选定对象轨迹</Button><Button disabled={props.disabled} onClick={()=>void launch("warning_detail",row)}>核对来源预警</Button></Show>
       <Show when={row.module==="tracks"&&["DEMO-LOCATION-A","DEMO-LOCATION-B"].includes(String(row.fields.deviceName))}><Button disabled={props.disabled} onClick={()=>void launch("incidents",row)}>以此地点核对警情范围</Button></Show>
     </article>}</For></details></Show>
   <Show when={open()}><Modal title="确认盗窃资料查询范围" onClose={()=>{if(!busy()){setOpen(false);setConfirmed(undefined);queueMicrotask(()=>{if(trigger?.isConnected)trigger.focus()})}}} text="每次只查询选定资料与当前页；不会自动扩展对象或继续翻页。">
    <fieldset disabled={busy()||uncertain()} class="provider-form" onInput={change} onChange={change}>
     <Field label="查询资料"><select disabled={busy()||uncertain()} value={kind()} onChange={e=>{setKind(e.currentTarget.value);setPage(1)}}><For each={choices()}>{c=><option value={c.kind} disabled={!c.available}>{c.name}{c.available?"":"（尚不可用）"}</option>}</For></select></Field>
     <Show when={!kind().startsWith("warning_")}><Field label="开始日期（北京时间）"><input type="date" value={start()} onInput={e=>setStart(e.currentTarget.value)} /></Field><Field label="结束日期（包含全天）"><input type="date" value={end()} onInput={e=>setEnd(e.currentTarget.value)}/></Field></Show>
     <Show when={["tracks","warnings","warning_detail","warning_logs"].includes(kind())}><Field label="明确选定的对象"><select value={subject()} onChange={e=>setSubject(e.currentTarget.value)}><option value="DEMO-PERSON-001">对象甲</option><option value="DEMO-PERSON-002">对象乙</option></select></Field></Show>
     <Show when={["incidents","captures"].includes(kind())}><Field label="选定来源位置"><select value={center()} onChange={e=>setCenter(e.currentTarget.value)}><option>DEMO-LOCATION-A</option><option>DEMO-LOCATION-B</option></select></Field><Field label="查询半径（米；只转交来源筛选）"><input type="number" min="1" max="5000" value={radius()} onInput={e=>setRadius(Number(e.currentTarget.value))}/></Field></Show>
     <Show when={["incidents","captures","warnings"].includes(kind())}><Field label="页码（每页20条）"><input type="number" min="1" max="10000" value={page()} onInput={e=>setPage(Number(e.currentTarget.value))}/></Field></Show>
    </fieldset><Show when={kind()==="warning_logs"}><p>此来源仅提供最近7天明细，不支持自定时间。</p></Show>
    <ErrorLine message={error()}/><Show when={confirmed()}>{v=><div role="status"><p>{v().summary}</p><p>{kind().startsWith("warning_")?"采用来源固定时间范围":`${start()} 至 ${end()}（北京时间）`}{["incidents","captures"].includes(kind())?`；位置 ${center()}，半径 ${radius()} 米`: `；对象 ${subject()}`}</p></div>}</Show>
    <div class="provider-actions"><Button disabled={busy()||uncertain()} onClick={()=>void preview()}>检查范围</Button><Button variant="primary" disabled={!confirmed()||busy()||uncertain()} onClick={()=>void execute()}>确认并查询</Button></div>
    <Show when={uncertain()}><p>受理结果待确认，请关闭此窗口查看原会话，不会自动重新发起。</p></Show>
   </Modal></Show>
 </Show></>
}
export function OwnerReviews(props:{sessionID:string;runID:string}) {
 const [data,setData]=createSignal<{items:{id:string;status_label:string;note:string;created_at:string;supersedes:string|null;claim_ids:string[];record_refs?:{record_id:string;snapshot_id:string}[]}[];result_digest:string;total:number}>(),[error,setError]=createSignal("")
 const [status,setStatus]=createSignal("needs_information"),[note,setNote]=createSignal(""),[busy,setBusy]=createSignal(false),[tick,setTick]=createSignal(0),[supersedes,setSupersedes]=createSignal("")
 const [page,setPage]=createSignal(1),[locked,setLocked]=createSignal(false)
 const [targets,setTargets]=createSignal<{claims:{claim_id:string;statement:string}[];records:{record_id:string;snapshot_id:string}[]}>(),[claimIDs,setClaimIDs]=createSignal<string[]>([]),[recordIDs,setRecordIDs]=createSignal<string[]>([])
 createEffect(()=>{const sid=props.sessionID,rid=props.runID;setTargets(undefined);setClaimIDs([]);setRecordIDs([]);let active=true;onCleanup(()=>{active=false});api<NonNullable<ReturnType<typeof targets>>>(`/sessions/${sid}/runs/${rid}/result`).then(v=>{if(active)setTargets(v)}).catch(()=>{})})
 createEffect(()=>{props.sessionID;props.runID;setNote("");setPage(1);setLocked(false)})
 let generation=0,currentKey="";onCleanup(()=>generation++)
 createEffect(()=>{const sid=props.sessionID,rid=props.runID,p=page();tick();const g=++generation,key=sid+":"+rid;if(key!==currentKey){setData(undefined);currentKey=key}setError("");setSupersedes("")
 api<NonNullable<ReturnType<typeof data>>>(`/sessions/${sid}/runs/${rid}/reviews?page=${p}&page_size=20`).then(v=>{if(g===generation)setData(v)}).catch(e=>{if(g===generation&&!(e instanceof ApiError&&e.code==="reviews_unavailable"))setError(safeMessage(e.message))})})
 async function save(){const d=data();if(!d||!note().trim())return;const g=generation;setBusy(true);setError("");try{await post(`/sessions/${props.sessionID}/runs/${props.runID}/reviews`,{result_digest:d.result_digest,status:status(),note:note(),claim_ids:claimIDs(),record_refs:(targets()?.records??[]).filter(r=>recordIDs().includes(r.record_id)).map(r=>({record_id:r.record_id,snapshot_id:r.snapshot_id})),...(supersedes()?{supersedes:supersedes()}:{})});if(g===generation){setNote("");setTick(x=>x+1)}}catch(e){if(g===generation){setError(safeMessage((e as Error).message));if(!(e instanceof ApiError)||e.status===0||e.status>=500)setLocked(true)}}finally{setBusy(false)}}
 return <Show when={data()}><details class="provider-records"><summary>人工来源复核（{data()?.total??0} 条）</summary><p>复核只记录来源是否一致，不修改原事实，不用于个人嫌疑认定。记录仅本人可查看。</p><For each={data()?.items}>{r=><article><strong>{r.status_label}</strong><p>{r.note}</p><small>{r.created_at}{r.supersedes?" · 更正历史意见":""}</small><Button onClick={()=>{setSupersedes(r.id);setNote("");setClaimIDs(r.claim_ids);setRecordIDs((r.record_refs??[]).map(x=>x.record_id))}}>追加更正</Button></article>}</For>
 <fieldset disabled={!!supersedes()}><legend>选择本次复核条目</legend><For each={targets()?.claims}>{c=><label><input type="checkbox" checked={claimIDs().includes(c.claim_id)} onChange={e=>setClaimIDs(v=>e.currentTarget.checked?[...v,c.claim_id]:v.filter(x=>x!==c.claim_id))}/>{c.statement}</label>}</For><For each={targets()?.records}>{r=><label><input type="checkbox" checked={recordIDs().includes(r.record_id)} onChange={e=>setRecordIDs(v=>e.currentTarget.checked?[...v,r.record_id]:v.filter(x=>x!==r.record_id))}/>{r.record_id}</label>}</For></fieldset>
 <Field label="复核状态"><select value={status()} onChange={e=>setStatus(e.currentTarget.value)}><option value="consistent">来源核对一致</option><option value="needs_information">需要补充资料</option><option value="inconsistent">发现资料不一致</option></select></Field>
 <Field label={supersedes()?"更正意见（保留原记录）":"复核意见"}><textarea maxlength={2000} value={note()} onInput={e=>setNote(e.currentTarget.value)} /></Field><ErrorLine message={error()}/><Button disabled={busy()||locked()||!note().trim()||(!claimIDs().length&&!recordIDs().length)} onClick={()=>void save()}>追加复核记录</Button><Button onClick={()=>{setTick(x=>x+1);setLocked(false)}}>刷新复核状态</Button><Button disabled={page()<=1} onClick={()=>setPage(x=>x-1)}>上一页</Button><span>第 {page()} 页</span><Button disabled={page()*20>=(data()?.total??0)} onClick={()=>setPage(x=>x+1)}>下一页</Button>
 </details></Show>
}
