import { expect, test } from "bun:test"
import { toolFailureMessage, toolPartStatus, toolTraceStatus } from "../src/tool-trace-status"

const failed = (body: object) => ({ state: { status: "error", error: `Error: ${JSON.stringify(body)}` } })

test("precheck rejection is not a plugin failure", () => {
  const part = failed({ code: "time_range_limit", message: "时间范围超出接口允许的上限；尚未访问资料接口。单次时间跨度上限 31 天", stage: "precheck", dispatch_status: "not_dispatched" })
  expect(toolPartStatus(part)).toBe("not_executed")
  expect(toolFailureMessage(part)).toContain("31 天")
  expect(toolTraceStatus([part])).toBe("partial")
})

test("supplier rows limit is labelled separately", () => {
  const part = failed({ code: "provider_rows_limit", message: "结果过多", stage: "dispatch", dispatch_status: "dispatched" })
  expect(toolPartStatus(part)).toBe("rows_limit")
  expect(toolTraceStatus([{ state: { status: "completed" } }, part])).toBe("partial")
})

test("other failures stay failed", () => {
  const part = failed({ code: "tool_execution_unavailable", message: "x", stage: "dispatch", dispatch_status: "dispatched" })
  expect(toolPartStatus(part)).toBe("error")
  expect(toolTraceStatus([part])).toBe("failed")
  expect(toolPartStatus({ state: { status: "error", error: "plain" } })).toBe("error")
  expect(toolFailureMessage({ state: { status: "error", error: "plain" } })).toBe("plain")
})
