import { createEffect, createSignal, For, onCleanup, onMount, Show, untrack } from "solid-js"

export type RelationshipNode = {
  id: string
  type: string
  label: string
  properties: Record<string, string | number | boolean | null>
  evidence_refs?: { id: string; type: string; label: string }[]
}
export type RelationshipEdge = { id: string; source: string; target: string; type: string; label: string; directed: boolean; weight?: number }

// Formal entity artwork can replace icon values without changing layout or interaction.
const appearance = {
  core: { fill: "#1769d2", icon: null },
  person: { fill: "#d85a68", icon: null },
  company: { fill: "#e8963c", icon: null },
  vehicle: { fill: "#39a66e", icon: null },
  place: { fill: "#9364c8", icon: null },
  account: { fill: "#27a7a2", icon: null },
  contract: { fill: "#746cce", icon: null },
  case: { fill: "#244b82", icon: null },
  unknown: { fill: "#7894ad", icon: null },
}

function entityKind(type: string) {
  const value = type.toLowerCase()
  if (/person|people|人员|人物|嫌疑人/.test(value)) return "person"
  if (/company|enterprise|organization|企业|公司|单位/.test(value)) return "company"
  if (/vehicle|car|车辆|车牌/.test(value)) return "vehicle"
  if (/place|location|address|地点|地址|场所/.test(value)) return "place"
  if (/account|bank|资金|账户|账号/.test(value)) return "account"
  if (/contract|协议|合同/.test(value)) return "contract"
  if (/case|event|案件|事件/.test(value)) return "case"
  return "unknown"
}

