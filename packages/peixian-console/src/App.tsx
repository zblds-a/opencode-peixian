import { canObserve } from "./runtime-view"
import { createEffect, createMemo, createSignal, For, onCleanup, onMount, Show, Switch, Match } from "solid-js"
import { api, ApiError, BASE, expireAuth, onUnauthorized, post, safeMessage, setAuth } from "./api"
import type { Auth, Capability, User } from "./types"
import { roleNames, visibleManagementTabs } from "./access"
import { Button, ErrorLine, Field, Icon, Spinner, Status } from "./components"
import { Context } from "./context"
import Chat from "./pages/Chat"
import Files from "./pages/Files"
import Settings from "./pages/Settings"
import Admin from "./pages/Admin"
import FinalAdmin from "./pages/FinalAdmin"
import { defaultPlatform, platformMetadata } from "./platform"
import type { Platform } from "./platform"
import { connectEvents, createChangeBus, parseChange, parseLive, resources } from "./events"
import RuntimeStatus from "./RuntimeStatus"
import loginStory from "./assets/peixian-login-left.webp"
import loginSide from "./assets/peixian-login-right.webp"
import policeEmblem from "./assets/police-emblem.png"
import settingsIcon from "./assets/images/chat/settings.png"
import cultureTitle from "./assets/peixian-culture-title.png"
import loginFeatureAnalysis from "./assets/login-feature-analysis.svg"
import loginFeatureCapability from "./assets/login-feature-capability.svg"
import loginFeatureKnowledge from "./assets/login-feature-knowledge.svg"
import loginFeatureCollaboration from "./assets/login-feature-collaboration.svg"
const pages = [
  { id: "chat", name: "智能研判", icon: "chat" },
  { id: "settings", name: "个人设置", icon: "settings" },
]
export default function App() {
  const [platform, setPlatform] = createSignal(defaultPlatform)
  const [auth, setSession] = createSignal<Auth>()
  const [loading, setLoading] = createSignal(true)
  const [initialError, setInitialError] = createSignal("")
  const [page, setPage] = createSignal("chat")
  const [menu, setMenu] = createSignal(false)
  const [changed, setChanged] = createSignal(0)
  const changes = createChangeBus()
  const [disconnected, setDisconnected] = createSignal(false)
  const [toast, setToast] = createSignal<{ message: string; kind: string }>()
  const capabilities = () => auth()?.capabilities ?? []
  const can = (capability: Capability) => capabilities().includes(capability)
  const management = () => visibleManagementTabs(capabilities()).length > 0
  const adminPages = () =>
    visibleManagementTabs(capabilities()).map((tab) => ({
      id: "admin-" + tab.id,
      name: tab.id === "users" ? "用户与部门" : tab.id === "audit" ? "调用审计" : tab.label,
      icon: tab.id === "models" ? "skill" : tab.id === "users" ? "users" : tab.id === "audit" ? "clock" : "shield",
    }))
  const defaultPage = () => (can("business.use") ? "chat" : adminPages()[0]?.id ?? "settings")
  const visiblePages = () => pages.filter((item) => item.id === "settings" || can("business.use"))
  let timer: ReturnType<typeof setTimeout> | undefined
  let authGeneration = 0
  let userFlight: Promise<void> | undefined
  function notify(message: string, kind = "success") {
    clearTimeout(timer)
    setToast({ message: safeMessage(message), kind })
    timer = setTimeout(() => setToast(undefined), 5500)
  }
  function accept(value: Auth) {
    authGeneration++
    setAuth(value)
    setSession(value)
    setPage(defaultPage())
  }
  function refreshUser(): Promise<void> {
    if (userFlight) return userFlight
    const first = !auth()
    const generation = authGeneration
    const flight = api<Auth>("/me")
      .then((data) => {
        if (generation !== authGeneration) return
        const previous = auth()?.user.runtime
        setAuth(data)
        setSession(data)
        if (first) setPage(defaultPage())
        if (JSON.stringify(previous) !== JSON.stringify(data.user.runtime)) changes.publish({ resources: ["runtime"] })
      })
      .finally(() => {
        if (userFlight === flight) userFlight = undefined
      })
    userFlight = flight
    return flight
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
      authGeneration++
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
    if (![...visiblePages(), ...adminPages()].some((item) => item.id === page())) setPage(defaultPage())
  })
  const eventIdentity = createMemo(() => {
    const user = auth()?.user
    return user &&
      can("business.use") &&
      !user.must_change_password &&
      canObserve(user.runtime) && (!user.runtime?.maintenance_mode || user.runtime.maintenance_mode === "normal")
      ? user.id
      : undefined
  })
  createEffect(() => {
    if (!eventIdentity()) {
      setDisconnected(false)
      return
    }
    const controller = new AbortController()
    void connectEvents({
      url: BASE + "/events",
      signal: controller.signal,
      onOpen: () => {
        setDisconnected(false)
        changes.publish({ resources: [...resources] })
      },
      onDisconnected: () => setDisconnected(true),
      onUnauthorized: expireAuth,
      onEvent: (event) => {
        const change = parseChange(event)
        if (change) changes.publish(change)
        else {
          const notice = parseLive(event)
          if (notice) changes.publishLive(notice)
        }
      },
    })
    onCleanup(() => controller.abort())
  })
  let lastAccountPoll = 0
  const accountPoll = setInterval(() => {
    const user = auth()?.user
    if (!user || user.must_change_password) return
    if (Date.now() - lastAccountPoll < (document.hidden ? 30000 : 5000)) return
    lastAccountPoll = Date.now()
    void refreshUser().catch(() => {})
    if (!can("business.use") && !document.hidden) setChanged((value) => value + 1)
  }, 5000)
  const visible = () => {
    if (document.hidden || !auth()) return
    lastAccountPoll = Date.now()
    void refreshUser().catch(() => {})
    changes.publish({ resources: [...resources] })
  }
  document.addEventListener("visibilitychange", visible)
  onCleanup(() => {
    clearInterval(accountPoll)
    document.removeEventListener("visibilitychange", visible)
  })
  async function logout() {
    try {
      await post("/auth/logout")
      authGeneration++
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
          <Show
            when={!session().user.must_change_password}
            fallback={<PasswordGate user={session().user} onDone={refreshUser} />}
          >
            <Context.Provider
              value={{
                user: () => auth()!.user,
                capabilities,
                can,
                notify,
                refreshUser,
                changed,
                subscribe: changes.subscribe,
                subscribeLive: changes.subscribeLive,
                invalidate: (resources) => changes.publish({ resources }),
              }}
            >
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
                    <img class="brand-mark app-header__emblem" src={policeEmblem} alt="中华人民共和国人民警察警徽" />
                    <span>
                      <strong class="police-brand-name">沛警智枢</strong>
                      <small class="police-brand-subtitle">沛县公安智能研判平台</small>
                    </span>
                  </a>
                  <Show when={!can("business.use")}>
                    <div class="space-label">管理工作台 <Icon name="lock" size={12} /></div>
                  </Show>
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
                          {item.id === "settings" ? <img class="sidebar-settings-icon" src={settingsIcon} alt="" /> : <Icon name={item.icon} />}
                          <span>{item.name}</span>
                          <Show when={page() === item.id}>
                            <span class="nav-dot" />
                          </Show>
                        </button>
                      )}
                    </For>
                    <Show when={management()}>
                      <For each={adminPages()}>{(item) => <button class={page() === item.id ? "active" : ""} onClick={() => { setPage(item.id); setMenu(false) }} aria-current={page() === item.id ? "page" : undefined}><Icon name={item.icon} /><span>{item.name}</span><Show when={page() === item.id}><span class="nav-dot" /></Show></button>}</For>
                    </Show>
                  </nav>
                  <div class="sidebar-people-first">人民公安为人民</div>
                </aside>
                <main class="main-area">
                  <header class="topbar">
                    <div>
                      <button class="icon-button mobile-menu" aria-label="打开导航" onClick={() => setMenu(true)}>
                        <Icon name="menu" />
                      </button>
                      <Show when={can("business.use")} fallback={<div class="admin-top-motto"><strong class="police-header-slogan">科技赋能公安　智慧守护平安</strong><small class="police-header-values">忠诚｜为民｜公正｜廉洁</small></div>}><div class="business-top-motto"><strong class="police-header-slogan">科技赋能公安　智慧守护平安</strong><small class="police-header-values">忠诚｜为民｜公正｜廉洁</small></div></Show>
                    </div>
                    <div class="topbar-status">
                      <Show when={disconnected()}>
                        <span class="connection-note">正在恢复连接</span>
                      </Show>
                      <div class="app-header__culture">
                        <img class="app-header__culture-title" src={cultureTitle} alt="汉风古韵 · 平安沛县" />
                        <small class="app-header__culture-subtitle">千年文脉　警心守护</small>
                      </div>
                      <div class={"app-header__account " + (can("business.use") ? "business-profile" : "admin-profile")}>
                        <span class="admin-avatar">警</span>
                        <span class="app-header__user"><strong>{session().user.display_name || session().user.username}</strong><small>{can("business.use") ? session().user.position || roleNames[session().user.role] : roleNames[session().user.role]}</small></span>
                        <button class="icon-button" aria-label="退出登录" title="退出登录" onClick={logout}><Icon name="logout" size={17} /></button>
                      </div>
                    </div>
                  </header>
                  <Show when={can("business.use") && page() !== "chat"}><RuntimeStatus /></Show>
                  <div class={"page-body " + (page() === "chat" ? "chat-page-body" : "")}>
                    <Show when={can("business.use")}>
                      <div class="chat-preserved" hidden={page() !== "chat"}>
                        <Chat />
                      </div>
                    </Show>
                    <Switch>
                      <Match when={page() === "files" && can("business.use")}><Files /></Match>
                      <Match when={page() === "settings"}><Settings /></Match>
                      <Match when={page() === "admin-models" && management()}><FinalAdmin section="models" /></Match>
                      <Match when={page() === "admin-users" && management()}><FinalAdmin section="users" /></Match>
                      <Match when={page() === "admin-audit" && management()}><FinalAdmin section="audit" /></Match>
                      <Match when={page().startsWith("admin-") && management()}><Admin section={page().slice(6)} /></Match>
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
          </Show>
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
      <div class="login-story" style={{ "--login-story": `url(${loginStory})` }}>
        <span class="login-story-accessible">沛警智枢，沛县公安智能研判平台。汉风古韵，平安沛县。</span>
        <div class="login-story-title"><img class="login-brand__emblem" src={policeEmblem} alt="中华人民共和国人民警察警徽" /><div><strong>沛警智枢</strong><span>沛县公安智能研判平台</span></div></div>
        <div class="login-story-slogan"><img class="login-story-culture-image" src={cultureTitle} alt="汉风古韵 平安沛县" /><span>—　以数据洞察风险　以智能守护平安　—</span></div>
        <div class="login-story-features">
          <div class="login-story-feature">
            <img src={loginFeatureAnalysis} alt="" />
            <strong>智能研判</strong>
            <span>让数据更有价值</span>
          </div>
          <div class="login-story-feature">
            <img src={loginFeatureCapability} alt="" />
            <strong>能力聚合</strong>
            <span>汇聚公安业务能力</span>
          </div>
          <div class="login-story-feature">
            <img src={loginFeatureKnowledge} alt="" />
            <strong>知识沉淀</strong>
            <span>让经验持续传承</span>
          </div>
          <div class="login-story-feature">
            <img src={loginFeatureCollaboration} alt="" />
            <strong>协同高效</strong>
            <span>助力实战一线</span>
          </div>
        </div>
      </div>
      <div class="login-side" style={{ "--login-side": `url(${loginSide})` }}>
        <div class="login-culture-heading"><img class="login-culture-title" src={cultureTitle} alt="汉风古韵 · 平安沛县" /><div class="login-corner-subtitle">千年文脉　警心守护</div></div>
        <form class="login-card" onSubmit={submit}>
          <div class="login-welcome"><span>欢迎登录</span><strong>沛警智枢</strong></div>
          <p class="login-subtitle">沛 县 公 安 智 能 研 判 平 台</p>
          <ErrorLine message={error() || props.initialError} />
          <Field label="账号">
            <div class="login-field-control">
              <Icon name="users" size={20} />
              <input aria-label="账号" required autocomplete="username" value={username()} onInput={(event) => setUsername(event.currentTarget.value)} placeholder="请输入警号/用户名" />
            </div>
          </Field>
          <Field label="密码">
            <div class="login-field-control">
              <Icon name="lock" size={20} />
              <input aria-label="密码" required type={showPassword() ? "text" : "password"} autocomplete="current-password" value={password()} onInput={(event) => setPassword(event.currentTarget.value)} placeholder="请输入密码" />
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
        <div class="login-foot">© 2024 沛县公安局 ｜ 苏ICP备XXXXXX号 ｜ 建议使用 Chrome / Edge 浏览器</div>
      </div>
    </div>
  )
}

