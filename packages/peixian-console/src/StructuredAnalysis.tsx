import { For, Show } from "solid-js"
import { Icon, Status } from "./components"
import type { AnalysisClue, AnalysisEvidenceCard, AnalysisResult, Json, Part } from "./types"

export const mockAnalysisResult: AnalysisResult = {
  schema: "peixian.analysis-result",
  version: "1.0",
  run_id: "mock-run-night-001",
  generated_at: "2026-09-17T15:34:18+08:00",
  intro: "已根据您的需求完成分析，以下是张某最近30天的夜间活动情况及关联人员研判结果。",
  process: [
    { id: "step-1", title: "获取目标对象信息", detail: "调取张某的基础信息和重点人员库数据", time: "15:32:10", status: "completed" },
    { id: "step-2", title: "查询近期轨迹", detail: "检索最近30天授权范围内的轨迹记录", time: "15:32:28", status: "completed" },
    { id: "step-3", title: "分析同行人员", detail: "基于时空碰撞分析同行人员及关联关系", time: "15:33:05", status: "completed" },
    { id: "step-4", title: "关联车辆信息", detail: "检索关联车辆及共同出行记录", time: "15:33:42", status: "completed" },
    { id: "step-5", title: "生成研判结果", detail: "整合多源数据形成结构化研判结论", time: "15:34:18", status: "completed" },
  ],
  subjects: [{
    id: "person-masked-01",
    name: "张某",
    fields: [
      { label: "性别", value: "男" },
      { label: "年龄", value: "36岁" },
      { label: "身份证", value: "320322********1234" },
      { label: "户籍地", value: "江苏省沛县汉城街道***" },
      { label: "现居住地", value: "沛县经济开发区***小区" },
    ],
    tags: ["夜间活跃", "重点关注人员", "多名同行人员", "关联车辆"],
  }],
  conclusions: [
    "张某最近30天夜间活动频繁，共出现42次，主要集中在22:00—02:00时段。",
    "与王某、李某等3人关联密切，共同出现12次，存在较强的社会关系。",
    "活动地点主要集中在沛县经济开发区及周边区域，特别是某工业园附近。",
    "关联车辆苏C12345多次与张某存在夜间同行，存在共同出行记录。",
  ],
  evidence: [
    { type: "trajectory", title: "轨迹记录", value: 42, unit: "条", summary: "近30天夜间", items: ["活动覆盖经济开发区、工业园等区域"] },
    { type: "companion", title: "同行人员", value: 6, unit: "人", summary: "其中重点关注3人", items: ["与王某共同出现12次"] },
    { type: "vehicle", title: "关联车辆", value: 2, unit: "辆", summary: "苏C12345等", items: ["存在11次轨迹高度重合"] },
    { type: "place", title: "高频地点", value: 5, unit: "个", summary: "主要在工业园周边", items: ["夜间出现频次较高"] },
  ],
  next_steps: "建议进一步核验王某、李某的身份背景及共同活动目的，并结合原始资料复核苏C12345的完整活动轨迹。",
  clues: [
    {
      id: "clue-person-01", type: "person", title: "关联人员线索", headline: "王某与张某共同出现12次", time: "15:33", level: "高", source: "张某夜间活动分析",
      summary: "王某（320322********5678）与张某在最近30天内多次在夜间共同出现，行为轨迹高度重合。",
      discoveries: ["近30天共同出现12次，时空重合度较高。", "主要出现在沛县经济开发区、某工业园、汉城路周边。", "多在22:00—02:00时段共同活动。"],
      evidence: [
        { type: "trajectory", label: "2026-08-15 22:18", content: "两人在某工业园西门附近同时出现，停留约1小时20分钟。" },
        { type: "trajectory", label: "2026-08-21 23:06", content: "两人同时出现在某娱乐场所，停留约2小时。" },
        { type: "trajectory", label: "2026-08-28 00:14", content: "两人在开发区大道交叉口附近高度重合，随后一同前往某KTV。" },
      ],
    },
    {
      id: "clue-vehicle-01", type: "vehicle", title: "关联车辆线索", headline: "苏C12345多次与张某夜间同行", time: "15:33", level: "中", source: "车辆轨迹分析",
      summary: "车辆苏C12345在近30天内有11次与张某轨迹重合，主要出现在工业园周边。",
      discoveries: ["车辆与目标对象轨迹重合11次。", "夜间同行特征明显。"],
      evidence: [{ type: "vehicle", label: "苏C12345", content: "近30天内存在11次轨迹高度重合记录。" }],
    },
    {
      id: "clue-place-01", type: "place", title: "异常地点线索", headline: "频繁出入某工业园区域", time: "15:34", level: "中", source: "场所信息查询",
      summary: "张某近30天内18次出现在沛县经济开发区某工业园，夜间出现频次较高。",
      discoveries: ["工业园区域出现18次。", "活动时间集中于夜间。"],
      evidence: [{ type: "place", label: "某工业园", content: "近30天夜间出现18次。" }],
    },
    {
      id: "clue-route-01", type: "trajectory", title: "异常轨迹线索", headline: "夜间活动时间较为固定", time: "15:34", level: "低", source: "轨迹查询",
      summary: "张某的夜间活动主要集中在22:00—02:00时段，具有明显规律性。",
      discoveries: ["夜间活动时段固定。", "活动区域相对集中。"],
      evidence: [{ type: "trajectory", label: "22:00—02:00", content: "该时段出现频率占夜间活动的68%。" }],
    },
  ],
}

