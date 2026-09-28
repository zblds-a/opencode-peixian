import { expect, test } from "bun:test"
import { parseLive, type AnswerSegmentNotice } from "../src/events"
import { applyLive, fromPage, needsBackfill, withLive } from "../src/live-answer"
import type { Message } from "../src/types"

const base = { type: "answer.segment" as const, session_id: "s1", run_id: "r1", final: false }
const segment = (sequence: number, extra: Partial<AnswerSegmentNotice>): AnswerSegmentNotice => ({ ...base, part_id: `part_delivery_r1_${sequence}`, sequence, display_kind: "source_answer", text: `来源${sequence}`, ...extra })

test("only versioned live notices with safe identifiers are accepted", () => {
  const ok = parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}), version: "live-push-v1" }) })
  expect(ok?.type).toBe("answer.segment")
  expect(parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}) }) })).toBeUndefined()
  expect(parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}), version: "live-push-v1", run_id: "../x" }) })).toBeUndefined()
  expect(parseLive({ event: "change", data: JSON.stringify({ type: "updated", resources: ["messages"] }) })).toBeUndefined()
  const progress = parseLive({ event: "change", data: JSON.stringify({ type: "run.progress", version: "live-push-v1", session_id: "s1", run_id: "r1", phase: "thinking", label: "正在分析问题" }) })
  expect(progress).toEqual({ type: "run.progress", session_id: "s1", run_id: "r1", phase: "thinking", label: "正在分析问题" })
})

test("final sections render as one part and yield to the persisted message", () => {
  let state = applyLive(undefined, segment(1, { message_id: "msg_delivery" }))
  for (const [index, text] of ["## 结论\n\n", "### 甲\n\n", "### 乙\n"].entries()) {
    state = applyLive(state, segment(2 + index, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index, count: 3, text }))
  }
  const user: Message = { info: { id: "msg_u", role: "user" }, parts: [{ type: "text", text: "问题" }] }
  const shown = withLive([user], state, "msg_u")
  expect(shown.map((item) => item.info.id)).toEqual(["msg_u", "msg_delivery", "msg_a"])
  expect(shown[2].parts[0].text).toBe("## 结论\n\n### 甲\n\n### 乙\n")
  expect(shown[2].info.parentID).toBe("msg_u")
  const persisted: Message = { info: { id: "msg_a", role: "assistant", run_id: "r1" }, parts: [{ id: "part_answer_r1", type: "text", text: "## 结论\n\n### 甲\n\n### 乙\n" }] }
  const replaced = withLive([user, persisted], state, "msg_u")
  expect(replaced.find((item) => item.info.id === "msg_a")?.parts.length).toBe(1)
})

test("a missing middle section stops the joined text instead of splicing", () => {
  let state = applyLive(undefined, segment(1, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index: 0, text: "A" }))
  state = applyLive(state, segment(3, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index: 2, text: "C" }))
  expect(withLive([], state)[0].parts[0].text).toBe("A")
  expect(needsBackfill(state, segment(3, { index: 2 }))).toBe(true)
  const filled = fromPage(state, { items: [{ sequence: 2, part_id: "part_answer_r1", display_kind: "final_answer", text: "B", index: 1 }] }, "msg_a")
  expect(withLive([], filled)[0].parts[0].text).toBe("ABC")
})

test("oversized notices without text request a backfill and never overwrite text", () => {
  const state = applyLive(undefined, segment(1, {}))
  expect(needsBackfill(state, segment(1, { text: undefined, truncated: true }))).toBe(true)
  expect(applyLive(state, segment(1, { text: undefined, truncated: true })).segments[0].text).toBe("来源1")
  expect(needsBackfill({ ...state, segments: [] }, segment(1, {}))).toBe(false)
})
