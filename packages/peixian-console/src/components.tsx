import { createEffect, createMemo, onCleanup, Show } from "solid-js"
import type { JSX } from "solid-js"
import { marked } from "marked"
import DOMPurify from "dompurify"
import { safeMessage } from "./api"
import { operationNote } from "./operation-note"
const icons: Record<string, string> = {
  chat: "M4 4h16v12H9l-5 4V4",
  file: "M6 3h8l4 4v14H6V3m8 0v5h4",
  skill: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3",
  plugin: "M9 3v4H5v5h4v4h5v-4h4V7h-4V3H9",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0-5v3m0 12v3M3 12h3m12 0h3M5.5 5.5l2 2m9 9 2 2m0-13-2 2m-9 9-2 2",
  users: "M9 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6M3 20v-3a6 6 0 0 1 12 0v3m2-15a3 3 0 0 1 0 6m2 3a5 5 0 0 1 2 4v2",
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M18 6 6 18",
  send: "m4 12 16-8-5 16-4-7-7-1Zm7 1 9-9",
  stop: "M6 6h12v12H6z",
  search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15M16 16l5 5",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2m0-14-2 2M7 17l-2 2",
  moon: "M20 15A9 9 0 0 1 9 3a9 9 0 1 0 11 12",
  menu: "M4 6h16M4 12h16M4 18h16",
  logout: "M9 4H4v16h5m5-12 4 4-4 4m-6-4h12",
  arrow: "m9 5 7 7-7 7",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6",
  refresh: "M20 11a8 8 0 1 0-2 7M20 4v7h-7",
  check: "m5 12 4 4L19 6",
  lock: "M6 10h12v11H6V10m3 0V6a3 3 0 0 1 6 0v4",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m0 4v6l4 2",
  dots: "M5 12h.01M12 12h.01M19 12h.01",
  download: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
  trash: "M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7",
  edit: "m4 16 12-12 4 4L8 20H4v-4m10-10 4 4",
  copy: "M8 8h12v12H8V8M4 16V4h12",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3m-4 9 3 3 5-6",
  eye: "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12m10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  "eye-off": "M3 3l18 18M10.6 6.2A11 11 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-2.1 2.8M6.2 6.2C3.4 8.1 2 12 2 12s3.5 6 10 6a10.6 10.6 0 0 0 3.8-.7M9.9 9.9a3 3 0 0 0 4.2 4.2",
}
export function Icon(props: { name: string; size?: number }) {
  return (
    <svg
      width={props.size ?? 20}
      height={props.size ?? 20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.65"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d={icons[props.name] ?? icons.dots} />
    </svg>
  )
}
export function Spinner() {
  return <span class="spinner" aria-label="加载中" />
}
export function Button(
  props: JSX.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "danger" | "ghost"
    busy?: boolean
    icon?: string
  },
) {
  return (
    <button
      {...props}
      class={["button", props.variant ?? "", props.class ?? ""].join(" ")}
      disabled={props.disabled || props.busy}
    >
      <Show when={props.busy} fallback={props.icon ? <Icon name={props.icon} size={17} /> : null}>
        <Spinner />
      </Show>
      {props.children}
    </button>
  )
}
export function Empty(props: { icon?: string; title: string; text?: string; children?: JSX.Element }) {
  return (
    <div class="empty">
      <span class="empty-icon">
        <Icon name={props.icon ?? "file"} size={27} />
      </span>
      <h3>{props.title}</h3>
      <Show when={props.text}>
        <p>{props.text}</p>
      </Show>
      {props.children}
    </div>
  )
}
export function PageHead(props: { eyebrow?: string; title: string; text?: string; children?: JSX.Element }) {
  return (
    <div class="page-head">
      <div>
        <Show when={props.eyebrow}>
          <div class="eyebrow">{props.eyebrow}</div>
        </Show>
        <h1>{props.title}</h1>
        <Show when={props.text}>
          <p>{props.text}</p>
        </Show>
      </div>
      <div class="head-actions">{props.children}</div>
    </div>
  )
}
const statuses: Record<string, [string, string]> = {
  ready: ["已就绪", "good"],
  running: ["运行中", "good"],
  healthy: ["已就绪", "good"],
  enabled: ["已启用", "good"],
  active: ["正常", "good"],
  completed: ["已完成", "good"],
  succeeded: ["已完成", "good"],
  success: ["成功", "good"],
  passed: ["通过", "good"],
  queued: ["等待处理", "pending"],
  pending: ["等待处理", "pending"],
  provisioning: ["准备中", "pending"],
  applying: ["更新中", "pending"],
  updating: ["更新中", "pending"],
  recorded: ["已记录", "muted"],
  starting: ["启动中", "pending"],
  parsing: ["解析中", "pending"],
  busy: ["处理中", "pending"],
  processing: ["处理中", "pending"],
  stopped: ["已暂停", "muted"],
  paused: ["已暂停", "muted"],
  disabled: ["已停用", "muted"],
  failed: ["处理失败", "bad"],
  denied: ["已拒绝", "bad"],
  error: ["异常", "bad"],
  partial: ["部分可用", "warn"],
  no_text: ["未识别到文字", "warn"],
  unsupported: ["暂不支持", "warn"],
  unavailable: ["版本已停用", "warn"],
  unconfigured: ["平台待配置", "warn"],
  draft: ["草稿", "muted"],
}
export function Status(props: { value?: string }) {
  const data = () => statuses[props.value ?? ""] ?? [props.value ? "等待确认" : "未配置", "muted"]
  return (
    <span class={"status " + data()[1]}>
      <span />
      {data()[0]}
    </span>
  )
}
export function Markdown(props: { text: string }) {
  const html = createMemo(() =>
    DOMPurify.sanitize(marked.parse(props.text, { async: false, breaks: true }) as string, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["img", "iframe", "form", "input", "style"],
      FORBID_ATTR: ["style"],
    }),
  )
  return <div class="markdown" innerHTML={html()} />
}
export function Modal(props: {
  title: string
  text?: string
  onClose: () => void
  children: JSX.Element
  wide?: boolean
}) {
  let dialog!: HTMLDialogElement
  createEffect(() => {
    dialog.showModal()
    dialog.querySelector<HTMLElement>("input,textarea,select,button")?.focus()
  })
  const handle = (event: KeyboardEvent) => {
    if (event.key === "Escape") props.onClose()
  }
  document.addEventListener("keydown", handle)
  onCleanup(() => document.removeEventListener("keydown", handle))
  return (
    <dialog
      ref={dialog}
      class={"modal " + (props.wide ? "wide" : "")}
      onCancel={(event) => {
        event.preventDefault()
        props.onClose()
      }}
    >
      <div class="modal-head">
        <div>
          <h2>{props.title}</h2>
          <Show when={props.text}>
            <p>{props.text}</p>
          </Show>
        </div>
        <button class="icon-button" aria-label="关闭对话框" onClick={props.onClose}>
          <Icon name="close" />
        </button>
      </div>
      {props.children}
    </dialog>
  )
}
export function ErrorLine(props: { message?: unknown }) {
  return (
    <Show when={props.message}>
      <div class="error-line" role="alert">
        {safeMessage(props.message)}
      </div>
    </Show>
  )
}
export function Field(props: { label: string; hint?: string; children: JSX.Element; required?: boolean }) {
  return (
    <label class="field">
      <span>
        {props.label}
        <Show when={props.required}>
          <b aria-label="必填"> *</b>
        </Show>
      </span>
      {props.children}
      <Show when={props.hint}>
        <small>{props.hint}</small>
      </Show>
    </label>
  )
}
export function Toggle(props: {
  checked?: boolean
  disabled?: boolean
  onChange: (value: boolean) => void
  label?: string
}) {
  return (
    <label class="toggle-wrap">
      <input
        type="checkbox"
        checked={!!props.checked}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.currentTarget.checked)}
      />
      <span class="toggle" />
      <Show when={props.label}>
        <span>{props.label}</span>
      </Show>
    </label>
  )
}
export function formatSize(value = 0) {
  return value < 1024
    ? value + " B"
    : value < 1024 ** 2
      ? (value / 1024).toFixed(1) + " KB"
      : (value / 1024 ** 2).toFixed(1) + " MB"
}
export function formatDate(value?: string | number) {
  if (!value) return "—"
  const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value)
  return Number.isNaN(date.valueOf())
    ? "—"
    : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}
export function JobNote(props: { value: unknown }) {
  return <p class="notice">{operationNote(props.value)}</p>
}
