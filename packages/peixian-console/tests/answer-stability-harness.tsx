import { createSignal, Show } from "solid-js"
import { render } from "solid-js/web"
import SmoothMarkdown from "../src/SmoothMarkdown"
import { QuestionForm } from "../src/BusinessConfirmations"
import type { StreamProjection } from "../src/stream-markdown"
import "../src/styles.css"
import "../src/chat-dialogue-v2.css"

const [text, setText] = createSignal("")
const [complete, setComplete] = createSignal(false)
const [mounted, setMounted] = createSignal(true)
const [busy, setBusy] = createSignal(false)
const cache = new Map<string, number>()
const projectionCache = new Map<string, StreamProjection>()
const scope = window as Window & { answerHarness: { setText: typeof setText; setComplete: typeof setComplete; setBusy: typeof setBusy; remount: () => void; pauseFollow: () => void; snapshot: () => unknown } }
let following = true
let scroll!: HTMLDivElement
scope.answerHarness = {
  setText,
  setComplete,
  setBusy,
  remount: () => { setMounted(false); queueMicrotask(() => setMounted(true)) },
  pauseFollow: () => { following = false },
  snapshot: () => ({ raw: text(), visibleCharacters: cache.get("answer:part") ?? 0, projection: projectionCache.get("answer:part"), scrollTop: scroll.scrollTop, scrollHeight: scroll.scrollHeight, following }),
}

render(() => <div class="business-shell"><div class="chat-layout">
  <div class="messages-scroll" ref={scroll} style={{ height: "260px", overflow: "auto", width: "640px" }}>
    <div style={{ height: "360px" }}>Earlier answer</div>
    <Show when={mounted()}><SmoothMarkdown id="answer:part" text={text()} live complete={complete()} cache={cache} projectionCache={projectionCache} onProgress={() => { if (following) requestAnimationFrame(() => { if (following) scroll.scrollTop = scroll.scrollHeight }) }} /></Show>
  </div>
  <QuestionForm request={() => ({ id: "question-1", sessionID: "session-1", questions: [
    { header: "事发地点", question: "请选择地点。", options: [{ label: "城区" }] },
    { header: "警情关联半径", question: "请选择半径。", options: [{ label: "半径 500 米" }] },
  ] })} busy={busy()} answer={() => undefined} />
</div></div>, document.getElementById("root")!)
