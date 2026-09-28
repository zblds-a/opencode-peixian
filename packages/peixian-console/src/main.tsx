import { render } from "solid-js/web"
import App from "./App"
import "../../ui/src/styles/theme.css"
import "./styles.css"
import "./chat-polish.css"
import "./visual-polish.css"
import "./typography.css"
import "./right-rail.css"
import "./chat-dialogue-v2.css"
import "./graph-preview.css"
if (location.pathname === "/dev/graph-preview") {
  if (import.meta.env.VITE_ENABLE_GRAPH_PREVIEW === "true") {
    void import("./GraphPreview").then(({ default: GraphPreview }) => render(() => <GraphPreview />, document.getElementById("root")!))
  } else {
    render(() => <main class="graph-preview-not-found"><h1>404</h1><p>页面不存在</p></main>, document.getElementById("root")!)
  }
} else render(() => <App />, document.getElementById("root")!)
