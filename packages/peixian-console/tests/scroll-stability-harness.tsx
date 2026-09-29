import { createSignal, For, onCleanup, onMount, Show } from "solid-js"
import { render } from "solid-js/web"
import { ChatScroll, type ChatScrollMeasure } from "../src/chat-scroll"
import { FollowScroll } from "../src/follow-scroll"
import "../src/styles.css"
import "../src/chat-polish.css"
import "../src/chat-dialogue-v2.css"

const [count, setCount] = createSignal(2)
const [first, setFirst] = createSignal("较早的内容。".repeat(8))
const [last, setLast] = createSignal("末尾内容。".repeat(8))
const [card, setCard] = createSignal("")
const [composerHeight, setComposerHeight] = createSignal(100)
const follow = new FollowScroll()
const measures: ChatScrollMeasure[] = []
let scroll!: HTMLDivElement
let controller!: ChatScroll
const scope = window as Window & { scrollHarness: {
  setCount: typeof setCount; setFirst: typeof setFirst; setLast: typeof setLast; setCard: typeof setCard; setComposerHeight: typeof setComposerHeight
  readUp: () => void; resume: () => void; snapshot: () => unknown; measures: ChatScrollMeasure[]
} }
scope.scrollHarness = {
  setCount, setFirst, setLast, setCard, setComposerHeight,
  readUp: () => { follow.pause(); scroll.scrollTop = Math.max(0, scroll.scrollHeight - scroll.clientHeight - 120); controller.capture() },
  resume: () => { follow.resume(); controller.request("user-resume") },
  snapshot: () => ({ scrollHeight: scroll.scrollHeight, clientHeight: scroll.clientHeight, scrollTop: scroll.scrollTop, following: follow.following, anchor: scroll.querySelector("[data-message-id='first'] .markdown p")?.getBoundingClientRect().top - scroll.getBoundingClientRect().top }),
  measures,
}

function Harness() {
  onMount(() => {
    controller = new ChatScroll(scroll, follow, () => false, () => undefined, (value) => measures.push(value))
    controller.request("mount")
    onCleanup(() => controller.dispose())
  })
  return <div class="business-shell" style={{ height: "100dvh" }}><div class="chat-layout" style={{ height: "100%", display: "block" }}>
    <section class="conversation" style={{ height: "100%", display: "flex", "flex-direction": "column", padding: "0" }}>
      <div class="messages-scroll" ref={scroll}>
        <div class="messages">
          <For each={Array.from({ length: count() }, (_, index) => index)}>{(index) =>
            <article class="message" data-message-id={index === 0 ? "first" : `message-${index}`}>
              <div class="message-content"><div class="markdown"><p>{index === 0 ? first() : index === count() - 1 ? last() : "中间内容。".repeat(20)}</p></div></div>
            </article>
          }</For>
        </div>
        <div class="conversation-questions"><Show when={card()}><div class="confirmation-card">需要补充信息：{card()}<div class="question-options">请选择半径</div></div></Show></div>
      </div>
      <div class="composer-area" style={{ height: `${composerHeight()}px`, "flex-shrink": "0" }}>输入框</div>
    </section>
  </div></div>
}

render(() => <Harness />, document.getElementById("root")!)
