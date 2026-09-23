import { expect, test } from "bun:test"
import { toolTraceStatus } from "./tool-trace-status"
test("terminal failures do not remain running", () => {
  expect(toolTraceStatus([{ state: { status: "error" } }])).toBe("failed")
  expect(toolTraceStatus([{ execution: { status: "completed" } }, { state: { status: "error" } }])).toBe("failed")
  expect(toolTraceStatus([{ state: { status: "running" } }, { state: { status: "error" } }])).toBe("running")
  expect(toolTraceStatus([{ state: { status: "completed" } }])).toBe("completed")
  expect(toolTraceStatus([{ state: { status: "cancelled" } }])).toBe("cancelled")
})
