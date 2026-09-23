import { expect, test } from "bun:test"
import { clarificationAnswer, clarificationRequest } from "../src/planner-question"
import type { Run } from "../src/types"

test("planner clarification uses the existing question card contract", () => {
  const run = { clarification: { version: "theft-clarification-v1", id: "call-1", missing: ["lon", "lat", "radius_m"] } } as Run
  const request = clarificationRequest(run, "session-1")
  expect(request.questions?.map((item) => item.header)).toEqual(["查询位置", "查询位置", "查询范围"])
  expect(request.questions?.every((item) => item.options.length === 0 && item.custom)).toBe(true)
  expect(clarificationAnswer(run.clarification!.missing, [["116.1"], ["34.2"], ["500"]])).toBe("经度：116.1；纬度：34.2；半径：500 米")
})

test("page, time and source answers retain exact user scope", () => {
  expect(clarificationAnswer(["start", "end", "page", "source"], [["2026-09-01 00:00:00"], ["2026-09-02 00:00:00"], ["2"], ["DEMO-REC-001"]]))
    .toBe("开始时间：2026-09-01 00:00:00；结束时间：2026-09-02 00:00:00；第2页；来源记录编号：DEMO-REC-001")
  expect(() => clarificationAnswer(["start"], [["下周"]])).toThrow()
})

test("broader supplier coverage needs explicit agreement", () => {
  const run = { clarification: { version: "theft-clarification-v1", id: "call-2", missing: ["supported_scope"] } } as Run
  const request = clarificationRequest(run, "session-1")
  expect(request.questions?.[0].custom).toBe(false)
  expect(() => clarificationAnswer(["supported_scope"], [["随便查"]])).toThrow()
  expect(clarificationAnswer(["supported_scope"], [["同意使用上游默认覆盖范围"]])).toBe("同意使用上游默认覆盖范围")
})
