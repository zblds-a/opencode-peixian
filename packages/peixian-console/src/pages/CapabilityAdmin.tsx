import { createEffect, createSignal, For, Show } from "solid-js"
import { list, patch, post, safeMessage } from "../api"
import { Button, Empty, ErrorLine, Field, Modal, PageHead, Status } from "../components"
import { useConsole } from "../context"

type ManagedCapability = { id: string; kind: "skill" | "plugin"; name: string; description: string; version: string; category: string; visibility: string; enabled: boolean; dependency_ids: string[] }

export default function CapabilityAdmin() {
  const app = useConsole()
  const [items, setItems] = createSignal<ManagedCapability[]>([])
  const [form, setForm] = createSignal<Partial<ManagedCapability>>()
  const [error, setError] = createSignal("")
  async function refresh() {
    try { setItems(await list<ManagedCapability>("/admin/capabilities")); setError("") }
    catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  createEffect(() => { app.changed(); void refresh() })
  async function save(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    const payload = { kind: data.kind, name: data.name, description: data.description, version: data.version, category: data.category, visibility: data.visibility, enabled: data.enabled === "on", dependency_ids: String(data.dependencies || "").split(",").map((value) => value.trim()).filter(Boolean) }
    try { if (form()?.id) await patch("/admin/capabilities/" + form()!.id, payload); else await post("/admin/capabilities", payload); setForm(undefined); await refresh() }
    catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function test(item: ManagedCapability) {
    try { const result = await post<{ ok: boolean; message: string }>("/admin/capabilities/" + item.id + "/test"); app.notify(result.message, result.ok ? "success" : "error") }
    catch (cause) { app.notify((cause as Error).message, "error") }
  }
  return <div class="final-admin"><PageHead title="能力配置" text="管理员专用入口，用于维护官方 Skill 和插件的配置、依赖、启停与连通测试。" /><ErrorLine message={error()} /><div class="admin-toolbar"><span>该入口不在主导航展示</span><Button variant="primary" icon="plus" onClick={() => setForm({ kind: "skill", version: "1.0", category: "官方能力", visibility: "all", enabled: true })}>新增能力</Button></div><div class="table-wrap"><table><thead><tr><th>能力名称</th><th>类型</th><th>版本</th><th>分类</th><th>可见范围</th><th>状态</th><th>依赖</th><th>操作</th></tr></thead><tbody><For each={items()} fallback={<tr><td colspan="8"><Empty title="尚未配置官方能力" /></td></tr>}>{(item) => <tr><td><strong>{item.name}</strong><small>{item.description}</small></td><td>{item.kind === "skill" ? "Skill" : "插件"}</td><td>{item.version}</td><td>{item.category}</td><td>{item.visibility}</td><td><Status value={item.enabled ? "enabled" : "disabled"} /></td><td>{item.dependency_ids.join("、") || "—"}</td><td><div class="row-actions"><Button onClick={() => setForm(item)}>编辑</Button><Button variant="ghost" onClick={() => void test(item)}>测试</Button></div></td></tr>}</For></tbody></table></div><Show when={form()}><Modal title={form()?.id ? "编辑能力" : "新增能力"} wide onClose={() => setForm(undefined)}><form onSubmit={save}><div class="form-grid"><Field label="类型" required><select name="kind"><option value="skill" selected={form()?.kind === "skill"}>Skill</option><option value="plugin" selected={form()?.kind === "plugin"}>插件</option></select></Field><Field label="名称" required><input name="name" required value={form()?.name || ""} /></Field><Field label="版本"><input name="version" value={form()?.version || "1.0"} /></Field><Field label="分类"><input name="category" value={form()?.category || "官方能力"} /></Field><Field label="可见范围"><select name="visibility"><option value="all">全体用户</option><option value="department">指定部门</option></select></Field><Field label="依赖能力" hint="多个 ID 使用逗号分隔"><input name="dependencies" value={form()?.dependency_ids?.join(",") || ""} /></Field></div><Field label="能力说明"><textarea name="description" value={form()?.description || ""} /></Field><label><input name="enabled" type="checkbox" checked={form()?.enabled !== false} /> 启用</label><div class="modal-actions"><Button type="button" onClick={() => setForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存配置</Button></div></form></Modal></Show></div>
}
