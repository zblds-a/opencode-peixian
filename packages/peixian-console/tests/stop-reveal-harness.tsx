import { createSignal, Show } from "solid-js"
import { render } from "solid-js/web"
import SmoothMarkdown from "../src/SmoothMarkdown"
import type { StreamProjection } from "../src/stream-markdown"

const [text, setText] = createSignal("First sentence. More text is still waiting in the reveal buffer.")
const [stopped, setStopped] = createSignal(false)
const [mounted, setMounted] = createSignal(true)
const cache = new Map<string, number>()
const projectionCache = new Map<string, StreamProjection>()
render(() => <>
  <button onClick={() => setStopped(true)}>Stop</button>
  <button onClick={() => setText((value) => value + " Later buffered content must stay hidden after stop.")}>Append cache</button>
  <button onClick={() => { setMounted(false); queueMicrotask(() => setMounted(true)) }}>Remount</button>
  <button onClick={() => setStopped(false)}>Resume after failure</button>
  <Show when={mounted()}><SmoothMarkdown id="demo:part" text={text()} live complete={false} stopped={stopped()} cache={cache} projectionCache={projectionCache} /></Show>
</>, document.getElementById("root")!)
