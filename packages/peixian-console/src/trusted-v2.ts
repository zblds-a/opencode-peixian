export type TaskContext = {
  agent_id: string
  generation: number
  version: number
  pending_clarification_id: string | null
}
export type AgentChoice = { id: string; name: string; version: string }
export type Claim = {
  agent_id: string
  claim_id: string
  type: "fact" | "computed" | "gap"
  statement: string
  source_ids: string[]
  verification_status: "approved"
  protected_fields: Record<string, unknown>
  source_run_id: string
}
export type Usage = {
  status: string
  queried: boolean | null
  new_call_count: number
  reuse_count: number
  source_data_run_id: string | null
  modules: { module: string; status: string; response_confirmed: boolean }[]
}
export type PersonTableAnswer = {
  version: "person-tables-v1"
  markdown?: string
  run_id: string
  person_ref: string | null
  status: "ready" | "partial"
  basic: { label: string; value: string; source_ids: string[]; source_run_id: string; obtained_at: string | null }[]
  conclusions: { text: string; source_ids: string[]; source_run_id: string; claim_id: string; limitation: string }[]
  evidence: { module: string; label: string; time: string; text: string; source_ids: string[]; source_run_id: string; snapshot_id: string }[]
  suggestions: { text: string; reason: string; conditions: string; source_ids: string[]; origin: "model_selection" | "platform_direction"; action: "query" | "inspect_sources" | "clarify_scope" | "authorize_candidates"; kind: string | null; reply?: string }[]
  next_question?: {
    id: string
    header: string
    question: string
    options: { label: string; description?: string; action: string; send: boolean }[]
    custom: boolean
  }
  missing: string[]
  preview_count: number
  total: number
  source_runs: string[]
  selection_status: "accepted" | "fallback"
}
export type TrustedResult = {
  schema: "peixian.analysis-result"
  version: "2.0" | "legacy"
  run_id: string
  status?: "pending" | "legacy"
  agent?: { id: string; version: string }
  task?: Record<string, unknown>
  data_environment?: string
  data_usage?: Usage
  claims?: Claim[]
  records?: Record<string, unknown>[]
  missing?: string[]
  versions?: Record<string, unknown>
  generated_at?: string
  answer?: { version: string; status: string; summary: string; items: { text: string; claim_id: string; source_run_id: string; source_ids: string[] }[]; missing: string[]; next_steps: string[] }
  answer_view?: PersonTableAnswer
  narrative?: { status: string; text: string | null; conflicts: { message: string }[]; coverage: string }
}
export const usageLabels: Record<string, string> = {
  not_started: "尚未发起资料查询",
  in_flight: "资料查询处理中",
  confirmed: "本轮已取得资料",
  partial: "本轮仅取得部分资料",
  reused_current_run: "复用本轮已取得资料",
  historical_evidence: "使用历史可信结果，未重新查询",
  unknown: "请求可能已发出，但结果未确认，不会自动重试",
  rejected: "资料暂不可采用",
  cancelled: "查询已取消或未发起",
}
export const narrativeLabels: Record<string, string> = {
  verified: "已通过冲突检查",
  unverified: "尚未通过核验，仅作辅助说明",
  conflicted: "存在冲突，未作为可信结论",
  not_generated: "尚未生成",
}
export const taskLabels: Record<string, string> = {
  query_mode: "查询方式",
  intent: "任务",
  methods: "方法",
  target_refs: "对象",
  target_mode: "对象模式",
  scenario_id: "场景",
  source_data_run_id: "历史来源执行",
}
const values: Record<string, string> = {
  portrait: "人像共现",
  vehicle: "车辆",
  calls: "话单",
  lookup: "关联互查",
  same_frame: "同框",
  same_trip: "明确同行",
  same_vehicle: "明确同乘",
  alone: "明确独行观测",
  unknown: "无法判断",
  new_query: "本轮查询",
  history_explanation: "解释历史资料",
  night_activity: "夜间活动整理",
  companions_check: "同行与共现核对",
  funds_analysis: "资金往来整理",
  relations_check: "已有关系核对",
  vehicle_activity: "车辆活动整理",
  integrated_analysis: "综合资料整理",
  default_subject: "场景对象",
  explicit_subject: "指定对象",
  confirmed_entity: "已确认对象",
  "DEMO-CASE-GAMBLING": "涉赌资料整理",
  "DEMO-CASE-THEFT": "盗窃时空核对",
  explain_previous: "解释历史资料",
  clarify: "需要确认",
  ordinary_chat: "普通交流",
  funds: "资金",
  night: "夜间活动",
  companions: "同行与共现",
  relations: "已有关系",
  vehicles: "车辆",
  composite: "综合整理",
  gambling: "涉赌资料整理",
  theft: "盗窃时空核对",
  synthetic: "合成测试环境",
}
export function label(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未提供"
  if (Array.isArray(value)) return value.map(label).join("、") || "未指定"
  if (typeof value === "object") return JSON.stringify(value)
  return values[String(value)] ?? String(value)
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(x=>typeof x === "string")
}
export function ownedResult(value: unknown, run: string, expectedAgent?: string): value is TrustedResult {
  if (!object(value)) return false
  const x = value
  if (x.schema !== "peixian.analysis-result" || x.run_id !== run) return false
  if (x.version === "legacy") return x.status === "legacy"
  if (x.version !== "2.0" || x.data_environment !== "synthetic" || !object(x.data_usage) || !Object.hasOwn(usageLabels,String(x.data_usage.status))) return false
  if (x.status === "pending") return true
  if (!object(x.agent) || !["theft-assistant","gambling-assistant"].includes(String(x.agent.id)) || (expectedAgent && x.agent.id !== expectedAgent)) return false
  const agent = x.agent.id, usage = x.data_usage
  const claims = x.claims
  if (!Array.isArray(claims) || !claims.every(c=>object(c) && c.agent_id === agent && ["fact","computed","gap"].includes(String(c.type)) && c.verification_status === "approved" && typeof c.statement === "string" && strings(c.source_ids))) return false
  // Unknown/not-started cannot authenticate factual cards. Partial may retain only confirmed modules.
  if (["unknown","not_started","in_flight"].includes(String(usage.status)) && claims.some(c=>c.type!=="gap")) return false
  return Array.isArray(x.records) && x.records.every(object) && strings(x.missing) && object(x.narrative) && Object.hasOwn(narrativeLabels,String(x.narrative.status))
}
export function allowLegacyEvidence(currentRun?: string, boundary?: {run_id:string;version:string}, evidenceRun?:string):boolean {
  if (!currentRun) return true
  return boundary?.run_id===currentRun && boundary.version==="legacy" && evidenceRun===currentRun
}

