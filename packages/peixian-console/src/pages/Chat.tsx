import { createEffect, createMemo, createSignal, For, Index, onCleanup, Show } from "solid-js"
import { api, ApiError, list, patch, post, remove, safeMessage } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, Markdown, Modal, Spinner, Status } from "../components"
import { useConsole } from "../context"
import BusinessConfirmations, { QuestionForm } from "../BusinessConfirmations"
import { clarificationRequest, clarificationAnswer } from "../planner-question"
import { ClueDrawer, CluePanel } from "../TrustedAnalysis"
import RealEntityGraph from "../RealEntityGraph"
import SmoothMarkdown from "../SmoothMarkdown"
import type { TrustedEvidence } from "../TrustedAnalysis"
import { isAnalysisResult, legacyPresentation } from "../result-contract"
import RuntimeStatus from "../RuntimeStatus"
import { displayName } from "../analysis-display"
import { canObserve, canSend } from "../runtime-view"
import { useResourceRefresh } from "../resource-refresh"
import type { AnalysisClue, AnalysisResult, CapabilityItem, FileItem, Message, Model, Plugin, Run, RunEvent, RunEvidence, Session, Skill, SkillDraft } from "../types"

export default function Chat() {
  const app = useConsole()
  const [sessions, setSessions] = createSignal<Session[]>([])
  const [messages, setMessages] = createSignal<Message[]>([])
  const [models, setModels] = createSignal<Model[]>([])
  const [files, setFiles] = createSignal<FileItem[]>([])
  const [skills, setSkills] = createSignal<Skill[]>([])
  const [plugins, setPlugins] = createSignal<Plugin[]>([])
  const [capabilities, setCapabilities] = createSignal<CapabilityItem[]>([])
  const [selected, setSelected] = createSignal<string>()
  const [model, setModel] = createSignal("")
  const [draft, setDraft] = createSignal("")
  const [selectedFiles, setSelectedFiles] = createSignal<string[]>([])
  const [sentAttachments, setSentAttachments] = createSignal<Record<string, { id: string; name: string }[]>>({})
  const [selectedSkills, setSelectedSkills] = createSignal<string[]>([])
  const [selectedPlugins, setSelectedPlugins] = createSignal<string[]>([])
  const [busy, setBusy] = createSignal(false)
  const [sending, setSending] = createSignal(false)
  const [pendingPrompt, setPendingPrompt] = createSignal<{ text: string; attachments: { id: string; name: string }[]; messageID?: string; accepted: boolean }>()
  const [uploading, setUploading] = createSignal(false)
  const [uncertain, setUncertain] = createSignal(false)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [picker, setPicker] = createSignal<"files" | "capabilities">()
  const [search, setSearch] = createSignal("")
  const [slashFilter, setSlashFilter] = createSignal("")
  const [capabilityKind, setCapabilityKind] = createSignal<"all" | "skill" | "plugin">("all")
  const [creator, setCreator] = createSignal<"choose" | "source" | "edit">()
  const [creatorSource, setCreatorSource] = createSignal<"requirement" | "conversation">("requirement")
  const [skillDraft, setSkillDraft] = createSignal<SkillDraft>()
  const [skillEditor, setSkillEditor] = createSignal<Skill>()
  const [latestRun, setLatestRun] = createSignal<string>()
  const [currentRun, setCurrentRun] = createSignal<Run>()
  const [runEvents, setRunEvents] = createSignal<RunEvent[]>([])
  const [runEventRun, setRunEventRun] = createSignal<string>()
  const [runEvidence, setRunEvidence] = createSignal<RunEvidence>()
  const [scene, setScene] = createSignal<{ scenario_id: string | null; name: string | null; source: string }>()
  const [clearingScene, setClearingScene] = createSignal(false)
  const [trusted, setTrusted] = createSignal<TrustedEvidence>()
  const [selectedClue, setSelectedClue] = createSignal<AnalysisClue>()
  const [showClues, setShowClues] = createSignal(true)
  const [insightTab, setInsightTab] = createSignal<"clues" | "graph">("clues")
  const [showHistory, setShowHistory] = createSignal(false)
  const [rename, setRename] = createSignal<Session>()
  const [title, setTitle] = createSignal("")
  const [skillRequirement, setSkillRequirement] = createSignal("")
  const [draftTestText, setDraftTestText] = createSignal("")
  const [draftBusy, setDraftBusy] = createSignal(false)
  const [questionBusy, setQuestionBusy] = createSignal(false)
  let scroll!: HTMLDivElement
  let textarea!: HTMLTextAreaElement
  let fileInput!: HTMLInputElement
  const displayedText = new Map<string, number>()
  let scrollFrame = 0
  let followOutput = true
  let selectingText = false
  let animateUntil = 0
  let selectionRevision = 0
  let messageFlight: { id: string; revision: number; trailing: boolean; detail: boolean; promise: Promise<void> } | undefined
  const shownSessions = createMemo(() => sessions())
  const shownModels = createMemo(() => models())
  const shownCapabilities = createMemo(() => capabilities().filter((item) => item.enabled).map(item=>({...item,name:displayName(item.name),description:displayName(item.name)!==item.name?"整理相关资料并核对来源。":item.description})))
  const slashQuery = createMemo(() => draft().match(/^\s*\/([^\s]*)$/)?.[1]?.toLowerCase())
  const slashCapabilities = createMemo(() => {
    if (slashQuery() === undefined) return []
    const query = slashFilter().trim().toLowerCase() || slashQuery() || ""
    return shownCapabilities().filter((item) => !query || `${item.name}${item.description ?? ""}`.toLowerCase().includes(query)).slice(0, 7)
  })
  const messageAnalysis = createMemo(() => [...messages().flatMap((message) => message.parts)].reverse().find((part) => part.type === "analysis_result" && isAnalysisResult(part.data))?.data as AnalysisResult | undefined)
  const latestAnalysis = createMemo(() => {
    const result = messageAnalysis() ?? legacyPresentation(trusted()?.presentation)
    if (!result) return
    const gaps = result.run_id && runEvidence()?.run_id === result.run_id ? runEvidence()?.missing : undefined
    return { ...result, missing: [...new Set([...(result.missing ?? []), ...(gaps ?? [])])] }
  })
  const graphRunID = createMemo(() => latestAnalysis()?.run_id ?? currentRun()?.id)
  const hasInsights = createMemo(() => Boolean(latestAnalysis()?.clues.length || latestAnalysis()?.diagram || latestAnalysis()?.run_id))
  const sideMode = createMemo(() => hasInsights() ? (showClues() ? "insight" : "collapsed") : "empty")
  type ChatEntry = { message: Message; textParts: { part: Message["parts"][number]; id: string; afterTools: boolean }[]; toolParts: Message["parts"]; error?: Message["info"]["error"]; missingBody: boolean }
  const shownMessages = createMemo<ChatEntry[]>(() => messages().flatMap((message, index, all): ChatEntry[] => {
    if (message.info.role === "user") return [{ message, textParts: message.parts.filter((part) => part.type === "text" && part.text).map((part, partIndex) => ({ part, id: `${message.info.id}:${part.id ?? partIndex}`, afterTools: false })), toolParts: [], missingBody: false }]
    const turnStart = all.slice(0, index).map((item) => item.info.role).lastIndexOf("user") + 1
    const nextUser = all.findIndex((item, offset) => offset > index && item.info.role === "user")
    const turn = message.info.turn_id
      ? all.filter((item) => item.info.role === "assistant" && item.info.turn_id === message.info.turn_id)
      : message.info.run_id
        ? all.filter((item) => item.info.role === "assistant" && item.info.run_id === message.info.run_id)
        : all.slice(turnStart, nextUser < 0 ? undefined : nextUser).filter((item) => item.info.role === "assistant")
    const anchor = turn[0]
    if (message !== anchor) return []
    const toolParts = turn.flatMap((item) => item.parts.filter((part) => part.type === "tool"))
    const firstToolMessage = turn.findIndex((item) => item.parts.some((part) => part.type === "tool"))
    const firstToolPart = firstToolMessage < 0 ? -1 : turn[firstToolMessage].parts.findIndex((part) => part.type === "tool")
    const textParts = turn.flatMap((item, messageIndex) => item.parts.flatMap((part, partIndex) => part.type === "text" && part.text?.trim() ? [{ part, id: `${item.info.id}:${part.id ?? partIndex}`, afterTools: firstToolMessage >= 0 && (messageIndex > firstToolMessage || messageIndex === firstToolMessage && partIndex > firstToolPart) }] : []))
    const error = turn.find((item) => item.info.error)?.info.error
    const hasAnalysis = turn.some((item) => item.parts.some((part) => part.type === "analysis_result" && isAnalysisResult(part.data)))
    if (!textParts.length && !toolParts.length && !hasAnalysis && !error) return []
    return [{ message: anchor, textParts, toolParts, error, missingBody: !textParts.length && hasAnalysis }]
  }))
  const awaitingReply = createMemo(() => {
    if (!busy() || !currentRun()) return false
    if (runEventRun() === currentRun()?.id && runEvents().length) return false
    const userIndex = messages().findIndex((message) => message.info.id === currentRun()?.user_message_id)
    return !messages().some((message, index) => message.info.role === "assistant" &&
      (message.info.run_id === currentRun()?.id || (userIndex >= 0 && index > userIndex)) &&
      message.parts.some((part) => part.type === "text" && part.text?.trim() || part.type === "tool"))
  })
  createEffect(() => {
    const clue = selectedClue()
    if (!clue) return
    const diagrams = [latestAnalysis(), ...messages().flatMap(m=>m.parts.filter(p=>p.type==="analysis_result" && isAnalysisResult(p.data)).map(p=>p.data as AnalysisResult))].flatMap(r=>r?.diagram?[r.diagram]:[])
    const graphClue = clue.diagram_run_id && diagrams.some(d=>(d.run_id??d.scenario_id)===clue.diagram_run_id && d.pages.some(p=>p.nodes.some(n=>(d.run_id??d.scenario_id)+":"+n.id===clue.id)))
    if (!graphClue && !latestAnalysis()?.clues.some((item) => item.id === clue.id)) setSelectedClue(undefined)
  })
  createEffect(() => {
    if (slashQuery() === undefined && slashFilter()) setSlashFilter("")
  })
  const ready = createMemo(() => canSend(app.user().runtime))
  const available = createMemo(() => canObserve(app.user().runtime))
  function fetchMessages(id: string, detail = true): Promise<void> {
    const revision = selectionRevision
    const owner = app.user().id
    if (messageFlight?.id === id && messageFlight.revision === revision) {
      messageFlight.trailing = true
      messageFlight.detail ||= detail
      return messageFlight.promise
    }
    const flight = { id, revision, trailing: false, detail, promise: Promise.resolve() }
    messageFlight = flight
    const current = () => selected() === id && selectionRevision === revision && app.user().id === owner
    flight.promise = (async () => {
      do {
        flight.trailing = false
        const includeDetail = flight.detail
        flight.detail = false
        const data = await list<Message>("/sessions/" + id + "/messages")
        if (!current()) return
        setMessages((current) => data.map((message, index) => {
          const old = current[index]
          return old?.info.id === message.info.id && JSON.stringify(old) === JSON.stringify(message) ? old : message
        }))
        if (pendingPrompt()?.messageID && data.some((message) => message.info.id === pendingPrompt()?.messageID)) setPendingPrompt(undefined)
        if (!includeDetail) continue
        const hasAnalysis = data.some((message) => message.parts.some((part) => part.type === "analysis_result" && isAnalysisResult(part.data)))
        if (hasAnalysis) setTrusted(undefined)
        if (!hasAnalysis) {
          try {
            const view=await api<TrustedEvidence>("/sessions/"+id+"/evidence")
            if(current())setTrusted(view)
          } catch {
            if(current())setTrusted(undefined)
          }
        }
        await fetchRunState(id, current)
        const context = await api<{scenario_id: string | null; name: string | null; source: string}>("/sessions/" + id + "/context")
        if (current()) setScene(context)
      } while (flight.trailing && current())
    })().finally(() => {
      if (messageFlight === flight) messageFlight = undefined
    })
    return flight.promise
  }
  async function fetchRunState(id: string, current = () => selected() === id) {
    const page = await api<{ items: Run[] }>("/sessions/" + id + "/runs?page=1&page_size=20")
    if (!current()) return
    const run = page.items.find((item) => item.id === latestRun()) ?? page.items.find((item) => !terminalRun(item.status)) ?? page.items[0]
    if (!run) {
      setCurrentRun(undefined)
      setLatestRun(undefined)
      setRunEvents([])
      setRunEventRun(undefined)
      setRunEvidence(undefined)
      return
    }
    setLatestRun(run.id)
    setCurrentRun(run)
    setBusy(!terminalRun(run.status))
    const sameRun = runEventRun() === run.id
    const after = sameRun ? Math.max(0, ...runEvents().map((item) => item.sequence)) : 0
    const [eventsResult, evidenceResult] = await Promise.allSettled([
      api<{ items: RunEvent[] }>("/sessions/" + id + "/runs/" + run.id + "/events?page=1&page_size=100&after=" + after),
      api<RunEvidence>("/sessions/" + id + "/runs/" + run.id + "/evidence"),
    ])
    if (!current()) return
    if (eventsResult.status === "fulfilled") {
      setRunEvents(mergeRunEvents(sameRun ? runEvents() : [], eventsResult.value.items))
      setRunEventRun(run.id)
    }
    if (evidenceResult.status === "fulfilled") setRunEvidence(evidenceResult.value)
  }
  async function refresh() {
    if (!available()) {
      setBusy(false)
      return
    }
    try {
      const values = await list<Session>("/sessions")
      setSessions(values)
      if (selected()) {
        setBusy(["busy", "retry"].includes(values.find((item) => item.id === selected())?.status ?? "idle"))
        await fetchMessages(selected()!)
      }
      setError("")
    } catch (error) {
      setError((error as Error).message)
    }
  }
  async function resources() {
    if (!available()) {
      setLoading(false)
      return
    }
    const result = await Promise.allSettled([
      list<Model>("/models"),
      list<FileItem>("/files"),
      list<Skill>("/skills"),
      list<Session>("/sessions"),
      list<Plugin>("/plugins"),
      list<Omit<CapabilityItem, "kind"> & { kind: "personal_skill" | "plugin" | "official_skill" }>("/capabilities?page=1&page_size=100"),
    ])
    if (result[0].status === "fulfilled") {
      setModels(result[0].value as Model[])
      const data = result[0].value as Model[]
      if (!data.some((item) => item.id === model())) setModel(data.find((x) => x.is_default)?.id ?? data[0]?.id ?? "")
    }
    if (result[1].status === "fulfilled") setFiles(result[1].value as FileItem[])
    if (result[2].status === "fulfilled") setSkills(result[2].value as Skill[])
    if (result[3].status === "fulfilled") setSessions(result[3].value as Session[])
    if (result[4].status === "fulfilled") setPlugins(result[4].value as Plugin[])
    if (result[5].status === "fulfilled") setCapabilities((result[5].value as (Omit<CapabilityItem, "kind"> & { kind: "personal_skill" | "plugin" | "official_skill" })[]).map((item) => ({
      ...item,
      source_kind: item.kind,
      kind: item.kind === "plugin" ? "plugin" : "skill",
      version: String(item.version ?? ""),
      category: item.category ?? (item.kind === "plugin" ? "插件工具" : "个人 Skill"),
      recommended: item.recommended ?? false,
      enabled: item.enabled ?? false,
      owned: item.owned ?? item.kind === "personal_skill",
      scope: item.scope ?? (item.kind === "plugin" ? "authorized" : "personal"),
    })))
    else setCapabilities([])
    setLoading(false)
  }
  createEffect(() => {
    app.changed()
    void refresh()
    void resources()
  })
  useResourceRefresh(["messages"], () => selected() ? fetchMessages(selected()!, false) : Promise.resolve(), 700)
  useResourceRefresh(["sessions", "runs"], refresh, 10000)
  const poll = setInterval(() => {
    if (busy()) void refresh()
  }, 1800)
  onCleanup(() => {
    selectionRevision++
    clearInterval(poll)
    cancelAnimationFrame(scrollFrame)
  })
  createEffect(()=>{if(!available()){selectionRevision++;setTrusted(undefined);setSelectedClue(undefined)}})
  createEffect(() => {
    messages()
    busy()
    cancelAnimationFrame(scrollFrame)
    scrollFrame = requestAnimationFrame(() => {
      if (scroll && followOutput && !selectingText && !selectionInConversation()) scroll.scrollTop = scroll.scrollHeight
    })
  })
  function selectionInConversation() {
    const selection = window.getSelection()
    return Boolean(selection && !selection.isCollapsed && selection.anchorNode && scroll?.contains(selection.anchorNode))
  }
  async function choose(id: string) {
    selectionRevision++
    displayedText.clear()
    animateUntil = 0
    followOutput = true
    setSelected(id)
    setPendingPrompt(undefined)
    setSelectedFiles([])
    setScene(undefined)
    setSelectedSkills([])
    setSelectedPlugins([])
    setMessages([])
    setTrusted(undefined)
    setCurrentRun(undefined)
    setLatestRun(undefined)
    setRunEvents([])
    setRunEventRun(undefined)
    setRunEvidence(undefined)
    setSelectedClue(undefined)
    setShowClues(true)
    setInsightTab("clues")
    setError("")
    setShowHistory(false)
    setBusy(["busy", "retry"].includes(sessions().find((item) => item.id === id)?.status ?? "idle"))
    try {
      await fetchMessages(id)
    } catch (error) {
      setError((error as Error).message)
    }
  }
  function fresh() {
    selectionRevision++
    displayedText.clear()
    animateUntil = 0
    followOutput = true
    setSelected(undefined)
    setPendingPrompt(undefined)
    setMessages([])
    setTrusted(undefined)
    setCurrentRun(undefined)
    setLatestRun(undefined)
    setRunEvents([])
    setRunEventRun(undefined)
    setRunEvidence(undefined)
    setSelectedClue(undefined)
    setShowClues(true)
    setInsightTab("clues")
    if (!uncertain()) setDraft("")
    setSelectedFiles([])
    setScene(undefined)
    setSelectedSkills([])
    setSelectedPlugins([])
    setError("")
    setShowHistory(false)
    setBusy(false)
    textarea?.focus()
  }
  async function clearScene() {
    const id = selected(), owner = app.user().id
    if (!id || busy() || sending() || clearingScene()) return
    const revision = ++selectionRevision
    setClearingScene(true)
    try {
      await remove("/sessions/" + id + "/context")
      if (selected() === id && selectionRevision === revision && app.user().id === owner) {
        setScene(undefined)
        setSelectedSkills([])
        app.notify("当前场景已清除，下一次分析请重新选择场景。")
      }
    } catch (cause) { if (selected() === id) app.notify((cause as Error).message, "error") }
    finally { if (app.user().id === owner) setClearingScene(false) }
  }
  async function send(textOverride?: string) {
    const text = textOverride ?? draft()
    if (!text.trim() || sending() || uncertain() || busy() || !ready() || !shownModels().length) return
    const attachments: {id:string;name:string}[] = []
    const payload = {
      text: text.trim(),
      agent_id: "theft-assistant",
      model_id: model() || undefined,
      skill_ids: [],
      plugin_ids: [],
      file_ids: [],
      mode: "standard",
      client_request_id: crypto.randomUUID(),
    }
    const uid = app.user().id
    setSending(true)
    setPendingPrompt({ text, attachments, accepted: false })
    setError("")
    let submitting = false
    let accepted = false
    try {
      let id = selected()
      const previous = currentRun()
      if (id && previous?.session_id === id) {
        const binding = await api<{agent_profile?:{id:string}}>(`/sessions/${id}/runs/${previous.id}/task`)
        if (binding.agent_profile?.id && binding.agent_profile.id !== "theft-assistant") throw new ApiError("涉赌助手已下线，历史记录仍可查看。请点击新建研判，使用盗窃助手继续；当前输入已保留。", 409, "session_agent_mismatch")
      }
      if (!id) {
        const session = await post<Session>("/sessions", { title: text.trim().slice(0, 35) })
        if (app.user().id !== uid) return
        id = session.id
        selectionRevision++
        setSelected(id)
      }
      if (!ready()) return
      submitting = true
      const result = await post<{ accepted: boolean; run_id: string; message_id: string }>("/sessions/" + id + "/messages", payload)
      if (app.user().id !== uid) return
      if (result.accepted !== true) throw new ApiError("提交结果待确认，请核对历史记录。", 0, "unknown_submission")
      accepted = true
      setSentAttachments((current) => ({ ...current, [result.message_id]: attachments }))
      setPendingPrompt({ text, attachments, messageID: result.message_id, accepted: true })
      animateUntil = Date.now() + 30000
      setLatestRun(result.run_id)
      setCurrentRun({ id: result.run_id, session_id: id, status: "queued", phase: "accepted", user_message_id: result.message_id, created_at: new Date().toISOString() })
      setRunEvents([])
      setRunEventRun(result.run_id)
      if (textOverride === undefined && draft() === text) setDraft("")
      if (JSON.stringify(selectedFiles()) === JSON.stringify(payload.file_ids)) setSelectedFiles([])
      if (JSON.stringify(selectedSkills()) === JSON.stringify(payload.skill_ids)) setSelectedSkills([])
      if (JSON.stringify(selectedPlugins()) === JSON.stringify(payload.plugin_ids)) setSelectedPlugins([])
      setBusy(true)
      setSending(false)
      await refresh()
    } catch (error) {
      if (app.user().id !== uid) return
      if (accepted) setError("消息已受理，历史记录暂未刷新；请等待恢复，不要重复发送。")
      else if (submitting && error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setPendingPrompt(undefined)
        setUncertain(true)
        setError("提交结果待确认，草稿已保留。请先检查历史和当前任务状态，避免重复调用。")
      } else { setPendingPrompt(undefined); setError((error as Error).message) }
    } finally {
      if (app.user().id === uid) setSending(false)
    }
  }
  async function answerClarification(answers?: string[][]) {
    const sid=selected(),run=currentRun(),question=run?.clarification
    if (!sid || !run || !question || questionBusy() || sending()) return
    setQuestionBusy(true)
    setError("")
    try {
      if (answers === undefined) {
        await post(`/sessions/${sid}/runs/${run.id}/clarification/reject`,{})
        await refresh()
        return
      }
      const reply=clarificationAnswer(question.missing,answers)
      if (selected()!==sid || currentRun()?.id!==run.id || currentRun()?.clarification?.id!==question.id) return
      await send(reply)
    } catch (cause) { if (selected()===sid) setError(safeMessage((cause as Error).message)) }
    finally { setQuestionBusy(false) }
  }
  async function abort() {
    if (!selected()) return
    try {
      const path = currentRun() && !terminalRun(currentRun()!.status)
        ? "/sessions/" + selected() + "/runs/" + currentRun()!.id + "/abort"
        : "/sessions/" + selected() + "/abort"
      const run = await post<Run>(path)
      if (run?.id) setCurrentRun(run)
      await refresh()
      app.notify(run?.status === "cancelled" ? "执行已停止。" : "停止请求已受理，正在等待执行状态确认。")
    } catch (error) {
      setError((error as Error).message)
    }
  }
  async function deleteSession(item: Session) {
    if (!window.confirm("确定删除这条对话及其消息吗？")) return
    try {
      await remove("/sessions/" + item.id)
      if (selected() === item.id) fresh()
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function saveTitle(event: SubmitEvent) {
    event.preventDefault()
    try {
      await patch("/sessions/" + rename()!.id, { title: title().trim() })
      setRename(undefined)
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  function toggle(id: string, type: "files" | "skills") {
    const setter = type === "files" ? setSelectedFiles : setSelectedSkills
    const current = type === "files" ? selectedFiles() : selectedSkills()
    if (!current.includes(id) && current.length >= 5) {
      app.notify("每次最多选择五个文件和五个技能。", "error")
      return
    }
    setter(current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  }
  async function uploadLocal(chosen: FileList | null) {
    if (!chosen?.length || uploading() || !ready()) return
    const incoming = Array.from(chosen)
    fileInput.value = ""
    if (incoming.length + selectedFiles().length > 5) {
      app.notify("每次最多关联五个文件。", "error")
      return
    }
    const owner = app.user().id
    const revision = selectionRevision
    setUploading(true)
    try {
      for (const file of incoming) {
        if (file.size > 20 * 1024 * 1024 || !/\.(xlsx|pdf|docx|txt|md|csv)$/i.test(file.name)) throw new Error("仅支持不超过 20 MiB 的 XLSX、PDF、DOCX、TXT、MD、CSV 文件。")
        const body = new FormData()
        body.append("file", file)
        const uploaded = await api<FileItem>("/files", { method: "POST", body })
        if (!uploaded.id) throw new Error("上传成功但未返回文件 ID，请在历史文件中核对。")
        let readyFile: FileItem | undefined
        for (let attempt = 0; attempt < 45; attempt++) {
          if (owner !== app.user().id || revision !== selectionRevision) return
          try {
            readyFile = await api<FileItem>("/files/" + encodeURIComponent(uploaded.id))
            setFiles((current) => [...current.filter((item) => item.id !== uploaded.id), readyFile!])
          } catch (cause) {
            if (!(cause instanceof ApiError && cause.status === 404)) throw cause
            const inventory = await list<FileItem>("/files")
            setFiles(inventory)
            readyFile = inventory.find((item) => item.id === uploaded.id)
          }
          if (readyFile?.status === "ready" && readyFile.truncated !== true) break
          if (readyFile?.truncated || readyFile && ["partial", "no_text", "failed", "error"].includes(readyFile.status ?? "")) throw new Error(`${file.name} 解析未完成或内容被截断，请拆分或重传。`)
          await new Promise((resolve) => setTimeout(resolve, 2000))
        }
        if (readyFile?.status !== "ready" || readyFile.truncated) throw new Error(`${file.name} 已上传但仍在解析，暂不能关联；请稍后重新选择。`)
        setSelectedFiles((current) => current.includes(uploaded.id) ? current : [...current, uploaded.id])
      }
      app.invalidate(["files"])
      app.notify("文件已上传并解析完成，发送时将随消息关联。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    } finally {
      if (owner === app.user().id) setUploading(false)
    }
  }
  function toggleCapability(item: CapabilityItem) {
    if (item.available === false) {
      app.notify(item.unavailable_reason || "该能力当前不可用。", "error")
      return
    }
    if (item.kind === "skill") {
      toggle(item.id, "skills")
      return
    }
    const current = selectedPlugins()
    if (!current.includes(item.id) && current.length >= 5) {
      app.notify("每次最多选择五个插件。", "error")
      return
    }
    setSelectedPlugins(current.includes(item.id) ? current.filter((value) => value !== item.id) : [...current, item.id])
  }
  function chooseSlashCapability(item: CapabilityItem) {
    toggleCapability(item)
    setDraft("")
    setSlashFilter("")
    queueMicrotask(() => textarea?.focus())
  }
  async function generateSkill(source: "requirement" | "conversation") {
    if (source === "conversation" && !selected()) {
      app.notify("请先选择一条已有对话。", "error")
      return
    }
    setCreatorSource(source)
    if (source === "requirement" && !skillRequirement().trim()) {
      app.notify("请先填写研判需求。", "error")
      return
    }
    setDraftBusy(true)
    try {
      const body = source === "conversation"
        ? { session_id: selected(), model_id: model() || undefined, client_request_id: crypto.randomUUID() }
        : { requirement: skillRequirement().trim(), model_id: model() || undefined, client_request_id: crypto.randomUUID() }
      const value = await post<SkillDraft>("/skill-drafts/from-" + (source === "conversation" ? "session" : "requirement"), body)
      setSkillDraft(normalizeSkillDraft(value))
      setCreator("edit")
      void pollDraft(value.id)
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    } finally {
      setDraftBusy(false)
    }
  }
  async function pollDraft(id: string) {
    for (let attempt = 0; attempt < 30; attempt++) {
      const value = await api<SkillDraft>("/skill-drafts/" + id)
      setSkillDraft(normalizeSkillDraft(value))
      if (!["preparing", "generating"].includes(value.status)) return
      await new Promise((resolve) => setTimeout(resolve, 1200))
    }
  }
  async function updateDraft() {
    const value = skillDraft()
    if (!value) return
    const updated = await patch<SkillDraft>("/skill-drafts/" + value.id, {
      name: value.name,
      description: value.description,
      content: value.content,
      dependency_ids: value.dependency_ids,
      input_schema: value.input_schema,
      default_rules: value.default_rules,
    })
    setSkillDraft(normalizeSkillDraft(updated))
    return updated
  }
  async function testDraft(mode: "validation" | "model") {
    const value = await updateDraft()
    if (!value) return
    if (mode === "model" && !draftTestText().trim()) {
      app.notify("请填写模型试运行输入。", "error")
      return
    }
    try {
      const result = await post<{ ok?: boolean; field_errors?: Record<string, string>; accepted?: boolean; session_id?: string; run_id?: string }>("/skill-drafts/" + value.id + "/test", mode === "validation" ? { mode } : { mode, text: draftTestText().trim(), model_id: model() || undefined, client_request_id: crypto.randomUUID() })
      if (mode === "validation") app.notify(result.ok ? "草稿结构检查通过。" : Object.values(result.field_errors ?? {}).join("；") || "草稿结构检查未通过。", result.ok ? "success" : "error")
      else app.notify(result.accepted ? `试运行已受理${result.run_id ? `（${result.run_id}）` : ""}。` : "试运行未受理。", result.accepted ? "success" : "error")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function saveDraft() {
    const value = await updateDraft()
    if (!value) return
    try {
      const result = await post<{ skill_id: string; enabled?: boolean; already_saved: boolean }>("/skill-drafts/" + value.id + "/save", {})
      setCreator(undefined)
      setSkillDraft(undefined)
      await resources()
      app.notify(result.already_saved ? "该草稿此前已保存为个人 Skill。" : "已保存为个人 Skill；启用并等待配置生效后即可使用。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function savePersonalSkill() {
    const value = skillEditor()
    if (!value) return
    try {
      await patch("/skills/" + value.id, {
        name: value.name,
        description: value.description ?? "",
        content: value.content ?? "",
        enabled: value.enabled ?? true,
      })
      setSkillEditor(undefined)
      await resources()
      app.notify("个人 Skill 已更新。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function testPersonalSkill() {
    const value = skillEditor()
    if (!value) return
    try {
      const result = await post<{ ok: boolean; message: string }>("/skills/" + value.id + "/test")
      app.notify(result.message, result.ok ? "success" : "error")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function deletePersonalSkill() {
    const value = skillEditor()
    if (!value || !window.confirm(`确定删除个人 Skill“${value.name}”吗？`)) return
    try {
      await remove("/skills/" + value.id)
      setSelectedSkills(selectedSkills().filter((id) => id !== value.id))
      setSkillEditor(undefined)
      await resources()
      app.notify("个人 Skill 已删除。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  return (
    <div class={"chat-layout side-mode-" + sideMode()}>
      <aside class={"history-panel " + (showHistory() ? "visible" : "")}>
        <div class="history-head">
          <strong>研判记录</strong>
          <button class="icon-button" aria-label="新建研判" onClick={fresh}>
            <Icon name="plus" />
          </button>
        </div>
        <Button class="new-chat" icon="plus" onClick={fresh}>
          新建研判
        </Button>
        <label class="search-box">
          <Icon name="search" size={16} />
          <input
            aria-label="搜索对话"
            placeholder="搜索对话"
            value={search()}
            onInput={(event) => setSearch(event.currentTarget.value)}
          />
        </label>
        <div class="history-list">
          <Show
            when={!loading()}
            fallback={
              <div class="loading">
                <Spinner />
              </div>
            }
          >
            <For
              each={shownSessions().filter((item) => item.title?.includes(search()))}
              fallback={<p class="quiet">你的研判记录会保存在这里</p>}
            >
              {(item) => (
                <div class={"history-item " + (selected() === item.id ? "selected" : "")}>
                  <button onClick={() => void choose(item.id)}>
                    <Icon name="chat" size={16} />
                    <span>{displayName(item.title) || "未命名对话"}</span>
                  </button>
                  <Show when={!item.id.startsWith("mock-")}><div class="history-actions">
                    <button
                      class="icon-button"
                      aria-label="重命名对话"
                      onClick={() => {
                        setRename(item)
                        setTitle(item.title)
                      }}
                    >
                      <Icon name="edit" size={14} />
                    </button>
                    <button class="icon-button" aria-label="删除对话" onClick={() => void deleteSession(item)}>
                      <Icon name="trash" size={14} />
                    </button>
                  </div></Show>
                </div>
              )}
            </For>
          </Show>
        </div>
        <div class="history-foot">
          <Icon name="lock" size={13} />
          仅你可见
        </div>
      </aside>
      <section class="conversation">
        <button class="mobile-history-open" aria-label="显示研判记录" aria-expanded={showHistory()} onClick={() => setShowHistory(!showHistory())}>研判记录</button>
        <Show when={!ready()}>
          <div class="runtime-banner">
            <Icon name="clock" size={17} />
            <span>
              个人工作空间
              {["updating", "applying"].includes(app.user().runtime?.status ?? "")
                ? "正在更新配置，当前对话可继续查看或停止，完成后即可发送新消息。"
                : ["paused", "stopped"].includes(app.user().runtime?.status ?? "")
                  ? "已暂停，请联系管理员恢复。"
                  : ["failed", "error"].includes(app.user().runtime?.status ?? "")
                    ? "暂时不可用，请联系管理员检查并重试。"
                    : "正在准备，准备完成后即可发送消息。"}
            </span>
            <Status value={app.user().runtime?.status} />
          </div>
        </Show>
        <div class="messages-scroll" ref={scroll} onPointerDown={() => { selectingText = true }} onPointerUp={() => { selectingText = false }} onPointerCancel={() => { selectingText = false }} onScroll={() => { followOutput = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 96 }}>
          <Show
            when={messages().length || pendingPrompt() || awaitingReply()}
            fallback={<Show when={!selected()} fallback={<div class="conversation-blank" aria-label="空白研判对话区" />}><div class="chat-welcome"><span class="welcome-icon"><Icon name="skill" size={25} /></span><h2>你好，我是盗窃资料助手</h2><p>直接说出要核对的问题。我会根据已有资料继续分析；缺少必要条件时，会在对话中请你补充。</p><div class="welcome-questions"><For each={["你能帮我做什么？", "帮我核对一处位置周边的警情", "解释刚才的资料依据", "继续核对我选定的来源记录"]}>{(question) => <button onClick={() => { setDraft(question); textarea?.focus() }}>{question}<Icon name="send" size={14} /></button>}</For></div></div></Show>}
          >
            <div class="messages">
              <Index each={shownMessages()}>
                {(entry) => {
                  const message = () => entry().message
                  const attachments = () => message().attachments ?? sentAttachments()[message().info.id] ?? []
                  const textParts = () => entry().textParts
                  const toolParts = () => entry().toolParts
                  const renderText = (item: { part: Message["parts"][number]; id: string }) => message().info.role === "assistant" ? <div><Show when={item.part.origin === "verified_result"}><small class="verified-result-label">已核对结果摘要</small></Show><SmoothMarkdown id={`${selected()}:${item.id}`} text={item.part.text ?? ""} live={busy() || Date.now() < animateUntil} cache={displayedText} onProgress={() => { if (scroll && followOutput && !selectingText && !selectionInConversation()) scroll.scrollTop = scroll.scrollHeight }} /></div> : <Markdown text={item.part.text ?? ""} />
                  return (
                  <article data-message-id={message().info.id} tabindex={-1} class={"message " + (message().info.role === "user" ? "user" : "assistant")}>
                    <div class="message-avatar">
                      <Show when={message().info.role === "user"} fallback={<Icon name="skill" size={17} />}>
                        {app.user().username.slice(0, 1).toUpperCase()}
                      </Show>
                    </div>
                    <div class="message-content">
                      <div class="message-author">{message().info.role === "user" ? "你" : "智能助手"}</div>
                      <Show when={message().info.role === "user" && attachments().length}>
                        <div class="message-attachments"><For each={attachments()}>{(file) => <span title={file.name}><Icon name="file" size={14} /><span>{file.name}</span></span>}</For></div>
                      </Show>
                      <For each={textParts().filter((item) => !item.afterTools)}>{renderText}</For>
                      <Show when={entry().missingBody}><p class="message-no-body">本轮暂无可展示的 Markdown 正文；右侧线索仍可查看。</p></Show>
                      <Show when={toolParts().length}>
                        <details class="tool-trace">
                          <summary>
                            <Icon
                              name={toolParts().every((part) => (part.execution?.status ?? part.state?.status) === "completed") ? "check" : "clock"}
                              size={14}
                            />
                            <span>查看资料处理过程（{toolParts().length} 项）</span>
                            <Status
                              value={toolParts().every((part) => (part.execution?.status ?? part.state?.status) === "completed") ? "completed" : "running"}
                            />
                          </summary>
                          <div class="tool-trace-list">
                            <For each={toolParts()}>
                              {(part) => (
                                <details class="tool-trace-item">
                                  <summary>
                                    <Icon name={(part.execution?.status ?? part.state?.status) === "completed" ? "check" : "clock"} size={14} />
                                    <span>{safeMessage(part.execution?.capability_name || part.execution?.name || part.state?.title || part.tool, "处理业务资料")}</span>
                                    <Status value={part.execution?.status ?? part.state?.status} />
                                  </summary>
                                  <div class="tool-trace-detail">
                                  <For
                                    each={[
                                      { title: "输入条件", fields: part.details?.inputs },
                                      { title: "处理结果", fields: part.details?.outputs },
                                    ]}
                                  >
                                    {(section) => (
                                      <Show when={Object.keys(section.fields ?? {}).length}>
                                        <div class="business-detail">
                                          <strong>{section.title}</strong>
                                          <dl>
                                            <For each={Object.entries(section.fields ?? {})}>
                                              {([name, value]) => (
                                                <div>
                                                  <dt>{safeMessage(name)}</dt>
                                                  <dd>
                                                    {safeMessage(
                                                      typeof value === "boolean" ? (value ? "是" : "否") : String(value),
                                                    )}
                                                  </dd>
                                                </div>
                                              )}
                                            </For>
                                          </dl>
                                        </div>
                                      </Show>
                                    )}
                                  </For>
                                  <Show when={part.state?.error}>
                                    <ErrorLine message={part.state?.error} />
                                  </Show>
                                  <Show when={part.execution?.input_summary}><p>{part.execution?.input_summary}</p></Show>
                                  <Show when={part.execution?.output_summary}><p>{part.execution?.output_summary}</p></Show>
                                  <Show when={part.execution?.result_truncated}><small>公开结果已裁剪；不代表取数完整。</small></Show>
                                  <Show when={!Object.keys(part.details?.inputs ?? {}).length && !Object.keys(part.details?.outputs ?? {}).length && !part.state?.error && !part.execution?.input_summary && !part.execution?.output_summary}>
                                    <p>后端暂无可展示的执行详情。</p>
                                  </Show>
                                  </div>
                                </details>
                              )}
                            </For>
                          </div>
                        </details>
                      </Show>
                      <For each={textParts().filter((item) => item.afterTools)}>{renderText}</For>
                      <Show when={entry().error}>
                        <ErrorLine
                          message={
                            entry().error?.data?.message ||
                            entry().error?.message ||
                            "本次生成未完成，请检查工作空间状态后重试。"
                          }
                        />
                      </Show>
                    </div>
                  </article>
                  )
                }}
              </Index>
              <Show when={pendingPrompt()?.messageID && messages().some((message) => message.info.id === pendingPrompt()?.messageID) ? undefined : pendingPrompt()}>
                {(prompt) => <article class="message user pending-prompt" aria-live="polite"><div class="message-avatar">{app.user().username.slice(0, 1).toUpperCase()}</div><div class="message-content"><div class="message-author">你</div><Show when={prompt().attachments.length}><div class="message-attachments"><For each={prompt().attachments}>{(file) => <span title={file.name}><Icon name="file" size={14} /><span>{file.name}</span></span>}</For></div></Show><Markdown text={prompt().text} /><small>{prompt().accepted ? "已发送" : "正在提交…"}</small></div></article>}
              </Show>
              <Show when={awaitingReply()}><div class="assistant-thinking" role="status"><span class="message-avatar"><Icon name="skill" size={17} /></span><span>智能助手正在思考…</span></div></Show>
              <Show when={busy() && runEventRun() === currentRun()?.id && runEvents().length && !messages().some((message) => message.info.run_id === currentRun()?.id && message.parts.some((part) => part.type === "tool"))}>
                <div class="active-run-trace" role="status"><strong>执行过程</strong><For each={runEvents()}>{(step) => <span>{step.capability_name || step.name}<Status value={step.status} /></span>}</For></div>
              </Show>
            </div>
          </Show>
        </div>
        <div class="composer-area">
          <RuntimeStatus compact />
          <BusinessConfirmations sessionID={selected()} available={available()} onAnswered={() => void refresh()} />
          <Show when={selected() && currentRun()?.clarification?.version === "theft-clarification-v1"}>
            <QuestionForm request={() => clarificationRequest(currentRun()!, selected()!)} busy={questionBusy() || sending() || !ready()} answer={(answers) => void answerClarification(answers)} />
          </Show>
          <ErrorLine message={error()} />
          <Show when={uncertain()}>
            <div class="runtime-banner" role="status">
              <span>结果待确认。刷新不会自动重发本次问题。</span>
              <Button onClick={() => void refresh()}>刷新历史</Button>
              <Button onClick={() => {
                if (window.confirm("请确认已核对原会话历史及任务状态。重新发送可能产生重复调用，是否解除发送保护？")) {
                  setUncertain(false)
                  setError("")
                }
              }}>已核对，解除保护</Button>
            </div>
          </Show>
          <Show when={scene()?.scenario_id}><div class="selection-chips" role="status"><span>当前场景：{scene()?.name} · 追问将沿用</span><button disabled={busy() || sending() || clearingScene()} onClick={() => void clearScene()} aria-label="清除当前场景">清除场景 <Icon name="close" size={12}/></button></div></Show>
          <Show when={selectedFiles().length}><div class="pending-attachments" aria-label="待发送附件"><For each={selectedFiles()}>{(id) => <button type="button" title={files().find((file) => file.id === id)?.name ?? "已上传文件"} aria-label={`移除附件 ${files().find((file) => file.id === id)?.name ?? "已上传文件"}`} onClick={() => toggle(id, "files")}><Icon name="file" size={14} /><span>{files().find((file) => file.id === id)?.name ?? "已上传文件"}</span><Icon name="close" size={12} /></button>}</For></div></Show>
          <div class="composer">
            <textarea
              ref={textarea}
              aria-label="输入消息"
              maxlength={32000}
              placeholder="直接描述要核对的问题，或继续追问已有结果…"
              value={draft()}
              rows={3}
              onInput={(event) => setDraft(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                  event.preventDefault()
                  void send()
                }
              }}
            />
            <div class="composer-tools">
              <div class="model-choice">
                <span class="model-dot" />
                <select aria-label="选择授权模型" value={model() || shownModels()[0]?.id} disabled={busy()} onChange={(event) => setModel(event.currentTarget.value)}>
                  <For each={shownModels()}>{(item) => <option value={item.id}>{item.name}{item.is_default ? " · 默认" : ""}</option>}</For>
                </select>
              </div>
              <Show
                when={busy()}
                fallback={
                  <Button
                    variant="primary"
                    icon="send"
                    busy={sending()}
                    disabled={!draft().trim() || uncertain() || !ready() || !shownModels().length}
                    onClick={() => void send()}
                  >
                    发送
                  </Button>
                }
              >
                <Button icon="stop" onClick={abort}>
                  停止生成
                </Button>
              </Show>
            </div>
          </div>
          <div class="composer-hint">
            Enter 发送 · Shift + Enter 换行 <span>重要信息请结合原始资料核验</span>
          </div>
        </div>
      </section>
      <Show when={sideMode() !== "empty"}>
        <aside class={"insight-sidebar rail-" + sideMode()} aria-label="研判侧栏">
          <Show when={sideMode() === "collapsed"}><button class="insight-reopen" onClick={() => setShowClues(true)} aria-label="展开研判侧栏" title="展开研判侧栏"><Icon name="star" size={17} /></button></Show>
          <Show when={sideMode() === "insight"}>
            <div class="insight-single-head"><strong>{insightTab() === "clues" ? "智能发现线索" : "实体关系图谱"}</strong><div><button class="insight-icon-button" aria-label="切换侧栏内容" title="切换侧栏内容" onClick={() => setInsightTab(insightTab() === "clues" ? "graph" : "clues")}><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h15l-4-4M20 16H5l4 4" /></svg></button><button class="insight-icon-button" aria-label="收起侧栏" title="收起侧栏" onClick={() => setShowClues(false)}><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 15 7-7 7 7" /></svg></button></div></div>
            <Show when={insightTab() === "clues"} fallback={<RealEntityGraph sessionID={selected()} runID={graphRunID()} runStatus={currentRun()?.id === graphRunID() ? currentRun()?.status : undefined} />}>
              <CluePanel clues={latestAnalysis()?.clues ?? []} expanded={showClues()} onExpandedChange={setShowClues} onSelect={setSelectedClue} hideHeader />
            </Show>
          </Show>
        </aside>
      </Show>
      <Show when={selectedClue()}>{(clue) => <ClueDrawer clue={clue()} onClose={() => setSelectedClue(undefined)} onReturn={clue().message_id ? ()=>{const id=clue().message_id;setSelectedClue(undefined);queueMicrotask(()=>{const target=Array.from(document.querySelectorAll<HTMLElement>('[data-message-id]')).find(el=>el.dataset.messageId===id);target?.scrollIntoView({block:"center"});target?.focus()})}:undefined} />}</Show>
      <Show when={picker()}>
        {(type) => (
          <Modal
            title={type() === "files" ? "关联文件" : "能力选择"}
            text={type() === "files" ? "仅可选择已完成解析的个人文件。" : "选择适合当前任务的能力；个人 Skill 可在此编辑和使用。"}
            onClose={() => setPicker(undefined)}
          >
            <Show when={type() === "capabilities"}>
              <div class="capability-toolbar"><label class="search-box"><Icon name="search" size={16} /><input placeholder="搜索能力名称或描述" value={search()} onInput={(event) => setSearch(event.currentTarget.value)} /></label><div class="segmented"><button class={capabilityKind() === "all" ? "active" : ""} onClick={() => setCapabilityKind("all")}>全部</button><button class={capabilityKind() === "skill" ? "active" : ""} onClick={() => setCapabilityKind("skill")}>分析 Skill</button><button class={capabilityKind() === "plugin" ? "active" : ""} onClick={() => setCapabilityKind("plugin")}>插件工具</button></div></div>
            </Show>
            <div class="picker-list">
              <For
                each={
                  type() === "files"
                    ? files().filter((item) => ["ready", "partial"].includes(item.status ?? ""))
                    : shownCapabilities().filter((item) => (capabilityKind() === "all" || item.kind === capabilityKind()) && (!search() || (item.name + (item.description ?? "")).toLowerCase().includes(search().toLowerCase())))
                }
                fallback={
                  <Empty
                    title={type() === "files" ? "暂无可关联文件" : "暂无已启用技能"}
                    text={type() === "files" ? "请先上传并等待文件解析完成。" : "当前没有匹配的可用能力。"}
                  />
                }
              >
                {(item) => (
                  <div class="pick-row capability-row">
                    <input
                      type="checkbox"
                      disabled={(type() === "files" && "status" in item && item.status === "partial") || (type() === "capabilities" && "available" in item && item.available === false)}
                      checked={(type() === "files" ? selectedFiles() : "kind" in item && item.kind === "plugin" ? selectedPlugins() : selectedSkills()).includes(item.id)}
                      onChange={() => type() === "files" ? toggle(item.id, "files") : "kind" in item && toggleCapability(item)}
                    />
                    <Icon name={type() === "files" ? "file" : "skill"} />
                    <span>
                      {item.name}
                      <Show when={type() === "capabilities" && "description" in item}><small>{("description" in item ? item.description : "") || "可用于当前研判任务"}</small></Show>
                      <Show when={type() === "capabilities" && "available" in item && item.available === false}><br/><small class="muted">当前不可用：{"unavailable_reason" in item ? item.unavailable_reason : "配置尚未生效"}</small></Show>
                      <Show when={type() === "files" && "status" in item && item.status === "partial"}>
                        <br />
                        <small class="muted">部分解析 · 请拆分重传</small>
                      </Show>
                    </span>
                    <Show when={type() === "capabilities" && "owned" in item && item.owned}>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          const skill = skills().find((value) => value.id === item.id)
                          if (skill) setSkillEditor({ ...skill })
                        }}
                      >
                        编辑
                      </Button>
                    </Show>
                  </div>
                )}
              </For>
            </div>
            <div class="modal-actions">
              <Show when={type() === "capabilities"}><Button icon="plus" onClick={() => { setPicker(undefined); setCreator("choose") }}>创建 Skill</Button></Show>
              <Button variant="primary" onClick={() => setPicker(undefined)}>
                完成选择
              </Button>
            </div>
          </Modal>
        )}
      </Show>
      <Show when={creator() === "choose"}><Modal title="选择创建方式" onClose={() => setCreator(undefined)}><div class="creator-choice"><button onClick={() => { setCreatorSource("requirement"); setCreator("source") }}><Icon name="file" /><strong>从需求创建</strong><span>通过自然语言描述，由系统生成 Skill 草稿</span></button><button onClick={() => void generateSkill("conversation")}><Icon name="chat" /><strong>从当前对话生成</strong><span>提炼当前研判对话中的有效流程</span></button></div></Modal></Show>
      <Show when={creator() === "source"}><Modal title="从需求创建 Skill" text="描述需要固化的研判目标、数据范围和输出要求。" wide onClose={() => setCreator(undefined)}><Field label="研判需求" required><textarea rows={8} value={skillRequirement()} onInput={(event) => setSkillRequirement(event.currentTarget.value)} placeholder="例如：分析目标人员最近30天夜间活动和共同出现人员" /></Field><div class="modal-actions"><Button onClick={() => setCreator("choose")}>上一步</Button><Button variant="primary" busy={draftBusy()} onClick={() => void generateSkill("requirement")}>AI 提炼生成</Button></div></Modal></Show>
      <Show when={creator() === "edit" && skillDraft()}>{(value) => <Modal title="编辑 Skill" text={`来源：${creatorSource() === "conversation" ? "当前对话" : "需求描述"} · 状态：${draftStatusText(value().status)}`} wide onClose={() => setCreator(undefined)}><Show when={["preparing","generating"].includes(value().status)}><div class="runtime-banner"><Spinner/><span>系统正在生成草稿，完成后将自动刷新。</span></div></Show><div class="form-grid"><Field label="Skill 名称" required><input disabled={["preparing","generating"].includes(value().status)} value={value().name} onInput={(event) => setSkillDraft({ ...value(), name: event.currentTarget.value })} /></Field><Field label="使用场景"><input disabled={["preparing","generating"].includes(value().status)} value={value().description} onInput={(event) => setSkillDraft({ ...value(), description: event.currentTarget.value })} /></Field></div><Field label="Skill 内容（SKILL.md）" required><textarea disabled={["preparing","generating"].includes(value().status)} class="skill-editor" value={value().content} onInput={(event) => setSkillDraft({ ...value(), content: event.currentTarget.value })} /></Field><Field label="模型试运行输入"><input value={draftTestText()} onInput={(event) => setDraftTestText(event.currentTarget.value)} placeholder="填写合成测试输入；不会使用当前对话原文" /></Field><Show when={value().error}><ErrorLine message={value().error?.message}/></Show><div class="modal-actions"><Button disabled={!['ready','needs_review'].includes(value().status)} onClick={() => void testDraft("validation")}>结构检查</Button><Button disabled={value().status !== "ready"} onClick={() => void testDraft("model")}>模型试运行</Button><Button variant="primary" disabled={value().status !== "ready"} onClick={() => void saveDraft()}>保存到个人 Skill</Button></div></Modal>}</Show>
      <Show when={skillEditor()}>{(value) => <Modal title="编辑个人 Skill" text="个人 Skill 仅当前账号可见，可在能力选择弹窗中继续使用。" wide onClose={() => setSkillEditor(undefined)}><div class="form-grid"><Field label="Skill 名称" required><input value={value().name} onInput={(event) => setSkillEditor({ ...value(), name: event.currentTarget.value })} /></Field><Field label="使用场景"><input value={value().description ?? ""} onInput={(event) => setSkillEditor({ ...value(), description: event.currentTarget.value })} /></Field></div><Field label="Skill 内容（SKILL.md）" required><textarea class="skill-editor" value={value().content ?? ""} onInput={(event) => setSkillEditor({ ...value(), content: event.currentTarget.value })} /></Field><div class="modal-actions split"><Button variant="danger" onClick={() => void deletePersonalSkill()}>删除</Button><span /><Button onClick={() => void testPersonalSkill()}>测试运行</Button><Button variant="primary" onClick={() => void savePersonalSkill()}>保存</Button></div></Modal>}</Show>
      <Show when={rename()}>
        <Modal title="重命名对话" onClose={() => setRename(undefined)}>
          <form onSubmit={saveTitle}>
            <Field label="对话名称">
              <input
                required
                maxlength={100}
                value={title()}
                onInput={(event) => setTitle(event.currentTarget.value)}
              />
            </Field>
            <div class="modal-actions">
              <Button type="submit" variant="primary">
                保存名称
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
    </div>
  )
}

function terminalRun(status: Run["status"]) {
  return ["completed", "failed", "cancelled"].includes(status)
}
function mergeRunEvents(current: RunEvent[], incoming: RunEvent[]) {
  return [...new Map([...current, ...incoming].sort((a, b) => a.sequence - b.sequence).map((item) => [item.step_id ?? item.id, item])).values()]
}
function normalizeSkillDraft(value: SkillDraft): SkillDraft {
  return { ...value, name: value.name ?? "", description: value.description ?? "", content: value.content ?? "", dependency_ids: value.dependency_ids ?? [], input_schema: value.input_schema ?? {}, default_rules: value.default_rules ?? [] }
}
function draftStatusText(status: SkillDraft["status"]) {
  return ({ preparing: "准备中", generating: "生成中", ready: "可编辑", needs_review: "需要人工复核", failed: "生成失败", saved: "已保存" } as Record<SkillDraft["status"], string>)[status]
}