function PasswordGate(props: { user: User; onDone: () => Promise<void> }) {
  const [old, setOld] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [confirm, setConfirm] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (password() !== confirm()) {
      setError("两次输入的新密码不一致。")
      return
    }
    setBusy(true)
    setError("")
    try {
      await post("/me/password", { current_password: old(), password: password() })
      await props.onDone()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div class="password-gate">
      <form class="login-card" onSubmit={save}>
        <span class="empty-icon">
          <Icon name="lock" />
        </span>
        <h2>设置你的登录密码</h2>
        <p>{props.user.username}，首次登录需要更换初始密码。</p>
        <ErrorLine message={error()} />
        <Field label="当前密码">
          <input
            type="password"
            required
            autocomplete="current-password"
            aria-label="当前密码"
            value={old()}
            onInput={(e) => setOld(e.currentTarget.value)}
          />
        </Field>
        <Field label="新密码" hint="至少 12 个字符，建议组合使用字母、数字与符号。">
          <input
            type="password"
            required
            minlength={12}
            autocomplete="new-password"
            aria-label="新密码"
            value={password()}
            onInput={(e) => setPassword(e.currentTarget.value)}
          />
        </Field>
        <Field label="确认新密码">
          <input
            type="password"
            required
            minlength={12}
            autocomplete="new-password"
            aria-label="确认新密码"
            value={confirm()}
            onInput={(e) => setConfirm(e.currentTarget.value)}
          />
        </Field>
        <Button variant="primary" busy={busy()} type="submit" class="full">
          保存并进入工作台
        </Button>
      </form>
    </div>
  )
}
