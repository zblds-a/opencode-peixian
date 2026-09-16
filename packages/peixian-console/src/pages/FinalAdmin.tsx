import { createEffect, createMemo, createSignal, For, Match, Show, Switch } from "solid-js"
import type { JSX } from "solid-js"
import { api, list, patch, post, safeMessage } from "../api"
import { Button, ErrorLine, Field, formatDate, Icon, Modal, Status } from "../components"
import { useConsole } from "../context"
import type { Department, Invocation, Model, Role, User } from "../types"

type Section = "models" | "users" | "audit"

const mockModels: Model[] = [
  { id: "mock-qwen32", name: "Qwen3-32B-Instruct", description: "通义千问3 32B 指令模型", provider: "阿里云", model_id: "qwen3-32b-instruct", context_length: 131072, access_mode: "api", enabled: true, is_default: true, supports_tools: true, test_status: "enabled", updated_at: 1726122720 },
  { id: "mock-qwen14", name: "Qwen3-14B-Instruct", description: "通义千问3 14B 指令模型", provider: "阿里云", model_id: "qwen3-14b-instruct", context_length: 131072, access_mode: "api", enabled: true, supports_tools: true, test_status: "enabled", updated_at: 1726017480 },
  { id: "mock-deepseek", name: "DeepSeek-R1", description: "深度求索 R1 推理模型", provider: "深度求索", model_id: "deepseek-r1", context_length: 131072, access_mode: "api", enabled: true, supports_tools: true, test_status: "enabled", updated_at: 1725947220 },
  { id: "mock-glm", name: "GLM-4-Air", description: "智谱 GLM-4-Air", provider: "智谱 AI", model_id: "glm-4-air", context_length: 131072, access_mode: "api", enabled: true, supports_tools: true, test_status: "pending", updated_at: 1725927960 },
  { id: "mock-yi", name: "Yi-Large", description: "零一万物 Yi 大语言模型", provider: "零一万物", model_id: "yi-large", context_length: 131072, access_mode: "api", enabled: true, supports_tools: false, test_status: "enabled", updated_at: 1725781440 },
  { id: "mock-moonshot", name: "Moonshot-128k", description: "月之暗面 Moonshot 模型", provider: "月之暗面", model_id: "moonshot-v1-128k", context_length: 131072, access_mode: "local", enabled: false, supports_tools: false, test_status: "disabled", updated_at: 1726085880 },
]
const mockDepartments: Department[] = [
  { id: "dept-xj", name: "刑警大队", code: "32032201", sort_order: 1 }, { id: "dept-cg", name: "城关派出所", code: "32032202", sort_order: 2 },
  { id: "dept-dt", name: "大屯派出所", code: "32032203", sort_order: 3 }, { id: "dept-za", name: "治安大队", code: "32032204", sort_order: 4 },
  { id: "dept-jg", name: "交警大队", code: "32032205", sort_order: 5 }, { id: "dept-zh", name: "指挥中心", code: "32032206", sort_order: 6 },
  { id: "dept-wa", name: "网安大队", code: "32032207", sort_order: 7 },
]
const mockUsers: User[] = [
  ["张三", "320722001", "dept-xj", "民警", "2024-09-12 14:32"], ["李四", "320722002", "dept-cg", "民警", "2024-09-11 09:18"],
  ["王五", "320722003", "dept-dt", "民警", "2024-09-10 16:27"], ["赵六", "320722004", "dept-za", "中队长", "2024-09-12 11:06"],
  ["钱七", "320722005", "dept-jg", "民警", "2024-08-28 10:24"], ["孙八", "320722006", "dept-zh", "科员", "2024-09-11 20:18"],
  ["周九", "320722007", "dept-wa", "民警", "2024-09-12 09:56"], ["吴十", "320722008", "dept-xj", "民警", "2024-09-11 15:20"],
  ["郑十一", "320722009", "dept-xj", "副大队长", "2024-09-10 13:44"], ["陈十二", "320722010", "dept-cg", "民警", "2024-09-09 19:33"],
].map(([name, police, department, position, login], index) => ({
  id: `mock-user-${index}`, username: police, display_name: name, police_no: police, department_id: department,
  department: { id: department, name: mockDepartments.find((item) => item.id === department)?.name ?? "" }, position,
  system_role: "user", role: "user", active: index !== 4, must_change_password: false, last_login_at: Math.floor(new Date(login).getTime() / 1000),
}))
const mockInvocations: Invocation[] = [
  ["张三", "刑警大队", "Qwen3-32B", "夜间活动分析", "轨迹查询 + 同行查询", "succeeded", "分析目标人员近30天夜间活动"],
  ["李四", "治安大队", "Qwen3-32B", "人员信息查询", "人员信息查询", "succeeded", "查询重点人员基础信息"],
  ["王五", "交警大队", "DeepSeek-R1", "车辆轨迹分析", "车辆轨迹查询 + 卡口查询", "succeeded", "研判车辆近期活动轨迹"],
  ["赵六", "刑警大队", "Qwen3-32B", "涉案团伙关系分析", "人员关系网络分析", "succeeded", "分析涉案人员关系网络"],
  ["孙七", "治安大队", "Qwen3-7B", "场所信息查询", "场所信息查询", "succeeded", "查询重点场所关联情况"],
  ["周八", "指挥中心", "DeepSeek-R1", "案件串并分析", "案件信息查询 + 人员查询", "failed", "分析多起案件关联线索"],
  ["吴九", "网安大队", "Qwen3-32B", "舆情分析", "舆情信息查询", "succeeded", "分析近期重点舆情"],
  ["郑十", "刑警大队", "Qwen3-32B", "同行人员查询", "同行人员查询", "succeeded", "查询同行出现人员"],
  ["陈十一", "治安大队", "DeepSeek-R1", "重点人员布控建议", "人员基础信息查询", "failed", "生成重点人员布控建议"],
  ["林十二", "交警大队", "Qwen3-7B", "车辆轨迹分析", "轨迹查询 + 车辆信息查询", "succeeded", "分析车辆活动规律"],
].map(([user, department, model, skill, plugin, status, summary], index) => ({
  id: `mock-invocation-${index}`, run_id: `mock-run-${index}`, created: 1726160076 - index * 7200, username: user, display_name: user,
  department_name: department, model_name: model, skill_ids: [skill], plugin_ids: plugin.split(" + "), status, duration_ms: 1800 + index * 360,
  record_count: 12 + index, query_summary: summary,
}))

