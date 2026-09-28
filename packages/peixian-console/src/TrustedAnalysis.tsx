import {EventDiagramView} from "./EventDiagram"
import { createEffect, For, onCleanup, Show } from "solid-js"
import { Icon, Status } from "./components"
import { clueIcon, clueTheme, dialogueIcons } from "./dialogue-icons"
import type { AnalysisClue, AnalysisResult } from "./types"
export type Presentation = AnalysisResult
export type TrustedEvidence = {turn_id?: string; presentation?: unknown}
function icon(type: string) { return ({trajectory:"route",companion:"users",vehicle:"car",place:"pin",funds:"file",relation:"users"} as Record<string,string>)[type] || "file" }
export function AnalysisResultView(props: {result: Presentation; onSelect: (clue: AnalysisClue) => void}) {
  const select=(id: string)=>{const clue=props.result.clues.find(x=>x.id===id);if(clue)props.onSelect(clue)}
  return <div class="analysis-result trusted-analysis" role="region" aria-label="研判结果">
    <section class="analysis-section analysis-process"><h3><Icon name="skill" size={17}/>研判过程</h3><div class="analysis-steps"><For each={props.result.process}>{(step,i)=><div class="analysis-step"><span class={"step-state "+step.status}>{step.status==="completed"?"✓":i()+1}</span><strong>{i()+1}. {step.title}</strong><p>{step.detail}</p><time>{step.time}</time><Status value={step.status}/></div>}</For></div></section>
    <section class="analysis-section analysis-conclusions"><h3><Icon name="file" size={17}/>核心结论</h3><ul><For each={props.result.conclusions} fallback={<li>暂无通过核对的结论。</li>}>{item=>{const source=()=>props.result.conclusion_sources?.find(value=>value.text===item);return <li><button class="conclusion-link" disabled={!source()?.clue_id} onClick={()=>source()?.clue_id&&select(source()!.clue_id!)}>{item}</button></li>}}</For></ul></section>
    <EventDiagramView value={props.result.diagram} onSelect={props.onSelect}/>
    <section class="analysis-section"><h3><Icon name="file" size={17}/>研判依据</h3><div class="analysis-evidence-grid"><For each={props.result.evidence}>{item=><button class={"analysis-evidence-card evidence-"+item.type} disabled={!item.clue_id} onClick={()=>item.clue_id&&select(item.clue_id)}><div class="analysis-evidence-title"><span><Icon name={icon(item.type)} size={17}/></span>{item.title}</div><strong>{item.value}<small>{item.unit}</small></strong><p>{item.summary}</p><For each={item.items}>{line=><small class="analysis-evidence-note">{line}</small>}</For></button>}</For></div></section>
    <Show when={props.result.missing?.length}><section class="analysis-section analysis-limits"><h3>资料缺口与局限</h3><ul><For each={props.result.missing}>{item => <li>{item}</li>}</For></ul></section></Show>
    <Show when={props.result.next_steps?.trim()}><section class="analysis-section analysis-next-steps"><h3>下一步建议</h3><p>{props.result.next_steps}</p></section></Show>
  </div>
}
export function CluePanel(props:{clues:AnalysisClue[];expanded:boolean;onExpandedChange:(expanded:boolean)=>void;onSelect:(clue:AnalysisClue)=>void;hideHeader?:boolean}) {
 return <aside class="clue-panel trusted-clues expanded right-panel--clues" aria-label="智能发现线索"><Show when={!props.hideHeader}><button class="clue-panel-head" onClick={()=>props.onExpandedChange(false)} aria-expanded={props.expanded} aria-label="收起智能发现线索"><strong>智能发现线索</strong><span class="clue-panel-actions"><small>{props.clues.length} 项</small><b>收起</b></span></button></Show><div class="clue-list"><For each={props.clues}>{clue=><article class={"clue-card clue-card--"+clueTheme(clue.type,clue.title)}><img class="clue-card-icon" src={clueIcon(clue.type,clue.title)} alt=""/><div class="clue-card-copy"><strong>{clue.title}</strong><p>{clue.headline.split(/(\d[\d,]*)/g).map((part)=>/^\d/.test(part)?<b>{part}</b>:part)}</p></div><button class="clue-card-open" onClick={()=>props.onSelect(clue)}>查看详情 <span aria-hidden="true">›</span></button></article>}</For></div></aside>
}
export function ClueDetailPanel(props: { clue: AnalysisClue; onClose: () => void; onReturn?: () => void }) {
 const theme = () => clueTheme(props.clue.type, props.clue.title)
 return <div class={"clue-detail-panel right-panel--clue-detail clue-detail--"+theme()}>
  <header class="clue-detail-head"><h2>线索详情</h2><button aria-label="关闭线索详情" onClick={props.onClose}><Icon name="close" size={17}/></button></header>
  <div class="clue-detail-scroll">
   <section class="clue-detail-hero"><img src={clueIcon(props.clue.type,props.clue.title)} alt=""/><div><h3>{props.clue.title}</h3><p>{props.clue.headline}</p></div></section>
   <section class="clue-detail-section"><h3><img src={dialogueIcons.sectionSummary} alt=""/>线索摘要</h3><p>{props.clue.summary}</p></section>
   <section class="clue-detail-section"><h3><img src={dialogueIcons.sectionFinding} alt=""/>核心发现</h3><ul><For each={props.clue.discoveries} fallback={<li>暂无可展示的核对发现。</li>}>{text=><li>{text}</li>}</For></ul></section>
   <section class="clue-detail-section clue-detail-evidence"><h3><img src={dialogueIcons.sectionEvidence} alt=""/>研判依据 <span>{props.clue.evidence.length} 项</span></h3><div class="clue-detail-evidence-list"><For each={props.clue.evidence} fallback={<p>当前线索暂无可展示的来源记录。</p>}>{item=><article><img src={dialogueIcons.document} alt=""/><div><strong>{item.label}</strong><p>{item.content}</p><Show when={item.occurred_at}><time>{item.occurred_at}</time></Show></div></article>}</For></div></section>
   <Show when={props.onReturn}><button class="clue-detail-return" onClick={()=>props.onReturn?.()}>返回关联消息</button></Show>
  </div>
 </div>
}
export function ClueDrawer(props:{clue:AnalysisClue;onClose:()=>void;onReturn?:()=>void}) {
 let dialog!:HTMLDialogElement
 const origin=document.activeElement as HTMLElement | null
 createEffect(()=>{dialog.showModal();dialog.querySelector<HTMLButtonElement>("button")?.focus()})
 onCleanup(()=>{dialog.close();queueMicrotask(()=>origin?.isConnected&&origin.focus())})
 return <dialog ref={dialog} class="trusted-drawer" aria-label="线索详情" onCancel={e=>{e.preventDefault();props.onClose()}}>
  <header><h2>线索详情</h2><Show when={props.onReturn}><button onClick={()=>props.onReturn?.()}>返回关联消息</button></Show><button class="icon-button" aria-label="关闭线索详情" onClick={props.onClose}><Icon name="close"/></button></header>
  <div class="clue-drawer-scroll">
   <section class="clue-name-card">
    <div class="clue-identity">
     <span class="clue-identity-icon"><Icon name={icon(props.clue.type)} size={22}/></span>
     <div><small>关联{props.clue.type === "person" ? "人员" : "线索"}</small><h3>{props.clue.title}</h3></div>
    </div>
    <div class="clue-meta">
     <Show when={props.clue.level}><span class="clue-level">线索等级：{props.clue.level}</span></Show>
     <Show when={props.clue.time}><span>发现时间：{props.clue.time}</span></Show>
    </div>
    <p>{props.clue.headline}</p>
    <Show when={props.clue.source}><small class="clue-source">来源任务：{props.clue.source}</small></Show>
   </section>
   <section>
    <h3><Icon name="file" size={17}/>线索摘要</h3>
    <p>{props.clue.summary}</p>
   </section>
   <section>
    <h3><Icon name="star" size={17}/>核心发现</h3>
    <ul class="clue-discoveries"><For each={props.clue.discoveries}>{text=><li>{text}</li>}</For></ul>
   </section>
   <section class="clue-evidence-section">
    <h3><Icon name="file" size={17}/>研判依据 <small>{props.clue.evidence.length} 项</small></h3>
    <div class="clue-evidence-list"><For each={props.clue.evidence}>{item=><article><span><Icon name={icon(item.type)} size={16}/></span><div><strong>{item.label}</strong><p>{item.content}</p></div></article>}</For></div>
   </section>
  </div>
 </dialog>
}
