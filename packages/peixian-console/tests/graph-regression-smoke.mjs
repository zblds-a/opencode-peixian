import { chromium } from "playwright"
import assert from "node:assert/strict"

const browser = await chromium.launch({ headless: true, executablePath: "/root/PeiXianDB/.tooling/browsers/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell" })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on("pageerror", (error) => errors.push(error.message))
await page.goto("http://127.0.0.1:4174/dev/graph-preview", { waitUntil: "networkidle" })
await page.locator(".entity-graph-stage").waitFor({ state: "visible" })
await page.waitForTimeout(200)
const pixels = () => page.locator(".entity-graph-stage canvas").evaluateAll((canvases) => canvases.map((canvas) => canvas.toDataURL()).join("|"))
const initial = await pixels()
await page.waitForTimeout(350)
assert.equal(await pixels(), initial, "Graph moves after becoming visible")
await page.screenshot({ path: "/tmp/peixian-graph-regression.png", fullPage: true })
const bounds = await page.locator(".entity-graph-canvas").boundingBox()
assert.ok(bounds)
let edgeCard = false
for (const [x, y] of [[760, 460], [750, 462], [680, 430], [800, 450], [780, 465], [720, 470], [720, 460]]) {
  await page.mouse.move(x, y)
  if (await page.locator(".graph-edge-card").count()) { edgeCard = true; break }
}
assert.ok(edgeCard, "Hovering a relation line should show its business card")
assert.match(await page.locator(".graph-edge-card").textContent(), /关系类型：/)
await page.screenshot({ path: "/tmp/peixian-graph-edge-hover.png", fullPage: true })
await page.mouse.move(bounds.x + 12, bounds.y + 12)
const beforePath = await pixels()
await page.getByRole("button", { name: "高亮路径" }).click()
await page.waitForTimeout(300)
const afterPath = await pixels()
assert.notEqual(afterPath, beforePath, "Path highlight must visibly change the canvas")
const cardLayout = await page.evaluate(() => {
  const shell = document.createElement("div")
  shell.className = "business-shell"
  shell.innerHTML = '<div class="chat-layout"><aside class="insight-sidebar right-panel--clues"><article class="clue-card"><img class="clue-card-icon" alt=""><div class="clue-card-copy"><strong>线索</strong><p>关系摘要</p></div><button class="clue-card-open">查看详情</button></article></aside></div>'
  document.body.append(shell)
  const card = shell.querySelector(".clue-card")
  const button = shell.querySelector(".clue-card-open")
  const position = getComputedStyle(button).position
  const inside = button.getBoundingClientRect().bottom <= card.getBoundingClientRect().bottom
  shell.remove()
  return { position, inside }
})
assert.deepEqual(cardLayout, { position: "static", inside: true })
assert.deepEqual(errors, [])
console.log(JSON.stringify({ stableAfterFirstDisplay: true, edgeHover: true, pathChangesCanvas: true, cardLayout, errors }))
await browser.close()