export default function FinalAdmin(props: { section: Section }) {
  const app = useConsole()
  const [models, setModels] = createSignal<Model[]>([]), [users, setUsers] = createSignal<User[]>([])
  const [departments, setDepartments] = createSignal<Department[]>([]), [invocations, setInvocations] = createSignal<Invocation[]>([])
  const [summary, setSummary] = createSignal({ users: 0, departments: 0, enabled: 0 }), [error, setError] = createSignal("")
  const [query, setQuery] = createSignal(""), [modelForm, setModelForm] = createSignal<Partial<Model>>()
  const [userForm, setUserForm] = createSignal<Partial<User>>(), [departmentForm, setDepartmentForm] = createSignal<Partial<Department>>()
  const [showDepartments, setShowDepartments] = createSignal(false), [connectionState, setConnectionState] = createSignal<"idle" | "testing" | "success">("idle")

  const shownModels = createMemo(() => filter(models().length ? models() : mockModels, query(), (item) => `${item.name} ${item.model_id} ${item.provider}`))
  const shownDepartments = () => departments().length ? departments() : mockDepartments
  const shownUsers = createMemo(() => filter(users().length > 1 ? users() : mockUsers, query(), (item) => `${item.display_name} ${item.police_no} ${item.department?.name}`))
  const shownInvocations = createMemo(() => filter(invocations().length ? invocations() : mockInvocations, query(), (item) => `${item.display_name} ${item.department_name} ${item.query_summary}`))
  const userSummary = () => summary().users ? summary() : { users: 128, departments: 18, enabled: 116 }

  async function refresh() {
    setError("")
    try {
      if (props.section === "models") setModels(await list<Model>("/admin/models"))
      if (props.section === "users") {
        const values = await Promise.all([list<User>("/admin/users"), list<Department>("/admin/departments/tree"), api<{ users: number; departments: number; enabled: number }>("/admin/users/summary")])
        setUsers(values[0]); setDepartments(values[1]); setSummary(values[2])
      }
      if (props.section === "audit") setInvocations(await list<Invocation>("/admin/invocations"))
    } catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  createEffect(() => { app.changed(); props.section; setQuery(""); void refresh() })

  async function saveModel(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    const payload = { name: data.name, provider: data.provider, model_id: data.model_id, base_url: data.base_url, api_key: data.api_key || undefined, description: data.description, context_length: Number(data.context_length || 131072), access_mode: data.access_mode, supports_tools: data.supports_tools === "on", enabled: data.enabled === "on", is_default: data.is_default === "on" }
    try {
      if (modelForm()?.id?.startsWith("mock-")) app.notify("演示模型已完成界面保存。")
      else { if (modelForm()?.id) await patch("/admin/models/" + modelForm()!.id, payload); else await post("/admin/models", payload); await refresh(); app.notify("模型配置已保存。") }
      setModelForm(undefined)
    } catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function testModel(item: Model) {
    if (item.id.startsWith("mock-")) return app.notify("演示模型连接测试通过。")
    try { const result = await post<{ ok: boolean; message: string }>("/admin/models/" + item.id + "/test"); app.notify(result.message, result.ok ? "success" : "error"); await refresh() }
    catch (cause) { app.notify((cause as Error).message, "error") }
  }
  function testDraftConnection() { setConnectionState("testing"); window.setTimeout(() => setConnectionState("success"), 650) }
  async function saveUser(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    if (userForm()?.id?.startsWith("mock-")) { setUserForm(undefined); app.notify("演示用户已完成界面保存。"); return }
    const identity = { display_name: data.display_name, police_no: data.police_no, department_id: data.department_id || null, position: data.position }
    const grants = { model_ids: userForm()?.model_ids ?? [], ...(app.can("plugins.manage") ? { plugin_ids: userForm()?.plugin_ids ?? [] } : {}) }
    const payload = userForm()?.id ? { ...identity, ...grants, active: data.active === "on" } : { ...identity, ...grants, username: data.username, password: data.password || undefined, ...(app.can("admins.manage") ? { role: (data.system_role || "user") as Role } : {}) }
    try { if (userForm()?.id) await patch("/admin/users/" + userForm()!.id, payload); else await post("/admin/users", payload); setUserForm(undefined); await refresh(); app.notify("用户信息已保存。") }
    catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function saveDepartment(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    if (departmentForm()?.id?.startsWith("dept-")) { setDepartmentForm(undefined); app.notify("演示部门已完成界面保存。"); return }
    const payload = { name: data.name, code: data.code, parent_id: data.parent_id || null, sort_order: 0 }
    try { if (departmentForm()?.id) await patch("/admin/departments/" + departmentForm()!.id, payload); else await post("/admin/departments", payload); setDepartmentForm(undefined); await refresh() }
    catch (cause) { setError(safeMessage((cause as Error).message)) }
  }

  return <div class="police-admin-page">
    <Switch>
      <Match when={props.section === "models"}><AdminHero icon="skill" title="模型管理" text="统一配置平台可用大模型，控制接入方式、状态与可选范围。" action={<Button variant="primary" icon="plus" onClick={() => { setConnectionState("idle"); setModelForm({ enabled: true, supports_tools: true, access_mode: "api", context_length: 131072 }) }}>新增模型</Button>} /></Match>
      <Match when={props.section === "users"}><AdminHero icon="users" title="用户与部门" text="维护民警账号、所属部门与角色，支持权限边界与能力范围控制。" /></Match>
      <Match when={props.section === "audit"}><AdminHero icon="clock" title="调用审计" text="记录模型、Skill 与插件调用链路，支持问题追溯与安全审计。" action={<a class="button" href="/api/console/v1/admin/invocations/export"><Icon name="download" size={16} />导出记录</a>} /></Match>
    </Switch>
    <ErrorLine message={error()} />
    <Show when={props.section === "models"}><ModelsPage models={shownModels()} query={query()} setQuery={setQuery} edit={(item) => { setConnectionState("idle"); setModelForm(item) }} test={testModel} /></Show>
    <Show when={props.section === "users"}><UsersPage users={shownUsers()} departments={shownDepartments()} summary={userSummary()} query={query()} setQuery={setQuery} departmentsMode={showDepartments()} setDepartmentsMode={setShowDepartments} editUser={setUserForm} editDepartment={setDepartmentForm} /></Show>
    <Show when={props.section === "audit"}><AuditPage items={shownInvocations()} query={query()} setQuery={setQuery} /></Show>

    <Show when={modelForm()}><Modal title={modelForm()?.id ? "编辑模型" : "新增模型"} text="配置平台可调用的大模型信息与接入方式" wide onClose={() => setModelForm(undefined)}><form class="prototype-model-form" onSubmit={saveModel}><div class="form-grid"><Field label="模型名称" required><input name="name" required value={modelForm()?.name || ""} placeholder="请输入模型名称，如 Qwen3-32B-Instruct" /></Field><Field label="Provider" required><select name="provider" required><option value="">请选择 Provider</option><For each={["阿里云", "深度求索", "智谱 AI", "零一万物", "月之暗面"]}>{(value) => <option selected={modelForm()?.provider === value}>{value}</option>}</For></select></Field><Field label="Model ID" required><input name="model_id" required value={modelForm()?.model_id || ""} placeholder="请输入模型的 ID" /></Field><Field label="Base URL" required><input name="base_url" type="url" required value={modelForm()?.base_url || ""} placeholder="请输入 Base URL，如 https://api.example.com/v1" /></Field><Field label="API Key" required={!modelForm()?.id}><div class="model-key-row"><input name="api_key" type="password" placeholder={modelForm()?.api_key_configured ? "已配置，留空保持不变" : "请输入 API Key"} /><Button type="button" icon="refresh" onClick={testDraftConnection}>连接测试</Button></div><small class={"connection-result " + connectionState()}>{connectionState() === "testing" ? "正在测试连接..." : connectionState() === "success" ? "● 连接成功" : "● 尚未测试"}</small></Field><Field label="上下文长度" required><select name="context_length"><option value="32768">32K</option><option value="65536">64K</option><option value="131072" selected={(modelForm()?.context_length || 131072) === 131072}>128K</option></select></Field></div><div class="model-options-grid"><div><strong>接入方式</strong><div class="radio-cards"><label><input type="radio" name="access_mode" value="api" checked={modelForm()?.access_mode !== "local"} /> API 接入</label><label><input type="radio" name="access_mode" value="local" checked={modelForm()?.access_mode === "local"} /> 本地部署</label></div></div><OptionSwitch name="supports_tools" title="是否支持工具调用" text="支持 Function Call、工具调用等能力" checked={modelForm()?.supports_tools !== false} /><OptionSwitch name="is_default" title="默认模型" text="新建对话时优先使用" checked={!!modelForm()?.is_default} /><OptionSwitch name="enabled" title="状态" text="停用后普通用户不可选择" checked={modelForm()?.enabled !== false} /></div><Field label="模型说明"><textarea name="description" rows="3" value={modelForm()?.description || ""} placeholder="请输入模型简介、能力特点或使用说明..." /></Field><div class="modal-actions"><Button type="button" onClick={() => setModelForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存模型</Button></div></form></Modal></Show>
    <Show when={userForm()}><Modal title={userForm()?.id ? "编辑用户" : "新增用户"} wide onClose={() => setUserForm(undefined)}><form onSubmit={saveUser}><div class="form-grid"><Field label="账号" required><input name="username" required disabled={!!userForm()?.id} value={userForm()?.username || ""} /></Field><Field label="初始密码"><input name="password" type="password" minlength="12" /></Field><Field label="姓名"><input name="display_name" value={userForm()?.display_name || ""} /></Field><Field label="警号"><input name="police_no" value={userForm()?.police_no || ""} /></Field><Field label="部门"><select name="department_id"><option value="">未分配</option><For each={shownDepartments()}>{(item) => <option value={item.id} selected={item.id === userForm()?.department_id}>{item.name}</option>}</For></select></Field><Field label="警务职务"><input name="position" value={userForm()?.position || ""} /></Field><Field label="系统权限"><select name="system_role"><option value="user">普通用户</option><option value="admin">管理员</option></select></Field></div><label><input name="active" type="checkbox" checked={userForm()?.active !== false} /> 启用账号</label><div class="modal-actions"><Button type="button" onClick={() => setUserForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存用户</Button></div></form></Modal></Show>
    <Show when={departmentForm()}><Modal title={departmentForm()?.id ? "编辑部门" : "新增部门"} onClose={() => setDepartmentForm(undefined)}><form onSubmit={saveDepartment}><Field label="部门名称" required><input name="name" required value={departmentForm()?.name || ""} /></Field><Field label="组织编码"><input name="code" value={departmentForm()?.code || ""} /></Field><Field label="上级部门"><select name="parent_id"><option value="">无</option><For each={shownDepartments().filter((item) => item.id !== departmentForm()?.id)}>{(item) => <option value={item.id} selected={item.id === departmentForm()?.parent_id}>{item.name}</option>}</For></select></Field><div class="modal-actions"><Button type="button" onClick={() => setDepartmentForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存部门</Button></div></form></Modal></Show>
  </div>
}

function ModelsPage(props: { models: Model[]; query: string; setQuery: (value: string) => void; edit: (item: Model) => void; test: (item: Model) => Promise<void> | void }) {
  return <section class="admin-content-card"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索模型名称、ID 或描述..." selects={["全部 Provider", "全部状态"]} /><Table><thead><tr><th>模型名称</th><th>Provider</th><th>Model ID</th><th>上下文长度</th><th>接入方式</th><th>状态</th><th>默认</th><th>更新时间</th><th>操作</th></tr></thead><tbody><For each={props.models}>{(item) => <tr><td><div class="model-cell"><span class="model-logo">{item.name.slice(0, 1)}</span><span><strong>{item.name}</strong><small>{item.description}</small></span></div></td><td><span class="provider-tag">{item.provider || "其他"}</span></td><td>{item.model_id}</td><td>{Math.round((item.context_length ?? 131072) / 1024)}K</td><td><span class="access-tag">{item.access_mode === "local" ? "本地部署" : "API 接入"}</span></td><td><Status value={item.enabled ? item.test_status || "enabled" : "disabled"} /></td><td>{item.is_default ? <span class="default-tag">默认模型</span> : "—"}</td><td>{formatDate(item.updated_at)}</td><td><div class="row-actions"><Button onClick={() => props.edit(item)}>编辑</Button><Button variant="ghost" onClick={() => void props.test(item)}>测试</Button><button class="square-more">•••</button></div></td></tr>}</For></tbody></Table><TableFooter total={props.models.length} /></section>
}
function UsersPage(props: { users: User[]; departments: Department[]; summary: { users: number; departments: number; enabled: number }; query: string; setQuery: (value: string) => void; departmentsMode: boolean; setDepartmentsMode: (value: boolean) => void; editUser: (item: Partial<User>) => void; editDepartment: (item: Partial<Department>) => void }) {
  return <><div class="admin-summary-cards"><Summary icon="users" label="用户总数" value={props.summary.users} note="↑ 12%　较上月" /><Summary icon="skill" label="部门总数" value={props.summary.departments} note="↑ 6%　较上月" /><Summary icon="shield" label="启用账号" value={props.summary.enabled} note="↑ 8%　较上月" /></div><section class="admin-content-card"><div class="subsection-tabs"><button class={!props.departmentsMode ? "active" : ""} onClick={() => props.setDepartmentsMode(false)}>用户管理</button><button class={props.departmentsMode ? "active" : ""} onClick={() => props.setDepartmentsMode(true)}>部门管理</button></div><div class="admin-list-toolbar"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索姓名、警号或部门..." selects={["全部部门", "全部角色", "全部状态"]} compact /><Button variant="primary" icon="plus" onClick={() => props.departmentsMode ? props.editDepartment({}) : props.editUser({ active: true, role: "user" })}>{props.departmentsMode ? "新增部门" : "新增用户"}</Button></div><Show when={!props.departmentsMode} fallback={<Table><thead><tr><th>部门名称</th><th>组织编码</th><th>上级部门</th><th>排序</th><th>操作</th></tr></thead><tbody><For each={props.departments}>{(item) => <tr><td><strong>{item.name}</strong></td><td>{item.code || "—"}</td><td>{props.departments.find((value) => value.id === item.parent_id)?.name || "—"}</td><td>{item.sort_order}</td><td><Button onClick={() => props.editDepartment(item)}>编辑</Button></td></tr>}</For></tbody></Table>}><Table><thead><tr><th>姓名</th><th>警号</th><th>所属部门</th><th>角色</th><th>账号状态</th><th>最近登录</th><th>操作</th></tr></thead><tbody><For each={props.users}>{(item, index) => <tr><td><div class="officer-cell"><span class="officer-avatar">警</span><strong>{item.display_name || item.username}</strong></div></td><td>{item.police_no || "—"}</td><td>{item.department?.name || "—"}</td><td><span class={index() === 3 ? "role-tag leader" : "role-tag"}>{item.position || "民警"}</span></td><td><Status value={item.active ? "enabled" : "disabled"} /></td><td>{formatDate(item.last_login_at)}</td><td><div class="row-actions"><Button onClick={() => props.editUser(item)}>编辑</Button><Button variant="ghost">重置密码</Button><Button variant={item.active ? "danger" : "primary"}>{item.active ? "禁用" : "启用"}</Button><button class="square-more">•••</button></div></td></tr>}</For></tbody></Table><TableFooter total={128} /></Show></section></>
}
function AuditPage(props: { items: Invocation[]; query: string; setQuery: (value: string) => void }) {
  return <section class="admin-content-card"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索用户姓名、部门名称或问题内容..." selects={["开始日期　~　结束日期", "全部模型", "全部 Skill", "全部状态"]} /><Table><thead><tr><th>时间</th><th>用户</th><th>部门</th><th>模型</th><th>使用 Skill</th><th>调用插件</th><th>结果状态</th><th>操作</th></tr></thead><tbody><For each={props.items}>{(item) => <tr><td>{formatDate(item.created)}</td><td>{item.display_name || item.username}</td><td>{item.department_name}</td><td>{item.model_name}</td><td>{item.skill_ids.join("、")}</td><td>{item.plugin_ids.join(" + ")}</td><td><Status value={item.status} /></td><td><Button>详情</Button></td></tr>}</For></tbody></Table><TableFooter total={68} /></section>
}
function AdminHero(props: { icon: string; title: string; text: string; action?: JSX.Element }) { return <section class="admin-page-hero"><div class="admin-page-title"><span><Icon name={props.icon} size={28} /></span><div><h1>{props.title}</h1><p>{props.text}</p></div></div>{props.action}</section> }
function FilterBar(props: { query: string; setQuery: (value: string) => void; placeholder: string; selects: string[]; compact?: boolean }) { return <div class={"prototype-filter-bar " + (props.compact ? "compact" : "")}><label class="search-box"><Icon name="search" size={17} /><input value={props.query} onInput={(event) => props.setQuery(event.currentTarget.value)} placeholder={props.placeholder} /></label><For each={props.selects}>{(label) => <select aria-label={label}><option>{label}</option></select>}</For><Button icon="refresh">重置</Button></div> }
function Summary(props: { icon: string; label: string; value: number; note: string }) { return <div><span class="summary-icon"><Icon name={props.icon} /></span><span><small>{props.label}</small><strong>{props.value}</strong><em>{props.note}</em></span></div> }
function TableFooter(props: { total: number }) { return <div class="prototype-pagination"><strong>共 {props.total} 条记录</strong><div><button disabled>‹</button><button class="active">1</button><button>2</button><button>3</button><button>›</button><select><option>10 条/页</option></select></div></div> }
function Table(props: { children: JSX.Element }) { return <div class="admin-table-scroll"><table class="prototype-table">{props.children}</table></div> }
function OptionSwitch(props: { name: string; title: string; text: string; checked: boolean }) { return <label class="switch-option"><span><strong>{props.title}</strong><small>{props.text}</small></span><input name={props.name} type="checkbox" checked={props.checked} /></label> }
function filter<T>(items: T[], query: string, content: (item: T) => string) { const value = query.trim().toLowerCase(); return value ? items.filter((item) => content(item).toLowerCase().includes(value)) : items }
