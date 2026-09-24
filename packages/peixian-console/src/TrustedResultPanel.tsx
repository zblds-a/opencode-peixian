import { createEffect, createSignal, For, Show, onCleanup } from "solid-js"
import { api, post, remove, ApiError } from "./api"
import { Modal, Button, ErrorLine } from "./components"
import { controlledAnswer, ownedResult, usageLabels, narrativeLabels, taskLabels, fieldLabels, label } from "./trusted-v2"
import type { TaskContext, TrustedResult, Claim } from "./trusted-v2"
import "./trusted-result.css"
type Ticket = {
  clarification_id: string
  question: string
  options: { id: string; label: string }[]
  context_generation: number
  context_version: number
  status: string
}
type Task = {
  run_id: string
  task_spec: Record<string, unknown> | null
  agent_profile: { id: string; version: string } | null
  response?: { clarification_id?: string }
}
export default function TrustedResultPanel(props: {
  sid: string
  rid?: string
  revision?: string
  agent: string
  disabled: boolean
  events?: {sequence:number;name:string;status:string;completed_at?:string|null}[]
  onContext: (value: TaskContext) => void
  onContinue: () => void
  onResult?: (value: TrustedResult | undefined) => void
}) {
  const [result, setResult] = createSignal<TrustedResult>(),
    [task, setTask] = createSignal<Task>(),
    [ticket, setTicket] = createSignal<Ticket>(),
    [context, setContext] = createSignal<TaskContext>()
  const [error, setError] = createSignal(""),
    [pending, setPending] = createSignal(false),
    [option, setOption] = createSignal(""),
    [resume, setResume] = createSignal<TaskContext>(),
    [source, setSource] = createSignal<Claim>(),
    [epoch, setEpoch] = createSignal(0)
  let request = 0,
    alive = true
  onCleanup(() => {
    alive = false
    request++
  })
  createEffect(() => {
    const sid = props.sid,
      rid = props.rid,
      agent = props.agent
    props.revision
    epoch()
    const sequence = ++request
    const current = () => alive && sequence === request && props.sid === sid && props.rid === rid
    setError("")
    setResult(undefined)
    props.onResult?.(undefined)
    setTask(undefined)
    setTicket(undefined)
    setSource(undefined)
    setOption("")
    setResume(undefined)
    setContext(undefined)
    void (async () => {
      try {
        const [contextReply, taskReply, resultReply] = await Promise.allSettled([
          api<TaskContext>(`/sessions/${sid}/task-context?agent_id=${encodeURIComponent(agent)}`),
          rid ? api<Task>(`/sessions/${sid}/runs/${rid}/task`) : Promise.resolve(undefined),
          rid ? api<unknown>(`/sessions/${sid}/runs/${rid}/result`) : Promise.resolve(undefined),
        ])
        if (!current()) return
        const ctx = contextReply.status === "fulfilled" ? contextReply.value : undefined
        const nextTask = taskReply.status === "fulfilled" ? taskReply.value : undefined
        if (ctx) {
          setContext(ctx)
          props.onContext(ctx)
          if (resume() && (resume()!.generation !== ctx.generation || resume()!.version !== ctx.version))
            setResume(undefined)
        }
        setTask(nextTask)
        if (rid && resultReply.status === "fulfilled" && resultReply.value) {
          if (!ownedResult(resultReply.value, rid, nextTask?.agent_profile?.id)) throw new Error("结果版本或执行归属无法识别，未展示可信卡片。")
          setResult(resultReply.value)
          props.onResult?.(resultReply.value)
        }
        const failures = [contextReply, taskReply, resultReply]
          .filter((reply) => reply.status === "rejected")
          .map((reply) => (reply as PromiseRejectedResult).reason)
          .filter(
            (cause) =>
              !(
                cause instanceof ApiError &&
                ["task_context_not_enabled", "agent_not_enabled"].includes(cause.code ?? "")
              ),
          )
        if (failures.length) setError(failures.map((cause) => cause.message).join("；"))
        const cid = ctx?.pending_clarification_id || nextTask?.response?.clarification_id
        if (cid && ctx) {
          const value = await api<Ticket>(`/sessions/${sid}/clarifications/${cid}`)
          if (current()) {
            setTicket(value)
            if (
              value.status === "resolved" &&
              value.context_generation === ctx.generation &&
              value.context_version === ctx.version
            )
              setResume(ctx)
          }
        }
      } catch (cause) {
        if (current()) setError((cause as Error).message)
      }
    })()
  })
  async function decide(cancel = false) {
    const value = ticket(),
      ctx = context(),
      sid = props.sid,
      rid = props.rid,
      sequence = request
    if (!value || !ctx || pending() || value.status !== "pending" || (!cancel && !option())) return
    setPending(true)
    setError("")
    try {
      const change = await post<{ context_generation: number; context_version: number; resume_required: boolean }>(
        `/sessions/${sid}/clarifications/${value.clarification_id}/${cancel ? "cancel" : "resolve"}`,
        {
          context_generation: value.context_generation,
          context_version: value.context_version,
          client_request_id: crypto.randomUUID(),
          ...(!cancel ? { option_id: option() } : {}),
        },
      )
      if (!alive || sequence !== request || sid !== props.sid || rid !== props.rid) return
      const next = {
        ...ctx,
        generation: change.context_generation,
        version: change.context_version,
        pending_clarification_id: null,
      }
      setContext(next)
      props.onContext(next)
      setResume(change.resume_required ? next : undefined)
      setTicket({ ...value, status: cancel ? "cancelled" : "resolved" })
    } catch (cause) {
      if (alive && sequence === request) {
        setError((cause as Error).message)
        if (cause instanceof ApiError && cause.status === 409) {
          setTicket(undefined)
          setResume(undefined)
        }
      }
    } finally {
      if (alive) setPending(false)
    }
  }
  async function resetContext() {
    const sid = props.sid,
      sequence = request
    if (pending() || props.disabled) return
    setPending(true)
    try {
      const next = (await remove(`/sessions/${sid}/task-context`)) as TaskContext
      if (alive && sequence === request && props.sid === sid) {
        setContext(next)
        props.onContext(next)
        setResume(undefined)
        setTicket(undefined)
        setEpoch((x) => x + 1)
      }
    } catch (cause) {
      if (alive && sequence === request) setError((cause as Error).message)
    } finally {
      if (alive) setPending(false)
    }
  }
  async function exportReport() {
    const rid = props.rid
    if (!rid) return
    try {
      const text = await api<string>(`/sessions/${props.sid}/runs/${rid}/report?format=html`)
      if (!alive || props.rid !== rid) return
      if (typeof text !== "string") throw new Error("报告格式无法识别")
      const url = URL.createObjectURL(new Blob([text], { type: "text/html;charset=utf-8" }))
      const link = document.createElement("a")
      link.href = url
      link.download = `run-${rid}.html`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) {
      setError((cause as Error).message)
    }
  }
  const taskValue = () => result()?.task ?? task()?.task_spec ?? {}
  const agentValue = () => result()?.agent ?? task()?.agent_profile
  return (
    <section class="trusted-v2" aria-label="任务与可信结果">
      <header>
        <h3>任务与可信结果</h3>
        <button type="button" disabled={pending() || props.disabled} onClick={() => void resetContext()}>
          重置任务上下文
        </button>
        <button type="button" onClick={() => setEpoch((x) => x + 1)} disabled={pending()}>
          刷新
        </button>
      </header>
      <ErrorLine message={error()} />
      <Show when={agentValue()}>
        {(agent) => (
          <div class="trusted-task">
            <strong>
              {agent().id === "theft-assistant" ? "盗窃资料助手" : "涉赌资料助手"} · {agent().version}
            </strong>
            <dl>
              <For each={Object.entries(taskLabels)}>
                {([key, title]) => (
                  <div>
                    <dt>{title}</dt>
                    <dd>{label(taskValue()[key])}</dd>
                  </div>
                )}
              </For>
              <div>
                <dt>数据环境</dt>
                <dd>{label(result()?.data_environment)}</dd>
              </div>
            </dl>
          </div>
        )}
      </Show>
      <Show when={ticket()?.status === "pending"}>
        <fieldset disabled={pending() || props.disabled}>
          <legend>{ticket()?.question}</legend>
          <For each={ticket()?.options}>
            {(item) => (
              <label class="trusted-option">
                <input
                  type="radio"
                  name={`clarification-${ticket()?.clarification_id}`}
                  checked={option() === item.id}
                  onChange={() => setOption(item.id)}
                />
                {item.label}
              </label>
            )}
          </For>
          <Button onClick={() => void decide()} disabled={!option()}>
            确认对象
          </Button>
          <Button variant="ghost" onClick={() => void decide(true)}>
            取消确认
          </Button>
          <p>确认对象不会自动查询资料。</p>
        </fieldset>
      </Show>
      <Show when={resume()}>
        <div role="status" class="trusted-resume">
          对象已确认，尚未查询。
          <Button
            disabled={pending() || props.disabled}
            onClick={() => {
              setResume(undefined)
              props.onContinue()
            }}
          >
            继续查询
          </Button>
        </div>
      </Show>
      <Show when={result()}>
        {(value) => (
          <>
            <Show when={value().version === "legacy"}>
              <p class="trusted-gap">Legacy 历史结果：原结果仍可阅读，本页不从历史模型文字补造可信结论。</p>
            </Show>
            <Show when={value().version === "2.0"}>
              <p class={`trusted-usage ${value().data_usage?.status}`} role="status">
                {usageLabels[value().data_usage?.status ?? ""] ?? "查询状态无法确认"}
              </p>
              <ul aria-label="分项资料状态"><For each={value().data_usage?.modules??[]}>{item=><li>{label(item.module)}：{item.response_confirmed?"已取得有效响应":({unknown:"结果未确认",pending:"处理中",rejected:"资料暂不可采用",not_started:"尚未查询"} as Record<string,string>)[item.status]??"尚无有效响应"}</li>}</For></ul>
              <Show when={value().status === "pending"}>
                <p>执行尚未结束，最终可信结果尚未保存。</p>
              </Show>
              <Show when={value().status !== "pending"}>
                <For
                  each={[
                    { kind: "fact", title: "已核验事实" },
                    { kind: "computed", title: "确定性计算" },
                    { kind: "gap", title: "资料缺口" },
                  ]}
                >
                  {(group) => (
                    <section>
                      <h4>{group.title}</h4>
                      <Show
                        when={value().claims?.some((c) => c.type === group.kind)}
                        fallback={
                          group.kind === "gap" && value().missing?.length ? null : (
                            <p>当前结果未提供，不能解释为没有发生。</p>
                          )
                        }
                      >
                        <ul>
                          <For each={value().claims?.filter((c) => c.type === group.kind)}>
                            {(claim) => (
                              <li>
                                <button type="button" class="trusted-claim" onClick={() => setSource(claim)}>
                                  {claim.statement}
                                  <span>查看依据</span>
                                </button>
                              </li>
                            )}
                          </For>
                        </ul>
                      </Show>
                      <Show when={group.kind === "gap"}>
                        <ul>
                          <For each={value().missing}>{(gap) => <li>{gap}</li>}</For>
                        </ul>
                      </Show>
                    </section>
                  )}
                </For>
                <section>
                  <h4>待核验来源记录</h4>
                  <p>来源记录不会自动成为已核验结论。</p>
                  <For each={value().records}>
                    {(record) => (
                      <details>
                        <summary>
                          {label(record.record_id)} · {label(record.module)}
                        </summary>
                        <dl>
                          <For each={Object.entries(record)}>
                            {([key, item]) => (
                              <div>
                                <dt>{fieldLabels[key] ?? key}</dt>
                                <dd>{label(item)}</dd>
                              </div>
                            )}
                          </For>
                        </dl>
                      </details>
                    )}
                  </For>
                </section>
                <section class={`trusted-narrative ${value().narrative?.status}`}>
                  <Show when={value().answer} fallback={<>
                    <h4>模型辅助说明</h4>
                    <strong>{narrativeLabels[value().narrative?.status ?? ""] ?? "状态无法确认"}</strong>
                    <p>{value().narrative?.text ?? "尚未生成说明。"}</p>
                    <For each={value().narrative?.conflicts}>{(item) => <p>{item.message}</p>}</For>
                    <small>此项检查不代替对所有自然语言语义的人工复核。</small>
                  </>}>
                    <h4>中文事实说明</h4>
                    <Show when={controlledAnswer(value())} fallback={<p>当前说明版本暂不受支持，请查看已有事实卡片。</p>}>
                      <p>{value().answer?.summary}</p>
                      <ul><For each={value().answer?.items}>{item => <li>{item.text}<small> 来源：{item.source_ids.join("、") || "本次已确认查询统计"}</small></li>}</For></ul>
                      <For each={value().answer?.missing}>{item => <p>{item}</p>}</For>
                      <For each={value().answer?.next_steps}>{item => <p>{item}</p>}</For>
                    </Show>
                  </Show>
                </section>
                <section>
                  <h4>来源与执行过程</h4>
                <ol><For each={props.events??[]}>{event=><li>{event.name} · {({completed:"已完成",failed:"失败",rejected:"已拒绝",cancelled:"已取消",running:"执行中",pending:"等待处理"} as Record<string,string>)[event.status]??"状态待确认"} · {event.completed_at??"—"}</li>}</For></ol>
                  <p>执行编号：{value().run_id}</p>
                  <p>结果时间：{value().generated_at}</p>
                  <dl>
                    <For each={Object.entries(value().versions ?? {})}>
                      {([key, item]) => (
                        <div>
                          <dt>{fieldLabels[key] ?? key}</dt>
                          <dd>{label(item)}</dd>
                        </div>
                      )}
                    </For>
                  </dl>
                  <Button variant="ghost" onClick={() => void exportReport()}>
                    导出 HTML 报告
                  </Button>
                  <p>下载后用浏览器打开，通过“打印 → 另存为 PDF”导出同一份报告。</p>
                </section>
              </Show>
            </Show>
          </>
        )}
      </Show>
      <Show when={source()}>
        {(claim) => (
          <Modal title="来源详情" onClose={() => setSource(undefined)}>
            <p>{claim().statement}</p>
            <dl>
              <dt>Claim</dt>
              <dd>{claim().claim_id}</dd>
              <dt>来源执行</dt>
              <dd>{claim().source_run_id}</dd>
              <dt>完整性</dt>
              <dd>{usageLabels[result()?.data_usage?.status ?? ""] ?? "未知"}</dd>
              <dt>数据环境</dt>
              <dd>{label(result()?.data_environment)}</dd>
            </dl>
            <For each={claim().source_ids}>
              {(id) => (
                <section>
                  <h4>{id}</h4>
                  <For each={result()?.records?.filter((r) => r.record_id === id)}>
                    {(record) => (
                      <dl>
                        <For each={Object.entries(record)}>
                          {([key, item]) => (
                            <div>
                              <dt>{fieldLabels[key] ?? key}</dt>
                              <dd>{label(item)}</dd>
                            </div>
                          )}
                        </For>
                      </dl>
                    )}
                  </For>
                </section>
              )}
            </For>
            <dl>
              <For each={Object.entries(result()?.versions ?? {})}>
                {([key, item]) => (
                  <div>
                    <dt>{fieldLabels[key] ?? key}</dt>
                    <dd>{label(item)}</dd>
                  </div>
                )}
              </For>
            </dl>
          </Modal>
        )}
      </Show>
    </section>
  )
}
