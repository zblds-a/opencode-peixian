import { createEffect, createMemo, createSignal, For, onCleanup, Show } from "solid-js"
import { Portal } from "solid-js/web"
import { api, ApiError } from "./api"
import { GraphCanvas } from "./EntityGraph"

type GraphNode = { id: string; type: string; label: string; properties: Record<string, string | number | boolean | null>; evidence_refs?: { id: string; type: string; label: string }[] }
type GraphEdge = { id: string; source: string; target: string; type: string; label: string; directed: boolean }
type GraphPage = {
  schema: "peixian.entity-graph"
  version: "1.0"
  graph_id: string
  status: "ready" | "partial" | "pending" | "unavailable"
  nodes: GraphNode[]
  edges: GraphEdge[]
  meta: { mode?: "snapshot" | "delta"; data_revision: string; truncated: boolean; total_nodes: number; total_edges: number; next_cursor?: string | null; truncation_reason?: string }
}
type GraphEntry = { id: string; title: string; status: "ready" | "partial" | "pending" | "empty" | "unavailable"; data_revision: string }
type PathResult = { found: boolean; paths: { node_ids: string[]; edge_ids: string[] }[]; data_revision: string; truncated: boolean }

export default function RealEntityGraph(props: { sessionID?: string; runID?: string; runStatus?: string }) {
  const sessionID = createMemo(() => props.sessionID)
  const runID = createMemo(() => props.runID)
  const [epoch, setEpoch] = createSignal(0)
  const [refresh, setRefresh] = createSignal(0)
  const [entry, setEntry] = createSignal<GraphEntry>()
  const [page, setPage] = createSignal<GraphPage>()
  const [status, setStatus] = createSignal("正在读取当前执行的可信图谱…")
  const [filter, setFilter] = createSignal("all")
  const [selected, setSelected] = createSignal<string>()
  const [detail, setDetail] = createSignal<GraphNode>()
  const [source, setSource] = createSignal("")
  const [target, setTarget] = createSignal("")
  const [path, setPath] = createSignal<string[]>([])
  const [large, setLarge] = createSignal(false)
  const [working, setWorking] = createSignal(false)
  const pending = new Set<AbortController>()
  const request = async <T,>(path: string, options: RequestInit = {}) => {
    const controller = new AbortController()
    pending.add(controller)
    try { return await api<T>(path, { ...options, signal: controller.signal }) }
    finally { pending.delete(controller) }
  }
  onCleanup(() => pending.forEach((controller) => controller.abort()))
  const base = () => "/sessions/" + encodeURIComponent(sessionID() ?? "") + "/runs/" + encodeURIComponent(runID() ?? "") + "/graphs"
  const nodes = () => (page()?.nodes ?? []).filter((node) => filter() === "all" || node.type === filter())
  const edges = () => (page()?.edges ?? []).filter((edge) => nodes().some((node) => node.id === edge.source) && nodes().some((node) => node.id === edge.target))
  const canvasNodes = () => nodes().map((node) => ({
    id: node.id, label: node.label,
    type: node.type,
    properties: {},
  }))
  const graphBase = () => base() + "/" + encodeURIComponent(entry()?.id ?? "")
  const resetRevision = () => {
    setPage(undefined)
    setEntry(undefined)
    setSelected(undefined)
    setDetail(undefined)
    setPath([])
    setStatus("图谱数据已更新，正在重新读取当前修订…")
    setEpoch((value) => value + 1)
  }
  const fail = (cause: unknown) => {
    if (cause instanceof ApiError && cause.status === 409) { resetRevision(); return }
    setStatus(cause instanceof ApiError ? cause.message : "图谱读取未完成，请重试。")
  }
  createEffect(() => {
    const sid = sessionID(), rid = runID(), version = epoch()
    props.runStatus
    refresh()
    setEntry(undefined)
    setPage(undefined)
    setSelected(undefined)
    setDetail(undefined)
    setPath([])
    if (!sid || !rid) { setStatus("当前执行尚无可信图谱。"); return }
    const controller = new AbortController()
    setStatus("正在读取当前执行的可信图谱…")
    void api<{ items: GraphEntry[] }>(base() + "?page=1&page_size=20", { signal: controller.signal }).then(async (directory) => {
      if (controller.signal.aborted || version !== epoch()) return
      const graph = directory.items.find((item) => item.status === "ready" || item.status === "partial")
      if (!graph) {
        setStatus(directory.items.some((item) => item.status === "pending") ? "可信图谱仍在生成，请稍后刷新。" : directory.items.some((item) => item.status === "unavailable") ? "当前结果缺少可投影的可信来源。" : directory.items.some((item) => item.status === "empty") ? "本轮没有可投影的来源关系。" : "当前执行没有可展示的可信关系图。")
        return
      }
      setEntry(graph)
      const snapshot = await api<GraphPage>(base() + "/" + encodeURIComponent(graph.id) + "?node_limit=80&edge_limit=160", { signal: controller.signal })
      if (controller.signal.aborted || version !== epoch()) return
      setPage(snapshot)
      setSource(snapshot.nodes[0]?.id ?? "")
      setTarget(snapshot.nodes[1]?.id ?? snapshot.nodes[0]?.id ?? "")
      setStatus(snapshot.nodes.length === 0 ? "本轮没有可投影的来源关系。" : snapshot.status === "partial" ? "仅显示已核对的部分来源关系。" : "")
    }).catch((cause) => {
      if (controller.signal.aborted) return
      if (cause instanceof ApiError && cause.status === 404) { setStatus("当前执行的图谱资源不存在，或当前账号无权查看。"); return }
      fail(cause)
    })
    onCleanup(() => { controller.abort(); pending.forEach((request) => request.abort()) })
  })
  const merge = (delta: GraphPage) => {
    const current = page()
    if (!current || delta.meta.data_revision !== current.meta.data_revision) { resetRevision(); return }
    setPage({ ...delta, meta: delta.meta.mode === "delta" ? { ...delta.meta, next_cursor: current.meta.next_cursor } : delta.meta,
      nodes: [...new Map([...current.nodes, ...delta.nodes].map((node) => [node.id, node])).values()],
      edges: [...new Map([...current.edges, ...delta.edges].map((edge) => [edge.id, edge])).values()] })
  }
  const loadMore = async () => {
    const cursor = page()?.meta.next_cursor
    if (!cursor || working()) return
    setWorking(true)
    try { merge(await request<GraphPage>(base() + "/" + encodeURIComponent(entry()!.id) + "?node_limit=80&edge_limit=160&cursor=" + encodeURIComponent(cursor))) }
    catch (cause) { fail(cause) }
    finally { setWorking(false) }
  }
  const selectNode = async (id: string) => {
    setSelected(id)
    setDetail(undefined)
    const revision = page()?.meta.data_revision
    if (!revision) return
    try {
      const result = await request<{ data_revision: string; node: GraphNode }>(graphBase() + "/nodes/" + encodeURIComponent(id) + "?data_revision=" + encodeURIComponent(revision))
      if (selected() === id && page()?.meta.data_revision === result.data_revision) setDetail(result.node)
    } catch (cause) { fail(cause) }
  }
  const expand = async () => {
    const id = selected(), revision = page()?.meta.data_revision
    if (!id || !revision || working()) return
    setWorking(true)
    try { merge(await request<GraphPage>(graphBase() + "/expand", { method: "POST", body: JSON.stringify({ node_id: id, depth: 1, relation_types: [], node_limit: 80, edge_limit: 160, cursor: null, data_revision: revision }) })) }
    catch (cause) { fail(cause) }
    finally { setWorking(false) }
  }
  const findPath = async () => {
    const revision = page()?.meta.data_revision
    if (!revision || !source() || !target() || working()) return
    setWorking(true)
    try {
      const result = await request<PathResult>(graphBase() + "/paths", { method: "POST", body: JSON.stringify({ source_id: source(), target_id: target(), max_hops: 4, data_revision: revision }) })
      if (result.data_revision !== page()?.meta.data_revision) { resetRevision(); return }
      setPath(result.found ? [...result.paths[0].node_ids, ...result.paths[0].edge_ids] : [])
      setStatus(result.found ? "已显示一条最短来源路径；关系连接不代表因果判断。" : "这两个节点之间没有已核对的来源路径。")
    } catch (cause) { fail(cause) }
    finally { setWorking(false) }
  }
  return <Show when={page()} fallback={<div class="entity-graph-panel" role="tabpanel" aria-label="实体关系图谱"><div class="graph-notice"><strong>暂无可信关系图谱</strong><p>{status()}</p></div><button class="graph-start" onClick={() => setRefresh((value) => value + 1)}>刷新图谱</button></div>}>
    <div class="entity-graph-panel" role="tabpanel" aria-label="实体关系图谱">
      <div class="graph-notice"><strong>{entry()?.title || "可信实体关系图谱"}</strong><p>{status() || "图中仅包含当前执行已批准的来源关系，不表示因果或风险判断。"} {page()?.meta.truncated ? "数据不完整，可继续加载或核对来源。" : ""}</p></div>
      <div class="graph-controls"><label>类型筛选<select aria-label="筛选节点类型" value={filter()} onChange={(event) => setFilter(event.currentTarget.value)}><option value="all">全部</option><For each={[...new Set(page()?.nodes.map((node) => node.type) ?? [])]}>{(type) => <option value={type}>{type}</option>}</For></select></label><button onClick={() => setLarge(true)}>放大查看</button></div>
      <GraphCanvas nodes={canvasNodes()} edges={edges()} selected={selected()} path={path()} onSelect={(id) => void selectNode(id)} />
      <p class="graph-help">可拖动、滚轮缩放，点击节点核对脱敏详情与来源。</p>
      <Show when={page()?.meta.next_cursor}><button class="graph-start" disabled={working()} onClick={() => void loadMore()}>加载更多关系</button></Show>
      <Show when={selected()}><div class="graph-detail"><strong>{detail()?.label ?? nodes().find((node) => node.id === selected())?.label}</strong><small>{detail()?.type ?? "节点"} · 已核对来源</small><For each={Object.entries(detail()?.properties ?? {})}>{([key, value]) => <p>{key}：{String(value)}</p>}</For><small>来源记录 {detail()?.evidence_refs?.length ?? 0} 项</small><button disabled={working()} onClick={() => void expand()}>展开相邻关系</button></div></Show>
      <div class="graph-path"><strong>来源路径分析</strong><label>起点<select aria-label="路径起点" value={source()} onChange={(event) => setSource(event.currentTarget.value)}><For each={page()?.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><label>终点<select aria-label="路径终点" value={target()} onChange={(event) => setTarget(event.currentTarget.value)}><For each={page()?.nodes}>{(node) => <option value={node.id}>{node.label}</option>}</For></select></label><button disabled={working()} onClick={() => void findPath()}>高亮路径</button></div>
      <Show when={large()}><Portal><div class="graph-overlay" role="dialog" aria-modal="true" aria-label="可信实体关系图谱大视图"><div><header><strong>{entry()?.title || "可信实体关系图谱"}</strong><button onClick={() => setLarge(false)} aria-label="关闭图谱大视图">关闭</button></header><GraphCanvas large nodes={canvasNodes()} edges={edges()} selected={selected()} path={path()} onSelect={(id) => void selectNode(id)} /><p>仅显示当前执行已批准的来源关系；不代表因果或风险判断。</p></div></div></Portal></Show>
    </div>
  </Show>
}
