import { createEffect, createMemo, createSignal, For, onCleanup, Show } from "solid-js"

export type EvidenceCard = { id: string; title: string; description: string; time: string; source_ids: string[]; fields: { label: string; value: string }[]; message_id: string; snapshot_id: string }
export type Evidence = {
  summary_check?: string; verified_summary?: { fact_id: string; statement: string; source_ids: string[] }[]
  turn_id?: string; status: string; notice: string; scenario: null | { title: string; scenario_id: string; subject_ref: string; snapshot_id: string; records_snapshot_id: string; rule_version: string; timezone: string; night_window: string; case_window: string[] }
  steps: { label: string; status: string }[]; cards: EvidenceCard[]; missing: string[]
  summary: { label: string; count: number; dates: string[]; night_count: number }[]
}
const labels: Record<string, string> = { pending: "等待处理", running: "正在获取", completed: "已完成", error: "未通过检查" }
export default function EvidencePanel(props: { value?: Evidence; summary?: boolean; error?: string; onRetry: () => void }) {
  const [selected, setSelected] = createSignal<EvidenceCard>()
  const [expanded, setExpanded] = createSignal(false)
  let origin: HTMLElement | undefined
  const close = () => { setSelected(undefined); queueMicrotask(() => origin?.isConnected && origin.focus()) }
  const turn = createMemo(() => props.value?.turn_id)
  createEffect(() => { turn(); setSelected(undefined) })
  return <Show when={!props.summary} fallback={
    <Show when={props.value?.steps.length}>
      <section class="evidence-summary" aria-label="实际资料获取过程">
        <h3>{props.value?.scenario?.title || "资料获取过程"}</h3>
        <p>{props.value?.notice} 助手文字摘要未经逐项核验，请以来源记录为准。</p>
        <ol><For each={props.value?.steps}>{step => <li>{step.label}<span>{labels[step.status] || "等待处理"}</span></li>}</For></ol>
        <div class="evidence-counts"><For each={props.value?.summary}>{item => <div><strong>{item.count}</strong><span>{item.label}</span><small>涉及 {item.dates.length} 个自然日 · 夜间 {item.night_count} 条</small></div>}</For></div>
        <Show when={props.value?.scenario}><p>北京时间 · 夜间 22:00 至次日 06:00；仅统计返回资料，不推断行为目的。</p></Show>
        <Show when={props.value?.summary_check}>
          <section aria-label="已核对摘要"><h3>已核对摘要</h3><p>仅以下原句通过代码核对；助手其他文字及改写仍未核验。</p>
          <For each={props.value?.verified_summary} fallback={<p>尚无通过核对的摘要表述。</p>}>{fact => <p>{fact.statement}<small> 来源：{fact.source_ids.join("、") || "已取得的完整模块与固定统计口径"}</small></p>}</For>
          <Show when={props.value?.summary_check === "rejected"}><p>部分提交表述不被来源支持，已拒绝展示为核验结果。</p></Show></section>
        </Show>
        <details><summary>资料缺口与限制</summary><ul><For each={props.value?.missing}>{text => <li>{text}</li>}</For></ul></details>
      </section>
    </Show>
  }>
    <aside class={"evidence-panel " + (expanded() ? "expanded" : "")} aria-label="资料发现">
      <button class="evidence-heading" onClick={() => setExpanded(!expanded())} aria-expanded={expanded()}>资料发现 <span>{props.value?.cards.length || 0} 条</span></button>
      <div class="evidence-content">
        <p class="quiet">已完成工具调用的来源记录 · 仅本人可见</p>
        <Show when={props.error}><p role="alert">{props.error}</p><button onClick={props.onRetry}>重新读取</button></Show>
        <For each={props.value?.cards} fallback={<p class="evidence-empty">尚无可展示的资料。选择场景 Skill 并完成工具调用后，这里会显示来源记录。</p>}>
          {card => <article class="evidence-card"><h3>{card.title}</h3><p>{card.description}</p><small>{card.id} · {card.time || "无时间字段"}</small><button onClick={event => { origin = event.currentTarget; setSelected(card) }}>查看依据</button></article>}
        </For>
      </div>
    </aside>
    <Show when={selected()}>{card => <EvidenceDrawer card={card()} close={close} />}</Show>
  </Show>
}
function EvidenceDrawer(props: { card: EvidenceCard; close: () => void }) {
  let dialog!: HTMLDialogElement
  createEffect(() => { dialog.showModal(); dialog.querySelector<HTMLButtonElement>("button")?.focus() })
  onCleanup(() => dialog?.close())
  return <dialog ref={dialog} class="evidence-drawer" aria-label="资料依据详情" onCancel={event => { event.preventDefault(); props.close() }}>
    <header><h2>资料依据详情</h2><button aria-label="关闭资料详情" onClick={props.close}>关闭</button></header>
    <h3>{props.card.title}</h3><p>{props.card.description}</p>
    <dl><dt>记录编号</dt><dd>{props.card.id}</dd><dt>时间</dt><dd>{props.card.time || "资料未提供"}</dd><dt>资料快照</dt><dd>{props.card.snapshot_id}</dd>
    <For each={props.card.fields}>{field => <><dt>{field.label}</dt><dd>{field.value}</dd></>}</For></dl>
    <h3>引用来源</h3><ul><For each={props.card.source_ids} fallback={<li>本条即为原始来源记录</li>}>{id => <li>{id}</li>}</For></ul>
    <p>记录存在不证明违法犯罪；没有观测记录也不证明行为未发生。</p>
    <Show when={props.card.message_id}><button onClick={() => { const id = props.card.message_id; props.close(); queueMicrotask(() => document.getElementById("message-" + id)?.scrollIntoView({ block: "center" })) }}>返回关联消息</button></Show>
  </dialog>
}
