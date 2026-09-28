import { createEffect, createSignal, onCleanup, Show, untrack } from "solid-js"
import { Markdown } from "./components"
import { MarkdownStreamBuffer, type StreamProjection } from "./stream-markdown"

// The server publishes change notices and complete text snapshots, not replayable token deltas.
// Preserve the displayed prefix across message refreshes so a remount cannot restart the reveal.
export default function SmoothMarkdown(props: { text: string; live: boolean; complete?: boolean; interrupted?: boolean; cache: Map<string, number>; id: string; onProgress?: () => void; pause?: () => boolean }) {
  const [count, setCount] = createSignal(props.cache.get(props.id) ?? (props.live ? 0 : Array.from(props.text).length))
  const [projection, setProjection] = createSignal<StreamProjection>({ text: "", pendingTable: false, pendingSource: false })
  const buffer = new MarkdownStreamBuffer()
  let consumed = ""
  let frame = 0
  let target = props.text
  let previous = 0
  let fractional = 0
  let lastRender = 0
  createEffect(() => {
    target = props.text
    const characters = Array.from(target)
    const cached = props.cache.get(props.id)
    if (cached === undefined && !props.live) {
      cancelAnimationFrame(frame)
      frame = 0
      setCount(characters.length)
      props.cache.set(props.id, characters.length)
      return
    }
    if (untrack(count) > characters.length) {
      setCount(characters.length)
      props.cache.set(props.id, characters.length)
    }
    const tick = (now: number) => {
      const characters = Array.from(target)
      const pending = characters.length - count()
      if (pending <= 0) { frame = 0; return }
      if (props.pause?.()) {
        previous = now
        fractional = 0
        frame = requestAnimationFrame(tick)
        return
      }
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setCount(characters.length)
        props.cache.set(props.id, characters.length)
        frame = 0
        return
      }
      const elapsed = Math.min(100, previous ? now - previous : 16)
      previous = now
      // Coalesce server snapshots into a visible update about every 70 ms.
      fractional += elapsed * Math.min(180, 55 + pending * 1.1) / 1000
      const increment = Math.floor(fractional)
      if (increment && now - lastRender >= 70) {
        fractional -= increment
        lastRender = now
        const next = Math.min(characters.length, count() + increment)
        setCount(next)
        props.cache.set(props.id, next)
      }
      frame = count() < characters.length ? requestAnimationFrame(tick) : 0
    }
    if (!frame && untrack(count) < characters.length) frame = requestAnimationFrame(tick)
  })
  createEffect(() => {
    const characters = Array.from(props.text)
    const current = characters.slice(0, count()).join("")
    if (current.startsWith(consumed)) buffer.append(current.slice(consumed.length))
    else buffer.reset(current)
    consumed = current
    const next = buffer.project((props.complete || !props.live) && count() >= characters.length, props.interrupted)
    const previous = untrack(projection)
    if (next.text === previous.text && next.pendingTable === previous.pendingTable && next.pendingSource === previous.pendingSource) return
    setProjection(next)
    if (next.text !== previous.text || next.pendingTable !== previous.pendingTable) props.onProgress?.()
  })
  onCleanup(() => cancelAnimationFrame(frame))
  return <div class="smooth-message-text" aria-live="off">
    <Markdown text={projection().text} incremental />
    <Show when={projection().pendingTable && !props.interrupted}><div class="stream-table-pending" role="status">正在整理表格…</div></Show>
    <Show when={props.interrupted}><p class="stream-interrupted">输出已中断，已保留完整内容。</p></Show>
  </div>
}
