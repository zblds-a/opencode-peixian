export const resources = [
  "messages",
  "runs",
  "sessions",
  "files",
  "models",
  "skills",
  "plugins",
  "runtime",
  "permissions",
  "questions",
] as const
export type Resource = (typeof resources)[number]
export type Change = { resources: Resource[]; session_id?: string }
export type ServerEvent = { event: string; data: string }

export function parseChange(event: ServerEvent): Change | undefined {
  if (event.event !== "change") return
  try {
    const data = JSON.parse(event.data)
    if (data?.type === "resync_required") return { resources: [...resources] }
    if (!data || data.type !== "updated") return
    const names = data.resources === undefined ? ["messages", "sessions"] : data.resources
    if (!Array.isArray(names)) return
    return {
      resources: [...new Set(names.filter((name): name is Resource => resources.includes(name)))],
      ...(typeof data.session_id === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(data.session_id)
        ? { session_id: data.session_id }
        : {}),
    }
  } catch {
    return
  }
}

export type AnswerSegmentNotice = {
  type: "answer.segment"
  session_id: string
  run_id: string
  message_id?: string
  part_id: string
  sequence: number
  display_kind: "source_answer" | "final_answer"
  final: boolean
  index?: number
  count?: number
  text?: string
  truncated?: boolean
}
export type RunProgressNotice = { type: "run.progress"; session_id: string; run_id: string; phase: string; label: string; status?: string }
export type LiveNotice = AnswerSegmentNotice | RunProgressNotice

const identifier = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value)

// Only pushed content from the controlled answer pipeline is accepted; anything else is ignored.
export function parseLive(event: ServerEvent): LiveNotice | undefined {
  if (event.event !== "change") return
  try {
    const data = JSON.parse(event.data)
    if (!data || data.version !== "live-push-v1" || !identifier(data.session_id) || !identifier(data.run_id)) return
    if (data.type === "run.progress") {
      if (typeof data.phase !== "string" || typeof data.label !== "string" || data.label.length > 200) return
      return { type: "run.progress", session_id: data.session_id, run_id: data.run_id, phase: data.phase, label: data.label, ...(typeof data.status === "string" ? { status: data.status } : {}) }
    }
    if (data.type !== "answer.segment") return
    if (!identifier(data.part_id) || !Number.isInteger(data.sequence) || data.sequence < 1) return
    if (data.display_kind !== "source_answer" && data.display_kind !== "final_answer") return
    if (data.text !== undefined && typeof data.text !== "string") return
    return {
      type: "answer.segment",
      session_id: data.session_id,
      run_id: data.run_id,
      ...(identifier(data.message_id) ? { message_id: data.message_id } : {}),
      part_id: data.part_id,
      sequence: data.sequence,
      display_kind: data.display_kind,
      final: data.final === true,
      ...(Number.isInteger(data.index) ? { index: data.index } : {}),
      ...(Number.isInteger(data.count) ? { count: data.count } : {}),
      ...(typeof data.text === "string" ? { text: data.text } : {}),
      ...(data.truncated === true ? { truncated: true } : {}),
    }
  } catch {
    return
  }
}

