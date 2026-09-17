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
  role: Role
  must_change_password: boolean
  active?: boolean
  model_ids?: string[]
  plugin_ids?: string[]
  runtime?: { id?: string; status: string; revision?: number; error?: string }
  display_name?: string
  police_no?: string
  department_id?: string
  department?: { id: string; name: string; code?: string }
  position?: string
  system_role?: Role
  last_login_at?: number
}
export type Auth = { user: User; csrf_token: string; capabilities: Capability[] }
export type Session = { id: string; title: string; status?: string; updated_at?: string; time?: { updated?: number } }
export type Part = {
  id?: string
  type: string
  text?: string
  data?: Json | AnalysisResult
  tool?: string
  details?: { inputs?: Record<string, string | number | boolean>; outputs?: Record<string, string | number | boolean> }
  state?: { status?: string; title?: string; output?: string; error?: string }
}
export type Message = {
  info: {
    id: string
    role: string
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
}
export type AnalysisClue = {
  id: string
  type: "person" | "vehicle" | "place" | "trajectory" | string
  title: string
  headline: string
  summary: string
  time?: string
  level?: string
  source?: string
  discoveries: string[]
  evidence: { type: string; label: string; content: string }[]
}
export type AnalysisResult = {
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
  clues: AnalysisClue[]
}
export type CapabilityItem = {
  id: string
  kind: "skill" | "plugin"
  name: string
  description?: string
  version: string
  category: string
  recommended: boolean
  enabled: boolean
  owned: boolean
  scope: string
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
}
export type RunEvent = {
  id: string
  sequence: number
  step_type: string
  name: string
  status: string
  started?: number
  completed?: number
  input_summary?: string
  output_summary?: string
  record_count?: number
  error?: string
}
export type Evidence = {
  conclusion: { confidence: string; summary: string }
  tabs: { trajectory: Json[]; places: Json[]; companions: Json[] }
  chain: { type: string; label: string }[]
  conditions: Record<string, Json>
  mock?: boolean
}
export type Department = { id: string; name: string; parent_id?: string; code?: string; sort_order: number }
export type Invocation = {
  id: string
  run_id: string
  created: number
  username?: string
  display_name?: string
  department_name?: string
  model_name?: string
  skill_ids: string[]
  plugin_ids: string[]
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
