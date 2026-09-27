type TracePart = { execution?: { status?: string }; state?: { status?: string; error?: string } }
type ToolFailure = { code?: unknown; message?: unknown; stage?: unknown; dispatch_status?: unknown }

export function toolFailure(part: TracePart): ToolFailure | undefined {
  const raw = typeof part.state?.error === "string" ? part.state.error : ""
  if (!raw.includes("{")) return undefined
  try {
    const parsed = JSON.parse(raw.slice(raw.indexOf("{")))
    return parsed && typeof parsed === "object" ? parsed : undefined
  } catch {
    return undefined
  }
}

export function toolFailureMessage(part: TracePart) {
  const message = toolFailure(part)?.message
  return typeof message === "string" && message ? message : part.state?.error
}

// Precheck rejections never reached the supplier; they are not plugin failures.
export function toolPartStatus(part: TracePart) {
  const status = part.execution?.status ?? part.state?.status
  if (status !== "failed" && status !== "error") return status
  const failure = toolFailure(part)
  if (failure?.code === "provider_rows_limit") return "rows_limit"
  if (failure?.stage === "precheck" && failure?.dispatch_status === "not_dispatched") return "not_executed"
  return status
}

export function toolTraceStatus(parts: TracePart[]) {
  const states = parts.map(toolPartStatus)
  if (states.some((state) => state === "running" || state === "pending")) return "running"
  if (states.some((state) => state === "error" || state === "failed")) return "failed"
  if (states.some((state) => state === "not_executed" || state === "rows_limit")) return "partial"
  if (states.some((state) => state === "cancelled")) return "cancelled"
  if (states.length && states.every((state) => state === "completed")) return "completed"
  return "reconciling"
}