export const fieldLabels: Record<string, string> = {
  record_id: "来源编号",
  module: "资料类别",
  source_type: "记录类型",
  data_source_id: "数据来源",
  snapshot_id: "资料快照",
  occurred_at: "记录时间",
  kind: "观测类型",
  member_ref: "记录对象",
  co_member_ref: "共现对象",
  group_ref: "关联对象",
  subject_ref: "范围对象",
  direction: "方向",
  amount_minor: "金额（分）",
  counterparty_ref: "对手方引用",
  transaction_ref: "交易引用",
  device_ref: "设备引用",
  source_record_ids: "原始来源引用",
  scenario_snapshot_id: "场景快照",
  records_snapshot_id: "资料快照",
  registry: "能力与规则版本",
  plugin_versions: "插件版本",
}

export function controlledAnswer(result: TrustedResult) {
  const answer = result.answer
  if (!answer || answer.version !== "controlled-zh-v1" || !["ready", "partial", "needs_input", "unavailable"].includes(answer.status)
    || typeof answer.summary !== "string" || !Array.isArray(answer.items) || answer.items.length > 5
    || !strings(answer.missing) || !strings(answer.next_steps) || answer.next_steps.length > 2) return undefined
  const claims = new Map((result.claims ?? []).map(claim => [claim.claim_id, claim]))
  if (!answer.items.every(item => {
    if (!object(item) || typeof item.text !== "string" || !strings(item.source_ids)) return false
    const claim = claims.get(item.claim_id)
    return !!claim && claim.verification_status === "approved" && item.source_run_id === claim.source_run_id
      && item.source_ids.length === claim.source_ids.length && item.source_ids.every(id => claim.source_ids.includes(id))
  })) return undefined
  return answer
}
