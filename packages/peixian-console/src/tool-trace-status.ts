export function toolTraceStatus(parts: { execution?: { status?: string }; state?: { status?: string } }[]) {
  const states = parts.map((part) => part.execution?.status ?? part.state?.status)
  if (states.some((state) => state === "running" || state === "pending")) return "running"
  if (states.some((state) => state === "error" || state === "failed")) return "failed"
  if (states.some((state) => state === "cancelled")) return "cancelled"
  if (states.length && states.every((state) => state === "completed")) return "completed"
  return "reconciling"
}
