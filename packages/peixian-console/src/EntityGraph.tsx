import { createSignal, For, Show } from "solid-js"
import { Portal } from "solid-js/web"
import RelationshipGraph from "./RelationshipGraph"

// The sample is synthetic. Real graph data must arrive through the versioned server contract.
type EntityNode = { id: string; type: string; label: string; properties: Record<string, string> }
type EntityEdge = { id: string; source: string; target: string; type: string; label: string; directed: boolean; weight?: number }
type EntityGraphData = {
  schema: "peixian.entity-graph"
  version: "1.0"
  nodes: EntityNode[]
  edges: EntityEdge[]
  analysis: { groups: { id: string; label: string; node_ids: string[] }[] }
  meta: { data_revision: string; truncated: boolean; total_nodes: number; total_edges: number }
}

export const sample: EntityGraphData = {
  schema: "peixian.entity-graph",
  version: "1.0",
  nodes: [
    { id: "p-1", type: "person", label: "示例人员甲", properties: { 说明: "完全虚构的演示节点", 分组: "A" } },
    { id: "p-2", type: "person", label: "示例人员乙", properties: { 说明: "完全虚构的演示节点", 分组: "A" } },
    { id: "p-3", type: "person", label: "示例人员丙", properties: { 说明: "完全虚构的演示节点", 分组: "B" } },
    { id: "p-4", type: "person", label: "示例人员丁", properties: { 说明: "完全虚构的演示节点", 分组: "B" } },
    { id: "v-1", type: "vehicle", label: "示例车辆一", properties: { 说明: "非真实车牌", 分组: "A" } },
    { id: "v-2", type: "vehicle", label: "示例车辆二", properties: { 说明: "非真实车牌", 分组: "B" } },
    { id: "l-1", type: "place", label: "示例地点一", properties: { 说明: "非真实地点", 分组: "A" } },
    { id: "l-2", type: "place", label: "示例地点二", properties: { 说明: "非真实地点", 分组: "B" } },
    { id: "e-1", type: "event", label: "示例事件一", properties: { 说明: "非真实事件", 分组: "A" } },
    { id: "e-2", type: "event", label: "示例事件二", properties: { 说明: "非真实事件", 分组: "B" } },
  ],
  edges: [
    { id: "r-1", source: "p-1", target: "p-2", type: "contact", label: "示例关联", directed: false },
    { id: "r-2", source: "p-1", target: "v-1", type: "uses", label: "示例使用", directed: true },
    { id: "r-3", source: "v-1", target: "l-1", type: "appeared", label: "示例出现", directed: true },
    { id: "r-4", source: "p-2", target: "e-1", type: "involved", label: "示例参与", directed: true },
    { id: "r-5", source: "e-1", target: "l-1", type: "occurred", label: "示例发生", directed: true },
    { id: "r-6", source: "p-3", target: "p-4", type: "contact", label: "示例关联", directed: false },
    { id: "r-7", source: "p-3", target: "v-2", type: "uses", label: "示例使用", directed: true },
    { id: "r-8", source: "v-2", target: "l-2", type: "appeared", label: "示例出现", directed: true },
    { id: "r-9", source: "p-4", target: "e-2", type: "involved", label: "示例参与", directed: true },
    { id: "r-10", source: "e-2", target: "l-2", type: "occurred", label: "示例发生", directed: true },
    { id: "r-11", source: "p-2", target: "p-3", type: "contact", label: "示例关联", directed: false },
  ],
  analysis: { groups: [{ id: "a", label: "示例组 A", node_ids: ["p-1", "p-2", "v-1", "l-1", "e-1"] }, { id: "b", label: "示例组 B", node_ids: ["p-3", "p-4", "v-2", "l-2", "e-2"] }] },
  meta: { data_revision: "mock-1", truncated: false, total_nodes: 10, total_edges: 11 },
}

const initialIds = ["p-1", "p-2", "v-1", "l-1"]
export const GraphCanvas = RelationshipGraph