export default function RelationshipGraph(props: {
  nodes: RelationshipNode[]
  edges: RelationshipEdge[]
  selected?: string
  path: string[]
  onSelect: (id: string) => void
  large?: boolean
}) {
  let container!: HTMLDivElement
  let stage!: HTMLDivElement
  let graph: import("@antv/g6").Graph | undefined
  let disposed = false
  let drawn = false
  let signature = ""
  let width = 0
  let height = 0
  let queue = Promise.resolve()
  const positions = new Map<string, { x: number; y: number }>()
  const [loadError, setLoadError] = createSignal(false)
  const [hovered, setHovered] = createSignal<string>()
  const [pointer, setPointer] = createSignal({ x: 160, y: 90 })
  const nodeInfo = () => props.nodes.find((node) => node.id === hovered())
  const degree = (id: string, edges: RelationshipEdge[]) => edges.filter((edge) => edge.source === id || edge.target === id).length
  const coreID = (nodes: RelationshipNode[], edges: RelationshipEdge[]) =>
    [...nodes].sort((a, b) => Number(entityKind(b.type) === "person") - Number(entityKind(a.type) === "person") || degree(b.id, edges) - degree(a.id, edges))[0]?.id

  const fitGraph = async () => {
    if (!graph || !props.nodes.length) return
    await graph.fitView({ when: "always" }, false)
    if (graph.getZoom() > 1.15) await graph.zoomTo(1.15, false)
  }

  const highlight = async () => {
    if (!graph || !drawn || disposed) return
    const path = new Set(props.path)
    const focus = hovered() ?? props.selected
    const neighbors = new Set(focus ? [focus] : [])
    props.edges.filter((edge) => edge.source === focus || edge.target === focus).forEach((edge) => {
      neighbors.add(edge.source)
      neighbors.add(edge.target)
    })
    const core = coreID(props.nodes, props.edges)
    graph.updateNodeData(props.nodes.map((node) => ({ id: node.id, style: {
      size: node.id === core ? hovered() === node.id ? 49 : 46 : hovered() === node.id ? 39 : 35,
      opacity: path.size ? path.has(node.id) ? 1 : focus && neighbors.has(node.id) ? 0.55 : 0.2 : focus && !neighbors.has(node.id) ? 0.24 : 1,
      stroke: path.has(node.id) ? "#e6a328" : focus === node.id ? "#123e75" : "#ffffff",
      lineWidth: path.has(node.id) ? 4 : focus === node.id ? 3 : 2,
    } })))
    graph.updateEdgeData(props.edges.map((edge) => ({ id: edge.id, style: {
      opacity: path.size ? path.has(edge.id) ? 1 : focus && (edge.source === focus || edge.target === focus) ? 0.55 : 0.13 : focus && edge.source !== focus && edge.target !== focus ? 0.15 : 1,
      stroke: path.has(edge.id) ? "#dfa328" : focus && (edge.source === focus || edge.target === focus) ? "#397ab8" : "#b7c9dc",
      lineWidth: path.has(edge.id) ? 3 : focus && (edge.source === focus || edge.target === focus) ? 2 : 1,
      endArrow: path.has(edge.id) && edge.directed,
      endArrowType: "triangle" as const,
      endArrowSize: 8,
    } })))
    await graph.draw()
  }

  const drawData = async (nodes: RelationshipNode[], edges: RelationshipEdge[]) => {
    if (!graph || disposed) return
    const next = JSON.stringify({ nodes, edges })
    if (next === signature) return
    signature = next
    graph.getNodeData().forEach((node) => {
      if (typeof node.style?.x === "number" && typeof node.style.y === "number") positions.set(node.id, { x: node.style.x, y: node.style.y })
    })
    const core = coreID(nodes, edges)
    const center = { x: (stage.clientWidth || 280) / 2, y: (stage.clientHeight || 310) / 2 }
    graph.setData({
      nodes: nodes.map((node, index) => {
        const neighbor = edges.find((edge) => edge.source === node.id && positions.has(edge.target) || edge.target === node.id && positions.has(edge.source))
        const near = neighbor && positions.get(neighbor.source === node.id ? neighbor.target : neighbor.source)
        const angle = index * 2.39996
        const position = positions.get(node.id) ?? (node.id === core ? center : { x: (near?.x ?? center.x) + Math.cos(angle) * 86, y: (near?.y ?? center.y) + Math.sin(angle) * 78 })
        const kind = node.id === core ? "core" : entityKind(node.type)
        return { id: node.id, style: {
          x: position.x, y: position.y,
          size: node.id === core ? 46 : 35,
          fill: appearance[kind].fill,
          stroke: "#ffffff", lineWidth: 2,
          shadowColor: "#1c477044", shadowBlur: 10,
          labelText: node.label, labelFill: "#244666", labelFontSize: 11,
          labelPlacement: "bottom" as const, labelOffsetY: 8,
        } }
      }),
      edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, style: { stroke: "#b7c9dc", lineWidth: 1 } })),
    })
    if (!drawn) {
      await graph.render()
      if (disposed) return
      graph.setLayout([])
      drawn = true
      await fitGraph()
    } else await graph.draw()
    await highlight()
  }

  const schedule = (task: () => Promise<void>) => {
    queue = queue.then(task).catch(() => { setLoadError(true) })
  }

  onMount(() => {
    void import("@antv/g6").then(({ Graph }) => {
      if (disposed) return
      width = stage.clientWidth || 280
      height = stage.clientHeight || 310
      graph = new Graph({
        container: stage, width, height,
        layout: { type: "force-atlas2", preventOverlap: true, nodeSize: 48, nodeSpacing: 24, iterations: 180 },
        behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
      })
      graph.on("node:click", (event) => {
        if ("target" in event && event.target && typeof event.target === "object" && "id" in event.target) props.onSelect(String(event.target.id))
      })
      graph.on("node:pointerenter", (event) => {
        if ("target" in event && event.target && typeof event.target === "object" && "id" in event.target) setHovered(String(event.target.id))
      })
      graph.on("node:pointerleave", () => setHovered(undefined))
      schedule(() => drawData(props.nodes, props.edges))
    }).catch(() => setLoadError(true))
    const observer = new ResizeObserver(() => {
      if (!graph || disposed) return
      const nextWidth = stage.clientWidth || 280
      const nextHeight = stage.clientHeight || 310
      if (nextWidth === width && nextHeight === height) return
      width = nextWidth
      height = nextHeight
      graph.resize(width, height)
    })
    observer.observe(stage)
    onCleanup(() => { disposed = true; observer.disconnect(); graph?.destroy() })
  })

  createEffect(() => {
    const nodes = props.nodes
    const edges = props.edges
    untrack(() => schedule(() => drawData(nodes, edges)))
  })
  createEffect(() => {
    props.selected
    props.path
    hovered()
    untrack(() => schedule(highlight))
  })

  return <div class={props.large ? "entity-graph-canvas large" : "entity-graph-canvas"} ref={container} onPointerLeave={() => setHovered(undefined)} onPointerMove={(event) => {
    if (!hovered()) return
    const bounds = container.getBoundingClientRect()
    setPointer({ x: Math.max(8, Math.min(bounds.width - 260, event.clientX - bounds.left + 20)), y: Math.max(8, Math.min(bounds.height - 150, event.clientY - bounds.top + 18)) })
  }}>
    <div class="entity-graph-stage" ref={stage} />
    <button class="graph-fit-view" type="button" onClick={() => void fitGraph()} aria-label="适配图谱视图">适配视图</button>
    <Show when={loadError()}><p class="graph-load-error">图谱组件加载失败，请刷新页面重试。</p></Show>
    <Show when={nodeInfo()}>{(node) => <div class="graph-entity-card" style={{ left: pointer().x + "px", top: pointer().y + "px" }} role="status">
      <strong>{node().label}</strong>
      <span>实体类型：{node().type}</span>
      <span>实体名称：{node().label}</span>
      <Show when={node().evidence_refs?.length}><span>来源：{node().evidence_refs!.map((item) => item.label || item.id).join("、")}</span></Show>
      <For each={Object.entries(node().properties).filter(([key, value]) => value !== null && value !== "" && !["实体类型", "实体名称", "来源"].includes(key))}>{([key, value]) => <span>{key}：{String(value)}</span>}</For>
    </div>}</Show>
  </div>
}
