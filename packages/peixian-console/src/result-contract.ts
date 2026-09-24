import {isDiagram} from "./event-diagram"
import type { AnalysisResult, Run } from "./types"

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === "string")
}
function displayArrays(value: Record<string, unknown>) {
  return Array.isArray(value.process) && value.process.every(item => object(item) && typeof item.id === "string" && typeof item.title === "string" && ["pending", "running", "completed", "failed"].includes(String(item.status)))
    && Array.isArray(value.evidence) && value.evidence.every(item => object(item) && typeof item.type === "string" && typeof item.title === "string" && (item.items === undefined || strings(item.items)))
    && Array.isArray(value.clues) && value.clues.every(item => object(item) && typeof item.id === "string" && typeof item.title === "string" && typeof item.type === "string" && typeof item.headline === "string" && typeof item.summary === "string" && strings(item.discoveries) && Array.isArray(item.evidence) && item.evidence.every(row => object(row) && typeof row.type === "string" && typeof row.label === "string" && typeof row.content === "string"))
}
export function isAnalysisResult(value: unknown): value is AnalysisResult {
  return object(value) && value.schema === "peixian.analysis-result" && value.version === "1.0" && displayArrays(value) && Array.isArray(value.subjects) && strings(value.conclusions)
}

// Use only for the authenticated session evidence endpoint, never model message data.
export function legacyPresentation(value: unknown): AnalysisResult | undefined {
  if (!object(value) || value.schema !== undefined || value.version !== "1.0" || !displayArrays(value) || !Array.isArray(value.conclusions) || !value.conclusions.every(item => object(item) && typeof item.text === "string" && strings(item.source_ids) && (item.clue_id === undefined || typeof item.clue_id === "string")) || !strings(value.missing)) return
  const sources = value.conclusions as NonNullable<AnalysisResult["conclusion_sources"]>
  return { schema: "peixian.analysis-result", version: "1.0", process: value.process as AnalysisResult["process"], subjects: [], conclusions: sources.map(item => item.text), conclusion_sources: sources, evidence: value.evidence as AnalysisResult["evidence"], clues: value.clues as AnalysisResult["clues"], missing: value.missing, presentation_version: value.version, diagram: isDiagram(value.diagram) ? value.diagram : undefined }
}
// The server projects only approved source facts into this display contract.
export function sourcePresentation(value: unknown, runID: string): AnalysisResult | undefined {
  if (!object(value) || value.schema !== "peixian.analysis-result" || value.version !== "2.0" || value.run_id !== runID || !object(value.presentation)) return
  const presentation = value.presentation
  if (presentation.version !== "source-clues-v1" || !["ready", "partial", "empty"].includes(String(presentation.status)) || !Array.isArray(presentation.clues)) return
  const valid = presentation.clues.every((clue) => object(clue) && typeof clue.id === "string" && typeof clue.type === "string" && typeof clue.title === "string" && typeof clue.headline === "string" && typeof clue.summary === "string" && strings(clue.discoveries) && Array.isArray(clue.evidence) && clue.evidence.every((row: unknown) => object(row) && typeof row.id === "string" && typeof row.label === "string" && typeof row.content === "string"))
  if (!valid) return
  const clues = presentation.clues.map((clue) => ({
    id: clue.id,
    type: clue.type,
    title: clue.title,
    headline: clue.headline,
    summary: clue.summary,
    discoveries: clue.discoveries,
    evidence: clue.evidence.map((row: Record<string, unknown>) => ({ id: row.id, type: "source", label: row.label, content: row.content, record_id: typeof row.record_id === "string" ? row.record_id : undefined, occurred_at: typeof row.occurred_at === "string" ? row.occurred_at : null, source_run_id: typeof row.source_run_id === "string" ? row.source_run_id : undefined })),
  })) as AnalysisResult["clues"]
  return { schema: "peixian.analysis-result", version: "1.0", run_id: runID, process: [], subjects: [], conclusions: [], evidence: [], clues, missing: strings(presentation.missing) ? presentation.missing : [], presentation_version: "source-clues-v1" }
}
export function acceptedRun(value: unknown, session: string): Run {
  if (!object(value) || value.accepted !== true || typeof value.run_id !== "string" || !value.run_id || typeof value.message_id !== "string" || !value.message_id) throw new Error("提交结果待确认，请核对执行记录，不要重复提交。")
  return { id: value.run_id, session_id: session, status: "queued", phase: "accepted", user_message_id: value.message_id, created_at: "" }
}
