import { createEffect, createSignal, For, onCleanup, onMount, Show } from "solid-js"
import { Portal } from "solid-js/web"

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

const sample: EntityGraphData = {
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

const colors: Record<string, string> = {
  person: "#cf4d5d", vehicle: "#2874c8", place: "#dc8936", time: "#8293a8",
  case: "#184c86", event: "#184c86", record: "#398b91", other: "#647e9d",
}
const entityKind = (type: string) => {
  const value = type.toLowerCase()
  if (/person|people|人员|人物|嫌疑人/.test(value)) return "person"
  if (/vehicle|car|车辆|车牌/.test(value)) return "vehicle"
  if (/place|location|address|地点|地址|场所/.test(value)) return "place"
  if (/time|date|timestamp|时间|日期/.test(value)) return "time"
  if (/case|event|案件|事件/.test(value)) return "case"
  if (/record|document|file|记录|文书|资料/.test(value)) return "record"
  return "other"
}
const relationTone = (edge: EntityEdge) => {
  const value = (edge.type + " " + edge.label).toLowerCase()
  if (/abnormal|anomaly|异常/.test(value)) return "#c75460"
  if (/important|key|重点|关键/.test(value)) return "#315f9a"
  return "#a7c3de"
}
const initialIds = ["p-1", "p-2", "v-1", "l-1"]

export function GraphCanvas(props: { nodes: EntityNode[]; edges: EntityEdge[]; selected?: string; path: string[]; onSelect: (id: string) => void; large?: boolean }) {
  let container!: HTMLDivElement
  let stage!: HTMLDivElement
  let graph: import("@antv/g6").Graph | undefined
  const [loadError, setLoadError] = createSignal(false)
  const [hoveredEdge, setHoveredEdge] = createSignal<string>()
  const [hoveredNode, setHoveredNode] = createSignal<string>()
  const [pointer, setPointer] = createSignal({ x: 120, y: 80 })
  const relation = () => props.edges.find((edge) => edge.id === hoveredEdge())
  const nodeInfo = () => props.nodes.find((node) => node.id === hoveredNode())
  const label = (id: string) => props.nodes.find((node) => node.id === id)?.label ?? id
  const degree = (id: string) => props.edges.filter((edge) => edge.source === id || edge.target === id).length
  const fitGraph = async () => {
    if (!graph || !props.nodes.length) return
    await graph.fitView({ when: "always" }, false)
    if (graph.getZoom() > 1.2) await graph.zoomTo(1.2, false)
  }
  const layout = () => {
    const ids = new Set(props.nodes.map((node) => node.id))
    const adjacency = new Map(props.nodes.map((node) => [node.id, new Set<string>()]))
    props.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).forEach((edge) => {
      adjacency.get(edge.source)?.add(edge.target)
      adjacency.get(edge.target)?.add(edge.source)
    })
    const unseen = new Set(ids)
    const groups: string[][] = []
    while (unseen.size) {
      const root = [...unseen].sort((a, b) => (adjacency.get(b)?.size ?? 0) - (adjacency.get(a)?.size ?? 0) || a.localeCompare(b))[0]
      const queue = [root]
      const group: string[] = []
      unseen.delete(root)
      while (queue.length) {
        const id = queue.shift()!
        group.push(id)
        ;[...(adjacency.get(id) ?? [])].sort((a, b) => (adjacency.get(b)?.size ?? 0) - (adjacency.get(a)?.size ?? 0) || a.localeCompare(b)).forEach((next) => {
          if (!unseen.delete(next)) return
          queue.push(next)
        })
      }
      groups.push(group)
    }
    const positions = new Map<string, { x: number; y: number }>()
    const gapX = 76, gapY = 68
    let row = 0
    groups.sort((a, b) => b.length - a.length).forEach((group) => {
      const columns = Math.max(1, Math.ceil(Math.sqrt(group.length * 1.3)))
      group.forEach((id, index) => {
        const column = index % columns
        positions.set(id, { x: (index % (columns * 2) < columns ? column : columns - column - 1) * gapX, y: (row + Math.floor(index / columns)) * gapY })
      })
      row += Math.ceil(group.length / columns) + 1
    })
    return positions
  }
  const renderGraph = async () => {
    if (!graph) return
    const positions = layout()
    graph.resize(stage.clientWidth || 280, stage.clientHeight || 310)
    graph.setData({
      nodes: props.nodes.map((node) => ({
        id: node.id,
        style: {
          x: positions.get(node.id)?.x ?? 0,
          y: positions.get(node.id)?.y ?? 0,
          size: Math.min(42, 24 + degree(node.id) * 2.5),
          fill: colors[entityKind(node.type)],
          stroke: "#fff",
          lineWidth: 2,
          labelText: node.label,
          labelFill: "#1d4168",
          labelFontSize: 11,
          labelPlacement: "bottom",
          labelOffsetY: 5,
        },
      })),
      edges: props.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        style: { stroke: relationTone(edge), lineWidth: 1 },
      })),
    })
    await graph.render()
    await fitGraph()
  }
  const updateHighlight = () => {
    if (!graph) return
    const focus = hoveredNode() ?? props.selected
    const near = new Set(focus ? [focus] : [])
    props.edges.filter((edge) => edge.source === focus || edge.target === focus).forEach((edge) => { near.add(edge.source); near.add(edge.target) })
    graph.updateNodeData(props.nodes.map((node) => ({ id: node.id, style: {
      opacity: focus && !near.has(node.id) ? 0.26 : 1,
      stroke: props.path.includes(node.id) ? "#e9ae2e" : focus === node.id ? "#173e73" : "#fff",
      lineWidth: props.path.includes(node.id) ? 4 : focus === node.id ? 3 : 2,
    } })))
    graph.updateEdgeData(props.edges.map((edge) => ({ id: edge.id, style: {
      opacity: focus && edge.source !== focus && edge.target !== focus ? 0.2 : 1,
      stroke: props.path.includes(edge.id) ? "#d99d20" : hoveredEdge() === edge.id || focus && (edge.source === focus || edge.target === focus) ? "#315f9a" : relationTone(edge),
      lineWidth: props.path.includes(edge.id) ? 3 : hoveredEdge() === edge.id || focus && (edge.source === focus || edge.target === focus) ? 2 : 1,
    } })))
    void graph.render()
  }
  onMount(() => {
    let disposed = false
    void import("@antv/g6").then(({ Graph }) => {
      if (disposed) return
      graph = new Graph({ container: stage, width: stage.clientWidth || 280, height: stage.clientHeight || 310, behaviors: ["drag-canvas", "zoom-canvas", "drag-element"] })
      graph.on("node:click", (event) => {
        if ("target" in event && event.target && typeof event.target === "object" && "id" in event.target) props.onSelect(String(event.target.id))
      })
      graph.on("node:pointerenter", (event) => {
        if ("target" in event && event.target && typeof event.target === "object" && "id" in event.target) setHoveredNode(String(event.target.id))
      })
      graph.on("node:pointerleave", () => setHoveredNode(undefined))
      graph.on("edge:pointerenter", (event) => {
        if ("target" in event && event.target && typeof event.target === "object" && "id" in event.target) setHoveredEdge(String(event.target.id))
      })
      graph.on("edge:pointerleave", () => setHoveredEdge(undefined))
      void renderGraph().then(updateHighlight)
    }).catch(() => setLoadError(true))
    const observer = new ResizeObserver(() => {
      if (!graph) return
      graph.resize(stage.clientWidth || 280, stage.clientHeight || 310)
      void fitGraph()
    })
    observer.observe(stage)
    onCleanup(() => { disposed = true; observer.disconnect(); graph?.destroy() })
  })
  createEffect(() => { props.nodes; props.edges; void renderGraph().then(updateHighlight) })
  createEffect(() => { props.selected; props.path; hoveredNode(); hoveredEdge(); updateHighlight() })
  return <div class={props.large ? "entity-graph-canvas large" : "entity-graph-canvas"} ref={container} onPointerMove={(event) => {
    if (!hoveredNode() && !hoveredEdge()) return
    const bounds = container.getBoundingClientRect()
    setPointer({ x: Math.max(105, Math.min(bounds.width - 105, event.clientX - bounds.left)), y: Math.max(62, event.clientY - bounds.top) })
  }}>
    <div class="entity-graph-stage" ref={stage} />
    <button class="graph-fit-view" type="button" onClick={() => void fitGraph()} aria-label="适配图谱视图">适配视图</button>
    <Show when={loadError()}><p class="graph-load-error">图谱组件加载失败，请刷新页面重试。</p></Show>
    <Show when={relation()}>{(edge) => <div class="graph-relation-tooltip" style={{ left: pointer().x + "px", top: pointer().y + "px" }} role="status"><strong>{label(edge().source)} {edge().directed ? "→" : "—"} {label(edge().target)}</strong><span>关系：{edge().label || edge().type}</span></div>}</Show>
    <Show when={nodeInfo()}>{(node) => <div class="graph-relation-tooltip" style={{ left: pointer().x + "px", top: pointer().y + "px" }} role="status"><strong>{node().label}</strong><span>{node().type} · {degree(node().id)} 条关系</span></div>}</Show>
  </div>
}

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
  const expand = () => {
    if (!selected()) return
    const neighbors = sample.edges.filter((edge) => edge.source === selected() || edge.target === selected()).flatMap((edge) => [edge.source, edge.target])
    setVisibleIds((current) => [...new Set([...current, ...neighbors])])
  }
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
      <p class="graph-help">可拖动、滚轮缩放，点击节点查看详情与展开关系。</p>
      <Show when={chosen()}>{(node) => <div class="graph-detail"><strong>{node().label}</strong><small>{node().type} · 示例节点</small><For each={Object.entries(node().properties)}>{([key, value]) => <p>{key}：{value}</p>}</For><button onClick={expand}>展开相邻关系</button></div>}</Show>
      <div class="graph-path"><strong>示例路径分析</strong><label>起点<select aria-label="路径起点" value={source()} onChange={(event) => setSource(event.currentTarget.value)}><For each={sample.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><label>终点<select aria-label="路径终点" value={target()} onChange={(event) => setTarget(event.currentTarget.value)}><For each={sample.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><button onClick={() => { setVisibleIds(sample.nodes.map((node) => node.id)); setFilter("all"); highlightPath() }}>高亮路径</button><Show when={path().length}><small>仅在示例网络中计算，已高亮 {Math.ceil(path().length / 2)} 个节点。</small></Show></div>
      <button class="graph-exit" onClick={() => { setDemo(false); setLarge(false) }}>退出示例</button>
      <Show when={large()}><Portal><div class="graph-overlay" role="dialog" aria-modal="true" aria-label="实体关系图谱示例大视图"><div><header><strong>实体关系图谱 · 示例数据</strong><button onClick={() => setLarge(false)} aria-label="关闭图谱大视图">关闭</button></header><GraphCanvas large nodes={nodes()} edges={edges()} selected={selected()} path={path()} onSelect={setSelected} /><Show when={chosen()}>{(node) => <p>已选：{node().label}。{node().properties.说明}</p>}</Show><p>仅供交互演示；不代表当前会话的事实或推断。</p></div></div></Portal></Show>
    </>}>
      <button class="graph-start" onClick={() => setDemo(true)}>查看示例</button>
    </Show>
  </div>
}
