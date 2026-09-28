import assert from "node:assert/strict"
import test from "node:test"
import { MarkdownStreamBuffer } from "../src/stream-markdown.ts"
import { FollowScroll } from "../src/follow-scroll.ts"

const answer = `正文开始。\n\n| 维度 | 主要依据 | 支持来源 |\n| --- | --- | --- |\n| D1 | 张三的记录 | [来源9](#source-abc123)、[来源13](#source-very-long-source-id-1234567890) |\n| D2 | 李四的记录 | [来源14](#source-other-456) |\n\n表格之后的正文。`

test("every character boundary keeps incomplete tables and source anchors out of view", () => {
  const buffer = new MarkdownStreamBuffer()
  for (const character of answer) {
    buffer.append(character)
    const current = buffer.project()
    assert.doesNotMatch(current.text, /\[来源\d+\]\(#source-[^)]*$/)
    assert.doesNotMatch(current.text, /source-(?:abc|very-long|other)(?![A-Za-z0-9-]*\))/)
    assert.doesNotMatch(current.text, /\| D[12] \|[^\n]*$/)
  }
  assert.equal(buffer.project(true).text, answer)
})

test("ordinary columns stream while the source column waits for a complete link", () => {
  const buffer = new MarkdownStreamBuffer()
  buffer.append("| 姓名 | 来源 |")
  assert.deepEqual(buffer.project(), { text: "", pendingTable: true, pendingSource: false })
  buffer.append("\n| --- | --- |\n")
  assert.equal(buffer.project().text, "| 姓名 | 来源 |\n| --- | --- |\n")
  buffer.append("| 张三 | [来源1](#source-ab")
  assert.match(buffer.project().text, /张三/)
  assert.doesNotMatch(buffer.project().text, /来源1|source-ab/)
  assert.equal(buffer.project().pendingTable, false)
  buffer.append("c) |\n")
  assert.match(buffer.project().text, /\| 张三 \| \[来源1\]\(#source-abc\) \|\n$/)
})

test("last row without newline streams safely, commits on normal end, and is withheld on interruption", () => {
  const row = "| 张三 | [来源10](#source-long-id) |"
  const prefix = "| 姓名 | 来源 |\n| --- | --- |\n"
  const buffer = new MarkdownStreamBuffer()
  buffer.append(prefix + row)
  assert.match(buffer.project().text, /张三.*\[来源10\]\(#source-long-id\)/)
  assert.equal(buffer.project(true).text, prefix + row)
  assert.equal(buffer.project(true).text, prefix + row)
  assert.equal(buffer.project(true, true).text, prefix)
})

test("source links appear individually without exposing long ids or changing the visible row shell", () => {
  const buffer = new MarkdownStreamBuffer()
  buffer.append("| 记录摘要 | 来源 |\n| --- | --- |\n| 已查得三条记录 | [来源9](#source-long-id-123)")
  const first = buffer.project().text
  assert.match(first, /已查得三条记录/)
  assert.match(first, /\[来源9\]\(#source-long-id-123\)/)
  buffer.append("、[来源10](#source-other-long")
  const pending = buffer.project().text
  assert.match(pending, /\[来源9\]\(#source-long-id-123\)/)
  assert.doesNotMatch(pending, /来源10|other-long/)
  buffer.append("-id-456) |\n\n表格之后的正文。")
  assert.match(buffer.project().text, /\[来源10\]\(#source-other-long-id-456\)/)
  assert.equal(buffer.project(true).text, "| 记录摘要 | 来源 |\n| --- | --- |\n| 已查得三条记录 | [来源9](#source-long-id-123)、[来源10](#source-other-long-id-456) |\n\n表格之后的正文。")
})

test("escaped pipes and inline code do not create false table placeholders", () => {
  const buffer = new MarkdownStreamBuffer()
  buffer.append("正文中的 \\| 与 `a|b`。")
  assert.equal(buffer.project().pendingTable, false)
  assert.equal(buffer.project(true).text, "正文中的 \\| 与 `a|b`。")
})

test("draft rows keep escaped pipes and inline code inside their original cells", () => {
  const buffer = new MarkdownStreamBuffer()
  buffer.append("| 记录摘要 | 来源 |\n| --- | --- |\n| `a|b` 与 甲\\|乙 | [来源3](#source-long")
  const draft = buffer.project()
  assert.match(draft.text, /`a\|b` 与 甲\\\|乙/)
  assert.doesNotMatch(draft.text, /来源3|source-long/)
  assert.equal(draft.pendingTable, false)
  buffer.append("-id) |\n")
  assert.match(buffer.project().text, /\[来源3\]\(#source-long-id\)/)
})

test("tables without a source column retain complete-row buffering", () => {
  const buffer = new MarkdownStreamBuffer()
  const prefix = "| 姓名 | 数量 |\n| --- | --- |\n"
  buffer.append(prefix + "| 张三 | 2")
  assert.equal(buffer.project().text, prefix)
  buffer.append(" |\n")
  assert.equal(buffer.project().text, prefix + "| 张三 | 2 |\n")
})

test("ordinary bracketed prose is retained and cumulative snapshot resets do not duplicate it", () => {
  const buffer = new MarkdownStreamBuffer()
  buffer.append("说明：[备注]与[来源研究]均为正文。\n")
  assert.equal(buffer.project().text, "说明：[备注]与[来源研究]均为正文。\n")
  buffer.reset("说明：[备注]与[来源研究]均为正文。\n补充。")
  assert.equal(buffer.project(true).text, "说明：[备注]与[来源研究]均为正文。\n补充。")
})

test("content growth preserves follow state; user intent changes it", () => {
  const follow = new FollowScroll()
  assert.equal(follow.scroll(200, false, 100), true)
  follow.wheel(-20, 110)
  assert.equal(follow.following, false)
  assert.equal(follow.scroll(200, false, 120), false)
  assert.equal(follow.scroll(0, false, 500), false)
  follow.wheel(20, 600)
  assert.equal(follow.scroll(0, false, 610), true)
  follow.pause()
  assert.equal(follow.scroll(500, true, 620), false)
  follow.resume()
  assert.equal(follow.following, true)
})