// Stream decoding preserves UTF-8 code points, CRLF boundaries and SSE multiline data.
export async function readEvents(
  stream: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  receive: (event: ServerEvent) => void,
) {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = "",
    event = "",
    data: string[] = [],
    size = 0
  const line = (value: string) => {
    if (!value) {
      if (data.length) receive({ event: event || "message", data: data.join("\n") })
      event = ""
      data = []
      size = 0
      return
    }
    if (value.startsWith(":")) return
    const colon = value.indexOf(":")
    const field = colon < 0 ? value : value.slice(0, colon)
    const content = colon < 0 ? "" : value.slice(colon + 1).replace(/^ /, "")
    if (field === "event") event = content
    if (field === "data") {
      data.push(content)
      size += content.length
    }
    if (size > 262144) throw new Error("Event exceeds receive limit")
  }
  const consume = (final = false) => {
    while (buffer.length && !signal.aborted) {
      const end = buffer.search(/[\r\n]/)
      if (end < 0 || (!final && end === buffer.length - 1 && buffer[end] === "\r")) break
      const width = buffer[end] === "\r" && buffer[end + 1] === "\n" ? 2 : 1
      line(buffer.slice(0, end))
      buffer = buffer.slice(end + width)
    }
    if (buffer.length > 262144) throw new Error("Event line exceeds receive limit")
  }
  const cancel = () => {
    void reader.cancel().catch(() => {})
  }
  signal.addEventListener("abort", cancel, { once: true })
  try {
    while (!signal.aborted) {
      const next = await reader.read()
      if (signal.aborted) break
      buffer += next.done ? decoder.decode() : decoder.decode(next.value, { stream: true })
      consume(next.done)
      if (next.done) break // An unterminated event is intentionally not dispatched.
    }
  } finally {
    signal.removeEventListener("abort", cancel)
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export function retryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value) return
  if (/^\d+(\.\d+)?$/.test(value.trim())) return Math.max(0, Number(value) * 1000)
  const date = Date.parse(value)
  return Number.isFinite(date) ? Math.max(0, date - now) : undefined
}
export function reconnectDelay(attempt: number, random = Math.random) {
  return [1000, 2000, 4000, 8000, 15000][Math.min(attempt, 4)] + Math.floor(random() * 250)
}
export function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const finish = () => {
      clearTimeout(timer)
      signal.removeEventListener("abort", finish)
      resolve()
    }
    const timer = setTimeout(finish, Math.min(milliseconds, 2147483647))
    signal.addEventListener("abort", finish, { once: true })
  })
}

type EventOptions = {
  url: string
  signal: AbortSignal
  onEvent: (event: ServerEvent) => void
  onOpen: () => void
  onDisconnected: () => void
  onUnauthorized: () => void
  fetcher?: typeof fetch
  wait?: typeof abortableDelay
  random?: () => number
}
export async function connectEvents(options: EventOptions) {
  const { signal } = options
  let attempt = 0
  while (!signal.aborted) {
    let delay: number | undefined
    let body: ReadableStream<Uint8Array> | null | undefined
    const opened = Date.now()
    try {
      const response = await (options.fetcher ?? fetch)(options.url, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: { Accept: "text/event-stream" },
        signal,
      })
      body = response.body
      if (signal.aborted) {
        await response.body?.cancel()
        break
      }
      if (response.status === 401) {
        await response.body?.cancel()
        options.onUnauthorized()
        return
      }
      if (response.status === 429 || response.status === 503) delay = retryAfter(response.headers.get("Retry-After"))
      if (!response.ok || !response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
        await response.body?.cancel()
        throw new Error("Event connection unavailable")
      }
      options.onOpen()
      await readEvents(response.body, signal, options.onEvent)
      if (Date.now() - opened >= 10000) attempt = 0
    } catch {
      // A reconnect reads history; it must never replay a model request.
    } finally {
      // onOpen can fail before readEvents takes ownership of the reader.
      // Reconnecting must still close the previous HTTP subscription.
      if (body && !body.locked) await body.cancel().catch(() => {})
    }
    if (signal.aborted) break
    options.onDisconnected()
    await (options.wait ?? abortableDelay)(Math.max(delay ?? 0, reconnectDelay(attempt++, options.random)), signal)
  }
}

export function createChangeBus() {
  const listeners = new Map<Resource, Set<(change: Change) => void>>()
  const live = new Set<(notice: LiveNotice) => void>()
  return {
    subscribeLive(callback: (notice: LiveNotice) => void) {
      live.add(callback)
      return () => {
        live.delete(callback)
      }
    },
    publishLive(notice: LiveNotice) {
      for (const callback of [...live]) callback(notice)
    },
    subscribe(resource: Resource, callback: (change: Change) => void) {
      const group = listeners.get(resource) ?? new Set()
      listeners.set(resource, group)
      group.add(callback)
      return () => {
        group.delete(callback)
      }
    },
    publish(change: Change) {
      const callbacks = new Set(change.resources.flatMap((resource) => [...(listeners.get(resource) ?? [])]))
      for (const callback of callbacks) callback(change)
    },
  }
}
