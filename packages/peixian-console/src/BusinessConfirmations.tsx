import { createEffect, createMemo, createSignal, For, Index, onCleanup, Show } from "solid-js"
import { list, post, safeMessage } from "./api"
import { Button, ErrorLine, Icon } from "./components"
import { useConsole } from "./context"
import { useResourceRefresh } from "./resource-refresh"

type Question = {
  question: string
  header: string
  options: { label: string; description?: string }[]
  multiple?: boolean
  custom?: boolean
}
export type Pending = { id: string; sessionID: string; description?: string; questions?: Question[] }

export function QuestionForm(props: { request: () => Pending; busy: boolean; answer: (answers?: string[][]) => void; title?: string; rejectLabel?: string }) {
  const [selected, setSelected] = createSignal<string[][]>([])
  const [custom, setCustom] = createSignal<string[]>([])
  const [customEnabled, setCustomEnabled] = createSignal<boolean[]>([])
  const questionID = createMemo(() => props.request().id)
  createEffect(() => {
    questionID()
    setSelected([])
    setCustom([])
    setCustomEnabled([])
  })
  const questions = () => props.request().questions ?? []
  const answers = () =>
    questions().map((question, index) => [
      ...(selected()[index] ?? []),
      ...(question.custom !== false && (customEnabled()[index] || !(question.options?.length)) && custom()[index]?.trim()
        ? [custom()[index].trim()]
        : []),
    ])
  const valid = () => questions().length > 0 && answers().every((answer) => answer.length > 0)
  function choose(index: number, value: string, multiple?: boolean) {
    setSelected((current) => {
      const next = [...current]
      next[index] = multiple
        ? (next[index] ?? []).includes(value)
          ? next[index].filter((item) => item !== value)
          : [...(next[index] ?? []), value]
        : [value]
      return next
    })
    if (!multiple)
      setCustomEnabled((current) => {
        const next = [...current]
        next[index] = false
        return next
      })
  }
  return (
    <form
      class="confirmation-card"
      onSubmit={(event) => {
        event.preventDefault()
        if (valid()) props.answer(answers())
      }}
    >
      <div class="confirmation-title">
        <Icon name="chat" size={18} />
        <strong>{props.title ?? "需要补充信息"}</strong>
      </div>
      <Index each={questions()}>
        {(question, index) => (
          <fieldset class="question-group">
            <legend>{safeMessage(question().header || "补充信息")}</legend>
            <p>{safeMessage(question().question)}</p>
            <div class="question-options">
              <For each={question().options ?? []}>
                {(option) => (
                  <label class="question-option">
                    <input
                      type={question().multiple ? "checkbox" : "radio"}
                      name={props.request().id + "-" + index}
                      disabled={props.busy}
                      checked={(selected()[index] ?? []).includes(option.label)}
                      onChange={() => choose(index, option.label, question().multiple)}
                    />
                    <span>
                      <strong>{safeMessage(option.label)}</strong>
                      <Show when={option.description}>
                        <small>{safeMessage(option.description)}</small>
                      </Show>
                    </span>
                  </label>
                )}
              </For>
              <Show when={question().custom !== false && !(question().options?.length)}>
                <textarea
                  aria-label={safeMessage(question().header || "补充信息")}
                  value={custom()[index] ?? ""}
                  maxlength={1600}
                  rows={2}
                  required
                  disabled={props.busy}
                  placeholder="请输入你的补充说明"
                  onInput={(event) => setCustom((current) => { const next = [...current]; next[index] = event.currentTarget.value; return next })}
                />
              </Show>
              <Show when={question().custom !== false && !!question().options?.length}>
                <label class="question-option">
                  <input
                    type={question().multiple ? "checkbox" : "radio"}
                    name={props.request().id + "-" + index}
                    disabled={props.busy}
                    checked={!!customEnabled()[index]}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked
                      setCustomEnabled((current) => {
                        const next = [...current]
                        next[index] = checked
                        return next
                      })
                      if (!question().multiple)
                        setSelected((current) => {
                          const next = [...current]
                          next[index] = []
                          return next
                        })
                    }}
                  />
                  <span>
                    <strong>自行填写</strong>
                  </span>
                </label>
                <Show when={customEnabled()[index]}>
                  <textarea
                    aria-label={safeMessage(question().header || "补充信息") + " · 自行填写"}
                    value={custom()[index] ?? ""}
                    maxlength={1600}
                    rows={2}
                    required
                    disabled={props.busy}
                    placeholder="请输入你的补充说明"
                    onInput={(event) => {
                      const value = event.currentTarget.value
                      setCustom((current) => {
                        const next = [...current]
                        next[index] = value
                        return next
                      })
                    }}
                  />
                </Show>
              </Show>
            </div>
            <Show when={question().multiple}>
              <small class="muted">可以选择多项</small>
            </Show>
          </fieldset>
        )}
      </Index>
      <div class="confirmation-actions">
        <Button type="button" disabled={props.busy} onClick={() => props.answer()}>
          {props.rejectLabel ?? "暂不回答"}
        </Button>
        <Button type="submit" variant="primary" busy={props.busy} disabled={!valid()}>
          提交回答
        </Button>
      </div>
    </form>
  )
}

