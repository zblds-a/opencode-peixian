export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Role = "super_admin" | "admin" | "user"
export type Capability =
  | "business.use"
  | "users.manage"
  | "admins.manage"
  | "models.manage"
  | "audit.read"
  | "plugins.manage"
  | "connections.manage"
  | "templates.manage"
  | "runtimes.manage"
  | "jobs.read"
export type User = {
  id: string
  username: string
  avatar?: string
  role: Role
  must_change_password: boolean
  active?: boolean
  model_ids?: string[]
  plugin_ids?: string[]
  runtime?: { id?: string; status: string; revision?: number; desired?: number; error?: string; phase?: string;
    security_blocked?: boolean; cancellation_confirmed?: boolean; recovery_required?: boolean; gate_policy?: string;
    runtime_mode?: "on_demand"; ready?: boolean; state_version?: number; stop_reason?: string; manual_stop_reason?: string;
    maintenance_mode?: "normal" | "frozen" | "repair_only";
    interaction?: { can_submit_new: boolean; can_observe: boolean; can_continue: boolean };
    waiting?: { expires_at: number; approximate_position: number } | null;
    wait_result?: string | null;
    allowed_actions?: string[]; job?: { id: string; action: string; status: string } | null }
  display_name?: string
  police_no?: string
  department_id?: string
  department?: { id: string; name: string; code?: string }
  position?: string
  system_role?: Role
  last_login_at?: string | number
}
export type Auth = { user: User; csrf_token: string; capabilities: Capability[] }
export type Session = { id: string; title: string; status?: string; updated_at?: string; time?: { updated?: number } }
export type Part = {
  id?: string
  type: string
  text?: string
  origin?: "verified_result" | string
  run_id?: string
  step_id?: string
  call_id?: string | null
  execution?: RunEvent
  data?: Json | AnalysisResult
  tool?: string
  details?: { inputs?: Record<string, string | number | boolean>; outputs?: Record<string, string | number | boolean> }
  state?: { status?: string; title?: string; output?: string; error?: string }
}
export type Message = {
  attachments?: { id: string; name: string; status: "available" | "unavailable" }[]
  info: {
    id: string
    role: string
    run_id?: string
    turn_id?: string
    parentID?: string | null
    error?: { message?: string; data?: { message?: string } }
    time?: { created?: number; completed?: number }
    finish?: string
  }
  parts: Part[]
}
export type Model = {
  id: string
  name: string
  description?: string
  is_default?: boolean
  enabled?: boolean
  base_url?: string
  model_id?: string
  api_key_configured?: boolean
  provider?: string
  context_length?: number
  access_mode?: "api" | "local"
  supports_tools?: boolean
  test_status?: string
  updated_at?: number
}
export type FileItem = {
  id: string
  name: string
  size?: number
  status?: string
  truncated?: boolean
  error?: string
  created_at?: string
  created?: number
}
export type Skill = {
  id: string
  name: string
  description?: string
  content?: string
  enabled?: boolean
  version?: number
  versions?: number[]
  owner_id?: string
  source_type?: "manual" | "requirement" | "conversation"
  dependency_ids?: string[]
  input_schema?: Record<string, Json>
  default_rules?: string[]
  scope?: "personal" | "department" | "public"
  updated_at?: number
}
export type AnalysisStep = {
  id: string
  title: string
  detail?: string
  time?: string
  status: "pending" | "running" | "completed" | "failed"
}
export type SubjectProfile = {
  id: string
  name: string
  fields: { label: string; value: string }[]
  tags?: string[]
}
export type AnalysisEvidenceCard = {
  type: "trajectory" | "companion" | "vehicle" | "place" | string
  title: string
  value?: string | number
  unit?: string
  summary?: string
  items?: string[]
  clue_id?: string
}
export type AnalysisClue = {
  diagram_run_id?: string
  message_id?: string
  id: string
  type: "person" | "vehicle" | "place" | "trajectory" | string
  title: string
  headline: string
  summary: string
  time?: string
  level?: string
  source?: string
  discoveries: string[]
  evidence: { type: string; label: string; content: string; source_ids?: string[]; record_id?: string; occurred_at?: string | null; synthetic?: boolean; verification_status?: string }[]
}
export type AnalysisResult = {
  diagram?: import("./event-diagram").EventDiagram | null
  schema: "peixian.analysis-result"
  version: "1.0"
  run_id?: string
  generated_at?: string
  intro?: string
  process: AnalysisStep[]
  subjects: SubjectProfile[]
  conclusions: string[]
  evidence: AnalysisEvidenceCard[]
  next_steps?: string
  next_steps_status?: "available" | "no_verified_suggestion"
  public_markdown?: string
  missing_details?: { id: string; category: "scope_limit" | "source_missing" | "verification_pending"; text: string; source_ids: string[] }[]
  recommendations?: { id: string; type: "request_information" | "manual_review"; text: string; gap_refs: string[]; source_ids: string[]; actionable: false }[]
  conclusion_sources?: { text: string; clue_id?: string; source_ids: string[] }[]
  source_metadata?: Record<string, Json>
  missing?: string[]
  presentation_version?: string
  clues: AnalysisClue[]
}
export type CapabilityItem = {
  id: string
  kind: "skill" | "plugin"
  source_kind?: "personal_skill" | "plugin" | "official_skill"
  name: string
  description?: string
  version: string
  category: string
  recommended: boolean
  enabled: boolean
  owned: boolean
  scope: string
  available?: boolean
  unavailable_reason?: string | null
  dependency_ids?: string[]
}
export type SkillDraft = {
  id: string
  session_id?: string
  source_type: "requirement" | "conversation"
  name: string
  description: string
  content: string
  dependency_ids: string[]
  input_schema: Record<string, Json>
  default_rules: string[]
  status: "preparing" | "generating" | "ready" | "needs_review" | "failed" | "saved"
  run_id?: string | null
  saved_skill_id?: string | null
  scope: "personal"
  error?: { code: string; message: string } | null
  created_at: string
  updated_at: string
}
export type RunEvent = {
  id: string
  step_id?: string
  run_id?: string
  call_id?: string | null
  message_id?: string | null
  part_id?: string | null
  sequence: number
  step_type: string
  name: string
  status: string
  started_at?: string | null
  completed_at?: string | null
  elapsed_ms?: number | null
  capability_id?: string | null
  capability_name?: string | null
  capability_version?: string | null
  input_summary?: string
  output_summary?: string
  result?: Record<string, string | number | boolean | null>
  result_truncated?: boolean
  record_count?: number
  evidence_refs?: string[]
  error_message?: string | null
}
export type Run = {
  outcome?: { version: string; status: string; label: string; message: string; next_steps: string[]; execution_status: string; data_status: string; queried: boolean | null }
  clarification?: { version: "theft-clarification-v1"; id: string; missing: string[] } | null
  id: string
  session_id: string
  status: "queued" | "running" | "cancelling" | "reconciling" | "completed" | "failed" | "cancelled"
  phase: string
  cancel_requested?: boolean
  model_id?: string
  message_id?: string | null
  user_message_id?: string
  parent_run_id?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  updated_at?: string
  error?: { code: string; message: string } | null
}
export type RunEvidence = {
  run_id: string
  status: "pending" | "empty" | "partial" | "complete" | "unavailable"
  notice?: string
  cards: Json[]
  summary: Json[]
  missing?: string[]
}
export type Evidence = {
  conclusion: { confidence: string; summary: string }
  tabs: { trajectory: Json[]; places: Json[]; companions: Json[] }
  chain: { type: string; label: string }[]
  conditions: Record<string, Json>
  mock?: boolean
}
export type Department = { id: string; name: string; parent_id?: string | null; code?: string; sort_order: number; updated_at?: string; children?: Department[] }
export type Invocation = {
  id: string
  run_id: string
  session_id?: string
  created?: number
  created_at?: string | number
  username?: string
  display_name?: string
  department_name?: string
  model_name?: string
  skill_ids: string[]
  plugin_ids: string[]
  actual_plugin_ids?: string[]
  model_id?: string
  status: string
  duration_ms?: number
  record_count: number
  query_summary: string
  steps?: RunEvent[]
}
export type CredentialState = boolean | { [key: string]: CredentialState }
export type Schema = {
  type?: string
  title?: string
  description?: string
  properties?: Record<string, Schema>
  required?: string[]
  enum?: Json[]
  default?: Json
  writeOnly?: boolean
  format?: string
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  items?: Schema
  minItems?: number
  maxItems?: number
}
export type Plugin = {
  id: string
  name: string
  description?: string
  version: string
  versions?: (string | { version: string; enabled?: boolean; connections?: ConnectionAliases })[]
  connections?: ConnectionAliases
  connection_status?: Record<string, { ready: boolean; missing: string[] }>
  enabled?: boolean
  config_schema?: Schema
  schemas?: Record<string, Schema>
  installed?: {
    version: string
    enabled: boolean
    config?: Record<string, Json>
    credentials_configured?: CredentialState
    state?: string
    missing_connections?: string[]
  }
}
export type ConnectionAliases = Record<string, { description: string }>
export type ServiceConnection = {
  id: string
  name: string
  base_url: string
  auth_type: "none" | "bearer" | "api_key"
  header_name: string
  allowed_methods: string[]
  allowed_paths: string[]
  timeout_seconds: number
  max_response_bytes: number
  enabled: boolean
  secret_configured: boolean
  revision: number
}
export type Job = {
  id: string
  type?: string
  action?: string
  status: string
  user_id?: string
  uid?: string
  username?: string
  error?: string
  created_at?: string
  created?: number
}
export type Audit = {
  id: string
  action?: string
  actor?: string
  actor_role?: Role
  result?: "success" | "denied" | "failed"
  username?: string
  target?: string
  status?: string
  created_at?: string
  created?: number
  detail?: string
}