export default function EntityGraphPanel(props: { notice?: string }) {
  const [demo, setDemo] = createSignal(false)
  const [visibleIds, setVisibleIds] = createSignal(initialIds)
  const [filter, setFilter] = createSignal("all")
  const [selected, setSelected] = createSignal<string>()
  const [source, setSource] = createSignal("p-1")
  const [target, setTarget] = createSignal("l-1")
  const [path, setPath] = createSignal<string[]>([])
  const [large, setLarge] = createSignal(false)
  const nodes = () => sample.nodes.filter((node) => visibleIds().includes(node.id) && (filter() === "all" || node.type === filter()))
  const edges = () => sample.edges.filter((edge) => nodes().some((node) => node.id === edge.source) && nodes().some((node) => node.id === edge.target))
  const chosen = () => sample.nodes.find((node) => node.id === selected())
  const highlightPath = () => {
    const queue: { id: string; path: string[] }[] = [{ id: source(), path: [source()] }]
    const visited = new Set<string>()
    while (queue.length) {
      const current = queue.shift()!
      if (current.id === target()) { setPath(current.path); return }
      if (visited.has(current.id)) continue
      visited.add(current.id)
      sample.edges.filter((edge) => edge.source === current.id || edge.target === current.id).forEach((edge) => {
        const next = edge.source === current.id ? edge.target : edge.source
        if (!visited.has(next)) queue.push({ id: next, path: [...current.path, edge.id, next] })
      })
    }
    setPath([])
  }
  return <div class="entity-graph-panel" role="tabpanel" aria-label="实体关系图谱">
    <div class="graph-notice"><strong>暂无真实图谱数据</strong><p>{props.notice ?? "后端图谱接口尚未接入；以下演示与当前会话和案件无关。"}</p></div>
    <Show when={!demo()} fallback={<>
      <div class="graph-demo-banner">示例数据 · 非真实研判结果</div>
      <div class="graph-controls">
        <label>类型筛选<select aria-label="筛选节点类型" value={filter()} onChange={(event) => { setFilter(event.currentTarget.value); setPath([]) }}><option value="all">全部</option><option value="person">人员</option><option value="vehicle">车辆</option><option value="place">地点</option><option value="event">事件</option></select></label>
        <button onClick={() => setLarge(true)}>放大查看</button>
      </div>
      <GraphCanvas nodes={nodes()} edges={edges()} selected={selected()} path={path()} onSelect={setSelected} />
      <p class="graph-help">可拖动、滚轮缩放，点击节点查看详情。</p>
      <Show when={chosen()}>{(node) => <div class="graph-detail"><strong>{node().label}</strong><small>{node().type} · 示例节点</small><For each={Object.entries(node().properties)}>{([key, value]) => <p>{key}：{value}</p>}</For></div>}</Show>
      <div class="graph-path"><strong>示例路径分析</strong><label>起点<select aria-label="路径起点" value={source()} onChange={(event) => setSource(event.currentTarget.value)}><For each={sample.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><label>终点<select aria-label="路径终点" value={target()} onChange={(event) => setTarget(event.currentTarget.value)}><For each={sample.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><button onClick={() => { setVisibleIds(sample.nodes.map((node) => node.id)); setFilter("all"); highlightPath() }}>高亮路径</button><Show when={path().length}><small>仅在示例网络中计算，已高亮 {Math.ceil(path().length / 2)} 个节点。</small></Show></div>
      <button class="graph-exit" onClick={() => { setDemo(false); setLarge(false) }}>退出示例</button>
      <Show when={large()}><Portal><div class="graph-overlay" role="dialog" aria-modal="true" aria-label="实体关系图谱示例大视图"><div><header><strong>实体关系图谱 · 示例数据</strong><button onClick={() => setLarge(false)} aria-label="关闭图谱大视图">关闭</button></header><GraphCanvas large nodes={nodes()} edges={edges()} selected={selected()} path={path()} onSelect={setSelected} /><Show when={chosen()}>{(node) => <p>已选：{node().label}。{node().properties.说明}</p>}</Show><p>仅供交互演示；不代表当前会话的事实或推断。</p></div></div></Portal></Show>
    </>}>
      <button class="graph-start" onClick={() => setDemo(true)}>查看示例</button>
    </Show>
  </div>
}
