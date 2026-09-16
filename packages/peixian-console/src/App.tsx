import { createEffect, createMemo, createSignal, For, onCleanup, onMount, Show, Switch, Match } from "solid-js"
import { api, ApiError, BASE, onUnauthorized, post, safeMessage, setAuth } from "./api"
import type { Auth, Capability } from "./types"
import { roleNames, visibleManagementTabs } from "./access"
import { Button, ErrorLine, Field, Icon, Spinner } from "./components"
import { Context } from "./context"
import Chat from "./pages/Chat"
import FinalAdmin from "./pages/FinalAdmin"
import loginPrototype from "./assets/peixian-login-prototype.png"
import { defaultPlatform, platformMetadata } from "./platform"
import type { Platform } from "./platform"
const pages = [
  { id: "chat", name: "智能研判", icon: "chat" },
]
const adminPages = [
  { id: "admin-models", name: "模型管理", icon: "skill" },
  { id: "admin-users", name: "用户与部门", icon: "users" },
  { id: "admin-audit", name: "调用审计", icon: "clock" },
] as const
export default function App() {
  const [platform, setPlatform] = createSignal(defaultPlatform)
  const [auth, setSession] = createSignal<Auth>()
  const [loading, setLoading] = createSignal(true)
  const [initialError, setInitialError] = createSignal("")
  const [page, setPage] = createSignal("chat")
  const [menu, setMenu] = createSignal(false)
  const [changed, setChanged] = createSignal(0)
  const [disconnected, setDisconnected] = createSignal(false)
  const [toast, setToast] = createSignal<{ message: string; kind: string }>()
  const capabilities = () => auth()?.capabilities ?? []
  const can = (capability: Capability) => capabilities().includes(capability)
  const management = () => visibleManagementTabs(capabilities()).length > 0
  const defaultPage = () => (can("business.use") ? "chat" : "admin-models")
  const visiblePages = () => pages.filter(() => can("business.use"))
  let timer: ReturnType<typeof setTimeout> | undefined
  function notify(message: string, kind = "success") {
    clearTimeout(timer)
    setToast({ message: safeMessage(message), kind })
    timer = setTimeout(() => setToast(undefined), 5500)
  }
  function accept(value: Auth) {
    setAuth(value)
    setSession(value)
    setPage(defaultPage())
  }
  async function refreshUser() {
    const first = !auth()
    const data = await api<Auth>("/me")
    setAuth(data)
    setSession(data)
    if (first) setPage(defaultPage())
  }
  async function initialize() {
    setLoading(true)
    setInitialError("")
    try {
      await refreshUser()
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) setInitialError(safeMessage((error as Error).message))
    } finally {
      setLoading(false)
    }
  }
  onMount(() => {
    void api<Platform>("/platform")
      .then((value) => setPlatform(platformMetadata(value)))
      .catch(() => {})
    onUnauthorized(() => {
      setAuth()
      setSession(undefined)
    })
    void initialize()
  })
  onCleanup(() => clearTimeout(timer))
  createEffect(() => {
    document.title = platform().name
  })
  createEffect(() => {
    if (!auth()) return
    if (management() && adminPages.some((item) => item.id === page())) return
    if (!visiblePages().some((item) => item.id === page())) setPage(defaultPage())
  })
  const eventIdentity = createMemo(() => {
    const user = auth()?.user
    return user &&
      can("business.use") &&
      ["ready", "running", "healthy", "updating", "applying"].includes(user.runtime?.status ?? "")
      ? user.id
      : undefined
  })
  createEffect(() => {
    if (!eventIdentity()) {
      setDisconnected(false)
      return
    }
    const events = new EventSource(BASE + "/events", { withCredentials: true })
    let debounce: ReturnType<typeof setTimeout> | undefined
    events.onopen = () => setDisconnected(false)
    events.onerror = () => setDisconnected(true)
    const update = () => {
      if (debounce) return
      debounce = setTimeout(() => {
        debounce = undefined
        setChanged((value) => value + 1)
        void refreshUser().catch(() => {})
      }, 250)
    }
    events.addEventListener("change", update)
    onCleanup(() => {
      clearTimeout(debounce)
      events.close()
    })
  })
  const accountPoll = setInterval(() => {
    const user = auth()?.user
    if (!user) return
    void refreshUser().catch(() => {})
    if (
      !can("business.use") ||
      !["ready", "running", "healthy", "updating", "applying"].includes(user.runtime?.status ?? "")
    )
      setChanged((value) => value + 1)
  }, 5000)
  onCleanup(() => clearInterval(accountPoll))
  async function logout() {
    try {
      await post("/auth/logout")
      setAuth()
      setSession(undefined)
      setMenu(false)
    } catch (error) {
      notify((error as Error).message, "error")
    }
  }
  return (
    <Show
      when={!loading()}
      fallback={
        <div class="boot">
          <Spinner />
          <p>正在打开工作台</p>
        </div>
      }
    >
      <Show
        when={auth()}
        fallback={<Login platform={platform()} onSuccess={accept} initialError={initialError()} onRetry={initialize} />}
      >
        {(session) => (
            <Context.Provider value={{ user: () => auth()!.user, capabilities, can, notify, refreshUser, changed }}>
              <div class={"app-shell " + (can("business.use") ? "business-shell" : "admin-shell") }>
                <Show when={menu()}>
                  <button class="nav-overlay" aria-label="关闭导航" onClick={() => setMenu(false)} />
                </Show>
                <aside class={"sidebar " + (menu() ? "open" : "")}>
                  <a
                    class="brand"
                    href="#"
                    onClick={(event) => {
                      event.preventDefault()
                      setPage(defaultPage())
                      setMenu(false)
                    }}
                  >
                    <span class="brand-mark">{platform().short_name}</span>
                    <span>
                      <strong>{platform().name}</strong>
                      <small>{platform().description}</small>
                    </span>
                  </a>
                  <div class="space-label">
                    {can("business.use") ? "个人工作空间" : "管理工作台"} <Icon name="lock" size={12} />
                  </div>
                  <nav aria-label="主导航">
                    <For each={visiblePages()}>
                      {(item) => (
                        <button
                          class={page() === item.id ? "active" : ""}
                          onClick={() => {
                            setPage(item.id)
                            setMenu(false)
                          }}
                          aria-current={page() === item.id ? "page" : undefined}
                        >
                          <Icon name={item.icon} />
                          <span>{item.name}</span>
                          <Show when={page() === item.id}>
                            <span class="nav-dot" />
                          </Show>
                        </button>
                      )}
                    </For>
                    <Show when={management()}>
                      <For each={adminPages}>{(item) => <button class={page() === item.id ? "active" : ""} onClick={() => { setPage(item.id); setMenu(false) }} aria-current={page() === item.id ? "page" : undefined}><Icon name={item.icon} /><span>{item.name}</span><Show when={page() === item.id}><span class="nav-dot" /></Show></button>}</For>
                    </Show>
                  </nav>
                </aside>
                <main class="main-area">
                  <header class="topbar">
                    <div>
                      <button class="icon-button mobile-menu" aria-label="打开导航" onClick={() => setMenu(true)}>
                        <Icon name="menu" />
                      </button>
                      <Show when={can("business.use")} fallback={<div class="admin-top-motto"><strong>忠诚　为民　公正　廉洁</strong><small>汉风古韵 · 平安沛县</small></div>}><div class="business-top-motto"><strong>忠诚　为民　公正　廉洁</strong><small>汉风古韵 · 平安沛县</small></div></Show>
                    </div>
                    <div class="topbar-status">
                      <Show when={disconnected()}>
                        <span class="connection-note">正在恢复连接</span>
                      </Show>
                      <Show when={can("business.use")} fallback={<div class="admin-profile"><span class="admin-avatar">警</span><span><strong>{session().user.display_name || (session().user.username === "admin" ? "张警官" : session().user.username)}</strong><small>{roleNames[session().user.role]}</small></span><button class="icon-button" aria-label="退出登录" title="退出登录" onClick={logout}><Icon name="logout" size={17} /></button></div>}>
                        <div class="business-profile"><span class="business-location">江苏 · 沛县<small>千年汉风地 · 今日平安城</small></span><span class="admin-avatar">警</span><span><strong>{session().user.display_name || session().user.username}</strong><small>{session().user.position || roleNames[session().user.role]}</small></span><button class="icon-button" aria-label="退出登录" title="退出登录" onClick={logout}><Icon name="logout" size={17} /></button></div>
                      </Show>
                    </div>
                  </header>
                  <div class={"page-body " + (page() === "chat" ? "chat-page-body" : "")}>
                    <Show when={can("business.use")}>
                      <div class="chat-preserved" hidden={page() !== "chat"}>
                        <Chat />
                      </div>
                    </Show>
                    <Switch>
                      <Match when={page() === "admin-models" && management()}><FinalAdmin section="models" /></Match>
                      <Match when={page() === "admin-users" && management()}><FinalAdmin section="users" /></Match>
                      <Match when={page() === "admin-audit" && management()}><FinalAdmin section="audit" /></Match>
                    </Switch>
                  </div>
                </main>
              </div>
              <Show when={toast()}>
                {(value) => (
                  <div class={"toast " + value().kind} role="status">
                    <Icon name={value().kind === "error" ? "close" : "check"} size={17} />
                    {value().message}
                    <button aria-label="关闭提示" onClick={() => setToast(undefined)}>
                      ×
                    </button>
                  </div>
                )}
              </Show>
            </Context.Provider>
        )}
      </Show>
    </Show>
  )
}
function Login(props: {
  platform: Platform
  onSuccess: (value: Auth) => void
  initialError: string
  onRetry: () => Promise<void>
}) {
  const rememberedUsername = localStorage.getItem("peixian-remembered-username") ?? ""
  const [username, setUsername] = createSignal(rememberedUsername)
  const [password, setPassword] = createSignal("")
  const [remember, setRemember] = createSignal(true)
  const [showPassword, setShowPassword] = createSignal(false)
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  async function submit(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const data = await post<Auth>("/auth/login", { username: username().trim(), password: password() })
      if (remember()) localStorage.setItem("peixian-remembered-username", username().trim())
      else localStorage.removeItem("peixian-remembered-username")
      setPassword("")
      props.onSuccess(data)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div class="login-shell">
      <div class="login-story" style={{ "--login-prototype": `url(${loginPrototype})` }}>
        <span class="login-story-accessible">沛警智枢，沛县公安智能研判平台。汉风古韵，平安沛县。</span>
      </div>
      <div class="login-side">
        <div class="login-corner-copy">汉风古韵 · 平安沛县</div>
        <form class="login-card" onSubmit={submit}>
          <div class="login-welcome"><span>欢迎登录</span><strong>沛警智枢</strong></div>
          <p class="login-subtitle">沛 县 公 安 智 能 研 判 平 台</p>
          <div class="login-account-tab">账号登录</div>
          <ErrorLine message={error() || props.initialError} />
          <Field label="账号">
            <div class="login-field-control">
              <Icon name="users" size={20} />
              <input required autocomplete="username" value={username()} onInput={(event) => setUsername(event.currentTarget.value)} placeholder="请输入警号/用户名" />
            </div>
          </Field>
          <Field label="密码">
            <div class="login-field-control">
              <Icon name="lock" size={20} />
              <input required type={showPassword() ? "text" : "password"} autocomplete="current-password" value={password()} onInput={(event) => setPassword(event.currentTarget.value)} placeholder="请输入密码" />
              <button type="button" class="login-password-toggle" aria-label={showPassword() ? "隐藏密码" : "显示密码"} onClick={() => setShowPassword(!showPassword())}>
                <Icon name={showPassword() ? "eye-off" : "eye"} size={19} />
              </button>
            </div>
          </Field>
          <label class="login-remember">
            <input type="checkbox" checked={remember()} onChange={(event) => setRemember(event.currentTarget.checked)} />
            <span>记住我</span>
          </label>
          <Button type="submit" variant="primary" busy={busy()} class="full">
            登 录
          </Button>
          <Show when={props.initialError}>
            <Button type="button" variant="ghost" onClick={props.onRetry}>
              重新连接
            </Button>
          </Show>
          <small>登录遇到问题，请联系系统管理员</small>
        </form>
        <div class="login-people-first">人民公安为人民</div>
        <div class="login-foot">© 2026 沛县公安局　|　建议使用 Chrome / Edge 浏览器</div>
      </div>
    </div>
  )
}