export function parseAnalysisResult(part: Part) {
  if (part.type !== "analysis_result" || !isRecord(part.data)) return
  if (part.data.schema !== "peixian.analysis-result" || part.data.version !== "1.0") return
  if (![part.data.process, part.data.subjects, part.data.conclusions, part.data.evidence, part.data.clues].every(Array.isArray)) return
  return part.data as AnalysisResult
}

function isRecord(value: unknown): value is { [key: string]: Json } {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function evidenceIcon(type: string) {
  if (type === "trajectory") return "route"
  if (type === "companion") return "users"
  if (type === "vehicle") return "car"
  if (type === "place") return "pin"
  return "file"
}

function clueIcon(type: string) {
  if (type === "person") return "users"
  if (type === "vehicle") return "car"
  if (type === "place") return "pin"
  if (type === "trajectory") return "route"
  return "star"
}

function EvidenceCard(props: { item: AnalysisEvidenceCard }) {
  return (
    <div class={"analysis-evidence-card evidence-" + props.item.type}>
      <div class="analysis-evidence-title"><span><Icon name={evidenceIcon(props.item.type)} size={17} /></span>{props.item.title}</div>
      <Show when={props.item.value !== undefined}><strong>{props.item.value}<small>{props.item.unit}</small></strong></Show>
      <Show when={props.item.summary}><p>{props.item.summary}</p></Show>
      <For each={props.item.items?.slice(0, 2)}>{(item) => <small class="analysis-evidence-note">{item}</small>}</For>
    </div>
  )
}

export function AnalysisResultView(props: { result: AnalysisResult }) {
  return (
    <div class="analysis-result">
      <Show when={props.result.intro}><p class="analysis-intro">{props.result.intro}</p></Show>
      <Show when={props.result.process.length}>
        <section class="analysis-section analysis-process">
          <h3><Icon name="skill" size={17} />研判过程</h3>
          <div class="analysis-steps">
            <For each={props.result.process}>{(step, index) => <div class="analysis-step"><span class={"step-state " + step.status}>{step.status === "completed" ? "✓" : index() + 1}</span><strong>{index() + 1}. {step.title}</strong><p>{step.detail}</p><time>{step.time}</time><Status value={step.status} /></div>}</For>
          </div>
        </section>
      </Show>
      <Show when={props.result.subjects.length}>
        <section class="analysis-section">
          <h3><Icon name="users" size={17} />目标对象画像</h3>
          <div class="subject-grid">
            <For each={props.result.subjects}>{(subject) => <article class="subject-card"><div class="subject-name"><span><Icon name="users" size={18} /></span><strong>{subject.name}</strong></div><div class="subject-fields"><For each={subject.fields}>{(field) => <p><span>{field.label}</span><b>{field.value}</b></p>}</For></div><Show when={subject.tags?.length}><div class="subject-tags"><For each={subject.tags}>{(tag) => <span>{tag}</span>}</For></div></Show></article>}</For>
          </div>
        </section>
      </Show>
      <Show when={props.result.conclusions.length}>
        <section class="analysis-section analysis-conclusions"><h3><Icon name="file" size={17} />核心结论</h3><ul><For each={props.result.conclusions}>{(item) => <li>{item}</li>}</For></ul></section>
      </Show>
      <Show when={props.result.evidence.length}>
        <section class="analysis-section"><h3><Icon name="file" size={17} />研判依据</h3><div class="analysis-evidence-grid"><For each={props.result.evidence.slice(0, 4)}>{(item) => <EvidenceCard item={item} />}</For></div></section>
      </Show>
      <Show when={props.result.next_steps}>
        <section class="analysis-next"><h3><Icon name="star" size={17} />建议下一步操作</h3><p>{props.result.next_steps}</p></section>
      </Show>
    </div>
  )
}

export function CluePanel(props: { clues: AnalysisClue[]; onSelect: (clue: AnalysisClue) => void }) {
  return (
    <aside class="clue-panel">
      <div class="clue-panel-head"><div><strong><Icon name="star" size={18} />智能发现线索</strong><small>实时分析 · 自动发现 · {props.clues.length} 条线索</small></div></div>
      <div class="clue-list"><For each={props.clues}>{(clue) => <article class={"clue-card clue-" + clue.type}><div class="clue-card-head"><span><Icon name={clueIcon(clue.type)} size={18} /></span><strong>{clue.title}</strong><time>{clue.time}</time></div><h4>{clue.headline}</h4><p>{clue.summary}</p><button onClick={() => props.onSelect(clue)}>查看详情</button></article>}</For></div>
    </aside>
  )
}

export function ClueDrawer(props: { clue: AnalysisClue; onClose: () => void }) {
  return (
    <div class="clue-drawer-backdrop" onClick={props.onClose}>
      <aside class="clue-drawer" onClick={(event) => event.stopPropagation()}>
        <header><h2>线索详情</h2><button class="icon-button" aria-label="关闭线索详情" onClick={props.onClose}><Icon name="close" /></button></header>
        <div class="clue-drawer-scroll">
          <section class="clue-name-card"><div><span class={"clue-main-icon clue-" + props.clue.type}><Icon name={clueIcon(props.clue.type)} size={22} /></span><div><small>{props.clue.title}</small><h3>{props.clue.headline}</h3></div></div><div class="clue-meta"><Show when={props.clue.level}><span>线索等级：<b>{props.clue.level}</b></span></Show><Show when={props.clue.time}><span>发现时间：{props.clue.time}</span></Show><Show when={props.clue.source}><span>来源任务：{props.clue.source}</span></Show></div></section>
          <section><h3><Icon name="file" size={17} />线索摘要</h3><p>{props.clue.summary}</p></section>
          <section><h3><Icon name="star" size={17} />核心发现</h3><ul><For each={props.clue.discoveries}>{(item) => <li>{item}</li>}</For></ul></section>
          <section><h3><Icon name="file" size={17} />研判依据</h3><div class="clue-evidence-list"><For each={props.clue.evidence}>{(item) => <article><span><Icon name={evidenceIcon(item.type)} size={16} /></span><div><strong>{item.label}</strong><p>{item.content}</p></div></article>}</For></div></section>
        </div>
      </aside>
    </div>
  )
}