export default function BusinessConfirmations(props: {
  sessionID?: string
  available: boolean
  canContinue?: boolean
  onAnswered: () => void
}) {
  const app = useConsole()
  const [questions, setQuestions] = createSignal<Pending[]>([])
  const [permissions, setPermissions] = createSignal<Pending[]>([])
  const [working, setWorking] = createSignal("")
  const [error, setError] = createSignal("")
  let generation = 0
  let identity = ""
  async function refresh() {
    const sessionID = props.sessionID
    const current = ++generation
    if (!sessionID) {
      setQuestions([])
      setPermissions([])
      setError("")
      return
    }
    if (!props.available) return
    const result = await Promise.allSettled([list<Pending>("/questions"), list<Pending>("/permissions")])
    if (current !== generation || props.sessionID !== sessionID || !props.available) return
    const matching = (items: Pending[]) => items.filter((item) => item.sessionID === sessionID)
    if (result[0].status === "fulfilled") setQuestions(matching(result[0].value))
    if (result[1].status === "fulfilled") setPermissions(matching(result[1].value))
    setError(result.some((item) => item.status === "rejected") ? "暂时无法读取待确认事项，请稍后重试。" : "")
  }
  const requestRefresh = useResourceRefresh(["permissions", "questions"], refresh, 4000)
  createEffect(() => {
    const next = app.user().id + ":" + (props.sessionID ?? "")
    if (identity !== next || app.user().runtime?.security_blocked || app.user().runtime?.recovery_required) {
      setQuestions([])
      setPermissions([])
      setError("")
      identity = next
    }
    props.available
    generation++
    void requestRefresh()
  })
  onCleanup(() => {
    generation++
  })
  async function reply(id: string, kind: "questions" | "permissions", value?: string[][] | "once" | "reject") {
    if (!props.available || props.canContinue === false) return
    const replyIdentity = identity
    setWorking(id)
    setError("")
    try {
      await post(
        "/" +
          kind +
          "/" +
          encodeURIComponent(id) +
          (kind === "questions" && value === undefined ? "/reject" : "/reply"),
        kind === "questions" ? (value === undefined ? {} : { answers: value }) : { reply: value },
      )
      if (replyIdentity !== identity) return
      if (kind === "questions") setQuestions((current) => current.filter((item) => item.id !== id))
      else setPermissions((current) => current.filter((item) => item.id !== id))
      app.notify(value === undefined || value === "reject" ? "已取消这项请求。" : "已提交，助手将继续处理。")
      props.onAnswered()
      await refresh()
    } catch (error) {
      if (replyIdentity !== identity) return
      setError(safeMessage((error as Error).message))
    } finally {
      setWorking("")
    }
  }
  return (
    <Show when={props.sessionID && (questions().length || permissions().length || error())}>
      <section class="business-confirmations" aria-label="待确认事项">
        <ErrorLine message={error()} />
        <For each={questions().map((item) => item.id)}>
          {(id) => (
            <QuestionForm
              request={() => questions().find((item) => item.id === id)!}
              busy={working() === id || props.canContinue === false}
              answer={(answers) => void reply(id, "questions", answers)}
            />
          )}
        </For>
        <For each={permissions()}>
          {(item) => (
            <div class="confirmation-card">
              <div class="confirmation-title">
                <Icon name="shield" size={18} />
                <strong>请确认本次操作</strong>
              </div>
              <p>{safeMessage(item.description, "模型需要你的确认才能继续。")}</p>
              <div class="confirmation-actions">
                <Button disabled={!!working() || props.canContinue === false} onClick={() => void reply(item.id, "permissions", "reject")}>
                  拒绝
                </Button>
                <Button
                  variant="primary"
                  busy={working() === item.id}
                  disabled={!!working() || props.canContinue === false}
                  onClick={() => void reply(item.id, "permissions", "once")}
                >
                  仅允许本次
                </Button>
              </div>
            </div>
          )}
        </For>
      </section>
    </Show>
  )
}
