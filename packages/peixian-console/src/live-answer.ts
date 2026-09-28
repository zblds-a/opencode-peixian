import type { AnswerSegmentNotice, LiveNotice } from "./events"
import type { Message, Part } from "./types"

export type LiveAnswer = { sessionID: string; runID: string; progress?: string; segments: AnswerSegmentNotice[] }

export function applyLive(current: LiveAnswer | undefined, notice: LiveNotice): LiveAnswer {
  const base = current && current.runID === notice.run_id && current.sessionID === notice.session_id
    ? current
    : { sessionID: notice.session_id, runID: notice.run_id, segments: [] }
  if (notice.type === "run.progress") return base.progress === notice.label ? base : { ...base, progress: notice.label }
  const existing = base.segments.find((item) => item.sequence === notice.sequence)
  if (existing && (existing.text !== undefined || notice.text === undefined)) return base
  const segments = [...base.segments.filter((item) => item.sequence !== notice.sequence), notice].sort((a, b) => a.sequence - b.sequence)
  return { ...base, segments }
}

// A gap or a text-less (oversized) notice means the replayable segment log must be read.
export function needsBackfill(state: LiveAnswer, notice: AnswerSegmentNotice) {
  if (notice.text === undefined) return true
  const before = state.segments.filter((item) => item.sequence < notice.sequence)
  return before.length !== notice.sequence - 1 || before.some((item) => item.text === undefined)
}

type SegmentPage = {
  message_id?: string
  items: { sequence: number; part_id: string; display_kind: string; text: string; index?: number; count?: number }[]
}

export function fromPage(state: LiveAnswer, page: SegmentPage, finalMessageID?: string): LiveAnswer {
  let next = state
  for (const item of page.items) {
    if (item.display_kind !== "source_answer" && item.display_kind !== "final_answer") continue
    const messageID = item.display_kind === "final_answer" ? finalMessageID : page.message_id
    next = applyLive(next, {
      type: "answer.segment",
      session_id: state.sessionID,
      run_id: state.runID,
      ...(messageID ? { message_id: messageID } : {}),
      part_id: item.part_id,
      sequence: item.sequence,
      display_kind: item.display_kind,
      final: false,
      ...(item.index !== undefined ? { index: item.index } : {}),
      ...(item.count !== undefined ? { count: item.count } : {}),
      text: item.text,
    })
  }
  return next
}

// Pushed parts are shown until /messages returns the same part id; final-answer sections
// are only joined while contiguous so a missing section never produces spliced text.
export function withLive(messages: Message[], state: LiveAnswer | undefined, parentID?: string): Message[] {
  if (!state?.segments.length) return messages
  const known = new Set(messages.flatMap((message) => message.parts.map((part) => part.id)).filter(Boolean))
  const parts = new Map<string, { messageID: string; part: Part }>()
  const nextSection = new Map<string, number>()
  for (const segment of state.segments) {
    if (known.has(segment.part_id) || segment.text === undefined) continue
    const messageID = segment.message_id ?? `live_${state.runID}_${segment.display_kind}`
    if (segment.display_kind === "source_answer") {
      parts.set(segment.part_id, { messageID, part: { id: segment.part_id, type: "text", text: segment.text, display_kind: "source_answer", run_id: state.runID } })
      continue
    }
    const expected = nextSection.get(segment.part_id) ?? 0
    if (expected < 0 || (segment.index ?? expected) !== expected) {
      nextSection.set(segment.part_id, -1)
      continue
    }
    nextSection.set(segment.part_id, expected + 1)
    const entry = parts.get(segment.part_id)
    if (entry) entry.part = { ...entry.part, text: (entry.part.text ?? "") + segment.text }
    else parts.set(segment.part_id, { messageID, part: { id: segment.part_id, type: "text", text: segment.text, display_kind: "final_answer", run_id: state.runID } })
  }
  if (!parts.size) return messages
  const result = [...messages]
  for (const { messageID, part } of parts.values()) {
    const index = result.findIndex((message) => message.info.id === messageID)
    if (index >= 0) result[index] = { ...result[index], parts: [...result[index].parts, part] }
    else result.push({ info: { id: messageID, role: "assistant", run_id: state.runID, parentID: parentID ?? null }, parts: [part] })
  }
  return result
}
