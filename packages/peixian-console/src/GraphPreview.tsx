import { createMemo, createSignal, For, Show } from "solid-js"
import { sample } from "./EntityGraph"
import RelationshipGraph from "./RelationshipGraph"

export default function GraphPreview() {
  const [filter, setFilter] = createSignal("all")
  const [selected, setSelected] = createSignal<string>()
  const [source, setSource] = createSignal(sample.nodes[0].id)
  const [target, setTarget] = createSignal(sample.nodes[6].id)
  const [path, setPath] = createSignal<string[]>([])
  const nodes = createMemo(() => sample.nodes.filter((node) => filter() === "all" || node.type === filter()))
  const edges = createMemo(() => {
    const ids = new Set(nodes().map((node) => node.id))
    return sample.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target))
  })
  const chosen = createMemo(() => sample.nodes.find((node) => node.id === selected()))
  const highlightPath = () => {
    const queue: { id: string; path: string[] }[] = [{ id: source(), path: [source()] }]
    const visited = new Set<string>()
    while (queue.length) {
      const current = queue.shift()!
      if (current.id === target()) { setPath(current.path); return }
      if (visited.has(current.id)) continue
      visited.add(current.id)
      edges().filter((edge) => edge.source === current.id || edge.target === current.id).forEach((edge) => {
        const next = edge.source === current.id ? edge.target : edge.source
        if (!visited.has(next)) queue.push({ id: next, path: [...current.path, edge.id, next] })
      })
    }
    setPath([])
  }
  return <main class="business-shell graph-preview-page">
    <header><div><small>开发预览 · 虚构示例数据</small><h1>实体关系图谱</h1></div><p>可悬停、点击、拖拽节点，滚轮缩放；“适配视图”位于画布右上角。</p></header>
    <section class="entity-graph-panel">
      <div class="graph-controls"><label>类型筛选<select aria-label="筛选节点类型" value={filter()} onChange={(event) => { setFilter(event.currentTarget.value); setPath([]); const first = sample.nodes.find((node) => event.currentTarget.value === "all" || node.type === event.currentTarget.value)?.id; if (first) { setSource(first); setTarget(first) } }}><option value="all">全部</option><For each={[...new Set(sample.nodes.map((node) => node.type))]}>{(type) => <option value={type}>{type}</option>}</For></select></label></div>
      <RelationshipGraph nodes={nodes()} edges={edges()} selected={selected()} path={path()} onSelect={setSelected} large />
      <Show when={chosen()}>{(node) => <div class="graph-detail"><strong>{node().label}</strong><small>{node().type} · 示例实体</small><For each={Object.entries(node().properties)}>{([key, value]) => <p>{key}：{value}</p>}</For></div>}</Show>
      <div class="graph-path graph-path-card"><strong>来源路径分析</strong><div class="graph-path-fields"><label>起点<select aria-label="路径起点" value={source()} onChange={(event) => setSource(event.currentTarget.value)}><For each={nodes()}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><label>终点<select aria-label="路径终点" value={target()} onChange={(event) => setTarget(event.currentTarget.value)}><For each={nodes()}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label></div><button type="button" onClick={highlightPath}>高亮路径</button></div>
    </section>
  </main>
}
