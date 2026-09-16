# 沛警智枢后端接口与服务完善需求说明书

## 1. 文档目的

本文档用于指导后端团队完成“沛警智枢——沛县公安智能研判平台”的正式后端开发、接口补齐和联调。本文档以当前前端终版页面、现有 `peixian-control` 服务和需求规格说明书为依据，是前后端接口冻结、任务拆分和验收的直接输入。

本文中的“已存在”表示代码中已有路由或基础数据结构，不代表已经达到生产可用标准。当前分支中运行轨迹、证据链、Skill 草稿、调用审计等部分接口主要用于前端 Mock 联调，后端仍需按本文完成真实业务闭环。

### 1.1 接口统一前缀

所有浏览器可访问接口统一使用：

```text
/api/console/v1
```

本文后续接口省略该前缀。

### 1.2 最终业务范围

后端需要支持：

- 账号密码登录、退出登录、个人主动改密和管理员重置密码；登录后不执行首次强制改密。
- 民警智能研判：会话、文件、模型、个人 Skill、深度研判、执行轨迹、证据链、重新研判和报告导出。
- Skill Creator：从自然语言需求或当前对话生成个人 Skill。
- 管理端：模型管理、用户与部门、调用审计。
- 管理员隐藏能力配置：官方 Skill、插件工具、依赖、启停和连通测试。
- 公安数据服务适配：人员、家庭关系、轨迹、涉案、涉警，以及后续场所、同行、车辆等能力。

以下模块不再作为独立产品功能开发：我的智能体、Skill 中心、插件中心、插件管理页面、Skill 审核页面、部门/公共 Skill 发布审批、短信登录、联网搜索。

## 2. 当前实现评估

| 模块 | 当前情况 | 后端正式开发要求 |
| --- | --- | --- |
| 登录认证 | 基本可用 | 补齐登录安全日志、限流、最近登录和组织身份字段 |
| 会话和消息 | 可代理现有 Runtime | 将消息、运行、事件、证据、报告和审计通过 `run_id` 串成完整链路 |
| 执行轨迹 | 已有数据库表和查询骨架 | 接入真实 Runtime 事件，提供实时推送、失败和取消状态 |
| 证据链 | 当前返回 Mock 结构 | 将公安工具返回记录规范化、持久化并生成可追溯证据引用 |
| Skill Creator | 当前为规则模板拼接 | 接入模型提炼、依赖识别、参数生成、安全校验和真实测试 |
| 能力目录 | 已有聚合骨架 | 实现部门/用户可见范围、依赖有效性和统一授权判断 |
| 模型管理 | 已扩充基础字段 | 实现分页筛选、真实连接测试、默认唯一约束和凭据安全存储 |
| 用户与部门 | 已有基础表和 CRUD | 实现完整树校验、筛选分页、组织同步策略和登录约束 |
| 调用审计 | 已有基础记录 | 实现运行完成回写、详情、筛选、导出、脱敏和留存策略 |
| 公安接口适配 | 未正式接入 | 建立统一工具适配层，禁止浏览器直接访问数据源 |

## 3. 总体技术和安全要求

### 3.1 身份和权限

系统角色与警务职务必须分开保存：

- `system_role`：`user`、`admin`、`super_admin`，用于权限判定。
- `position`：民警、中队长、科员、副大队长等，仅用于展示、检索和统计。

权限最低要求：

| 能力 | user | admin | super_admin |
| --- | --- | --- | --- |
| 智能研判及本人数据 | 允许 | 禁止 | 禁止 |
| 用户、部门、模型管理 | 禁止 | 允许 | 允许 |
| 调用审计 | 禁止 | 允许，只读脱敏 | 允许，只读脱敏 |
| 官方能力配置 | 禁止 | 按授权决定 | 允许 |
| 管理员账号维护 | 禁止 | 禁止 | 允许 |

普通用户的会话、文件、个人 Skill、草稿、运行记录和证据必须按 `uid` 强隔离。后端不能依赖前端隐藏按钮实现权限控制。

### 3.2 认证安全

- Cookie 会话保持 `HttpOnly`、`SameSite=Strict`；HTTPS 环境必须启用 `Secure`。
- Cookie 写请求继续校验 CSRF 和精确 Origin。
- 登录失败统一返回“账号或密码错误”，不能暴露账号是否存在、是否禁用等内部原因。
- 同一账号连续失败需要限流。建议 5 分钟内连续 5 次失败后延迟或临时锁定，并记录安全日志。
- 禁用账号、改密、管理员重置密码、注销时立即撤销旧会话和访问令牌。
- 所有 API Key、公安数据源凭据只写不读；响应只返回 `*_configured: true/false`。
- 当前公安接口资料中出现过接口密钥、应用密钥和真实身份证样例。这些凭据必须在正式接入前轮换，并迁移至部署密钥存储；不得复制进代码、数据库明文字段、前端、测试样例或日志。

### 3.3 通用数据约定

- ID 使用后端生成的不透明字符串，前端不得解析其含义。
- 时间字段统一使用 Unix 秒级时间戳；同一接口不得混用毫秒和秒。
- 列表接口返回：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

- `page` 从 1 开始；`page_size` 默认 20，最大 100。
- 排序字段必须采用白名单，禁止直接拼接客户端传入 SQL。
- 所有响应增加 `X-Request-ID`；跨 Runtime、模型和公安数据源调用时沿用同一个 `trace_id`。
- 更新接口采用字段白名单，未知字段返回 400，不能静默忽略。
- 删除操作不存在资源时返回 404；存在业务依赖无法删除时返回 409。

### 3.4 通用错误格式

```json
{
  "message": "面向用户的安全提示",
  "code": "department_not_empty",
  "request_id": "opaque-request-id",
  "details": {}
}
```

`details` 可省略，且不得含堆栈、SQL、内部地址、API Key、身份证完整号码或上游原始响应。

建议固定错误码：

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `invalid_request` | 字段、格式或状态不合法 |
| 401 | `authentication_required` | 未登录或会话失效 |
| 403 | `permission_denied` | 角色或数据权限不足 |
| 404 | `resource_not_found` | 资源不存在或不属于当前用户 |
| 409 | `resource_conflict` | 重名、默认模型冲突、部门非空等 |
| 413 | `payload_too_large` | 文件或请求上下文超限 |
| 422 | `validation_failed` | 参数结构校验未通过 |
| 429 | `rate_limited` | 登录或业务查询频率过高 |
| 502 | `upstream_invalid_response` | 上游响应异常 |
| 503 | `upstream_unavailable` | Runtime、模型或业务数据源不可用 |
| 504 | `upstream_timeout` | 上游超时 |

## 4. 认证与当前用户

### 4.1 账号登录

```http
POST /auth/login
```

请求：

```json
{
  "username": "320722001",
  "password": "user-password"
}
```

成功响应：

```json
{
  "user": {
    "id": "uid",
    "username": "320722001",
    "display_name": "张三",
    "police_no": "320722001",
    "department_id": "dept-id",
    "department": { "id": "dept-id", "name": "刑警大队", "code": "..." },
    "position": "民警",
    "system_role": "user",
    "active": true,
    "must_change_password": false,
    "last_login_at": 1789520000,
    "runtime": { "status": "ready" }
  },
  "csrf_token": "session-csrf-token",
  "capabilities": ["business.use"]
}
```

后端要求：

- 登录成功、失败、禁用账号尝试都写入 `login_events`。
- 日志字段至少包括：账号输入值的安全摘要、匹配用户 ID（如有）、结果、客户端 IP、User-Agent、时间、request_id。
- 登录成功后更新 `last_login_at`，失败不得更新。
- `GET /me` 返回与登录一致的用户结构。
- `POST /me/password`、`POST /auth/logout` 和管理员重置密码继续沿用现有接口。

## 5. 智能研判、会话和运行

### 5.1 消息提交

目标接口：

```http
POST /sessions/{session_id}/messages
```

目标请求体：

```json
{
  "text": "分析目标人员最近30天夜间活动情况",
  "model_id": "model-id",
  "skill_ids": ["skill-id"],
  "file_ids": ["file-id"],
  "mode": "deep_research"
}
```

字段要求：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| text | 是 | 1～32000 字符，不允许全空白 |
| model_id | 否 | 必须是当前用户已授权且启用的模型；省略时使用默认模型 |
| skill_ids | 否 | 最多 5 个，仅当前用户有权使用且启用的 Skill |
| file_ids | 否 | 最多 5 个，仅当前用户 `ready` 且未截断的文件 |
| mode | 否 | `standard` 或 `deep_research`，默认 `standard` |

兼容期可继续接受 `X-Analysis-Mode` 请求头，但正式契约应以请求体 `mode` 为准，后续前端再移除兼容请求头。

成功返回 HTTP 202：

```json
{
  "accepted": true,
  "run_id": "run-id"
}
```

创建消息时必须在一个事务中完成：

1. 校验会话归属、模型授权、Skill 授权和文件状态。
2. 创建 `run` 记录。
3. 创建调用审计记录。
4. 写入第一条“需求理解”事件或将任务提交到持久队列。
5. 返回 `run_id`。

不得仅在内存中保存运行状态。服务重启后必须能查询已接受运行的最后持久状态。

### 5.2 运行状态

```http
GET /sessions/{sid}/runs/{run_id}
```

返回字段：

```json
{
  "id": "run-id",
  "session_id": "session-id",
  "parent_run_id": null,
  "model_id": "model-id",
  "mode": "deep_research",
  "query_summary": "脱敏后的问题摘要",
  "status": "running",
  "started_at": 1789520000,
  "completed_at": null,
  "duration_ms": null,
  "error_code": null,
  "error_message": null
}
```

运行状态固定为：

```text
accepted -> running -> succeeded
                    -> failed
                    -> cancelled
                    -> timed_out
```

状态只能向终态前进，终态不得被普通回调覆盖。中止请求必须把运行和未完成步骤更新为 `cancelled`，同时通知 Runtime 停止。

### 5.3 执行轨迹历史和实时推送

```http
GET /sessions/{sid}/runs/{run_id}/events
GET /sessions/{sid}/runs/{run_id}/events?after_sequence=3
```

历史查询响应：

```json
{
  "items": [
    {
      "id": "event-id",
      "run_id": "run-id",
      "sequence": 1,
      "step_type": "requirement_understanding",
      "name": "需求理解",
      "status": "succeeded",
      "started_at": 1789520000,
      "completed_at": 1789520001,
      "elapsed_ms": 860,
      "input_summary": "研判最近30天夜间活动",
      "output_summary": "已识别目标对象、时间范围和分析维度",
      "record_count": null,
      "capability_id": null,
      "evidence_refs": [],
      "error_code": null,
      "error_message": null
    }
  ],
  "next_sequence": 2
}
```

步骤类型至少包括：

- `requirement_understanding`：需求理解。
- `skill_loading`：加载 Skill。
- `plugin_call`：调用插件或公安业务工具。
- `data_analysis`：数据清洗、聚合和关联分析。
- `result_generation`：生成结构化结论和报告。

步骤状态固定为 `pending`、`running`、`succeeded`、`failed`、`skipped`、`cancelled`。

实时能力要求：

- 同一路径在 `Accept: text/event-stream` 时提供 SSE，或新增明确的 `/events/stream` 路径。
- SSE 事件至少包括 `run.started`、`run.step.updated`、`run.completed`、`run.failed`、`run.cancelled`。
- 每条 SSE 带递增 `id`/`sequence`，支持 `Last-Event-ID` 断线续传。
- 心跳间隔不超过 20 秒。
- 页面刷新后可以通过历史接口完整回放，无需依赖 SSE 内存缓存。
- 只输出可审计摘要，不得输出模型内部思维过程、提示词秘密或工具原始凭据。

### 5.4 真实运行回写

当前代码只创建默认步骤，未跟随 Runtime 完成状态更新。后端必须提供可信内部回写机制：

- 回写方只能是受信任 Runtime/Worker，不接受浏览器声明执行成功。
- 回写校验运行 ID、账号 ID、步骤序号和幂等键。
- 重复回写不生成重复事件。
- 每次插件调用记录开始、完成、超时、记录数和证据引用。
- 运行结束时统一回写 `completed_at`、`duration_ms`、`record_count`、最终状态和安全错误摘要。
- 同步更新对应调用审计记录。

### 5.5 重新研判

```http
POST /sessions/{sid}/runs/{run_id}/rerun
```

请求：

```json
{
  "conditions": {
    "begin_time": "2026-08-01 00:00:00",
    "end_time": "2026-08-30 23:59:59",
    "dimensions": ["trajectory", "place", "companion"],
    "night_time": { "start": "22:00", "end": "06:00" },
    "companion_threshold": 3
  },
  "model_id": "model-id"
}
```

要求：

- 新建独立 `run_id`，通过 `parent_run_id` 关联原运行。
- 不覆盖原证据、原报告和原审计。
- 重新执行真实业务链路，不能只创建数据库记录。

### 5.6 报告导出

```http
GET /sessions/{sid}/runs/{run_id}/report?format=docx
```

支持 `docx`、`pdf`、`md`，默认建议 `docx`。报告仅允许在运行成功且证据生成完成后导出；未完成返回 409。

报告至少包含：查询条件、目标对象脱敏信息、核心结论、关键统计、轨迹/场所/同行依据、风险提示、数据来源、生成时间、run_id 和免责声明。文件名使用安全字符，响应设置正确的 `Content-Type` 和 `Content-Disposition`。

## 6. 证据链

```http
GET /sessions/{sid}/runs/{run_id}/evidence
```

目标响应：

```json
{
  "run_id": "run-id",
  "conclusion": {
    "summary": "结构化研判摘要",
    "confidence": "high",
    "risk_level": "medium",
    "warnings": []
  },
  "tabs": {
    "trajectory": [],
    "places": [],
    "companions": []
  },
  "chain": {
    "nodes": [],
    "edges": []
  },
  "conditions": {},
  "sources": [],
  "mock": false,
  "generated_at": 1789520000
}
```

证据记录通用字段：

```json
{
  "evidence_id": "evidence-id",
  "type": "trajectory",
  "occurred_at": 1789520000,
  "location_name": "沛县某地点",
  "activity_type": "出现",
  "duration_seconds": 3600,
  "subject_ref": "subject-token",
  "related_subject_refs": [],
  "source": "person_trajectory",
  "source_record_ref": "不可逆摘要或数据源记录号",
  "trace_id": "trace-id",
  "display": {}
}
```

要求：

- 每个结论必须能够引用一个或多个 `evidence_id`。
- 原始上游响应可按安全策略存储在受控区域，但不得直接返回浏览器或写入普通日志。
- `mock=true` 仅允许开发/联调环境；生产环境不得混入 Mock 并标记为正式结论。
- 前端证据链中不再展示“使用 Skill/插件”卡片，但后端仍需在审计中记录真实能力调用。
- 对无数据、部分数据源超时、全部数据源失败三种情况分别返回明确状态，不能将“无数据”当作“低风险”。

## 7. 统一能力目录与个人 Skill

### 7.1 能力目录

```http
GET /capabilities?query=夜间&kind=skill&category=人员分析&page=1&page_size=20
```

返回：

```json
{
  "items": [
    {
      "id": "capability-id",
      "kind": "skill",
      "name": "人员夜间活动分析",
      "description": "...",
      "version": "1.3",
      "category": "人员分析",
      "recommended": true,
      "enabled": true,
      "owned": false,
      "scope": "all",
      "available": true,
      "unavailable_reason": null,
      "dependency_ids": []
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

目录必须同时聚合：

- 当前用户的个人 Skill。
- 当前用户获授权的插件工具。
- 管理员配置且当前用户可见的官方 Skill/插件。

可见范围至少支持 `all`、`department`、`users`。依赖能力停用、缺少授权或连接未配置时，返回 `available=false` 及安全原因；不得允许执行。

### 7.2 个人 Skill 数据结构

扩展 `/skills`，正式保存以下字段：

```json
{
  "id": "skill-id",
  "name": "人员夜间活动分析",
  "description": "使用场景说明",
  "content": "# SKILL.md ...",
  "enabled": true,
  "version": 3,
  "owner_id": "uid",
  "source_type": "conversation",
  "dependency_ids": ["plugin-id"],
  "input_schema": {},
  "default_rules": [],
  "scope": "personal",
  "created_at": 1789520000,
  "updated_at": 1789520000
}
```

用户生成 Skill 的 `scope` 必须由服务端固定为 `personal`，客户端不能通过伪造字段发布到部门或全局。修改保留历史版本；删除后历史运行仍需保留当时版本快照，不能破坏审计。

### 7.3 Skill 草稿生成

```http
POST /skill-drafts/from-requirement
POST /skill-drafts/from-session
GET /skill-drafts/{id}
PATCH /skill-drafts/{id}
POST /skill-drafts/{id}/test
POST /skill-drafts/{id}/save
```

从需求创建：

```json
{
  "requirement": "分析目标人员最近30天夜间活动及共同出现人员"
}
```

从会话创建：

```json
{
  "session_id": "session-id",
  "message_ids": ["message-id-1", "message-id-2"]
}
```

后端正式要求：

1. 校验会话及消息属于当前用户。
2. 从对话中排除系统提示、模型内部思维、凭据、原始身份证号等不应固化内容。
3. 调用受控模型生成名称、描述、依赖、输入参数、默认规则和 `SKILL.md`。
4. 对生成内容执行长度、Markdown、安全指令和依赖白名单校验。
5. 草稿仅所有者可读写，建议 7～30 天自动清理未保存草稿。
6. `test` 必须运行隔离测试，返回步骤、依赖检查、示例输入输出和错误；不能只返回固定“通过”。
7. `save` 固定保存为个人 Skill，并记录来源会话和生成模型用于审计。

## 8. 管理员隐藏能力配置

```http
GET /admin/capabilities
POST /admin/capabilities
PATCH /admin/capabilities/{id}
POST /admin/capabilities/{id}/test
```

需要维护：类型、名称、描述、版本、分类、依赖、可见范围、启停状态、工具配置和凭据配置状态。

建议请求结构：

```json
{
  "kind": "plugin",
  "name": "人员轨迹查询",
  "description": "查询授权范围内的人员活动轨迹",
  "version": "1.0",
  "category": "人员分析",
  "dependency_ids": [],
  "visibility": {
    "scope": "department",
    "department_ids": ["dept-id"],
    "user_ids": []
  },
  "enabled": true,
  "config": {
    "connection_id": "connection-id",
    "timeout_seconds": 30
  },
  "credentials": {
    "app_id": "write-only",
    "app_secret": "write-only"
  }
}
```

正式要求：

- 配置和凭据分开加密存储。
- GET/PATCH 响应不得返回凭据，只返回 `credentials_configured`。
- `test` 执行真实连通性和最小无敏感查询测试，返回测试时间、阶段和安全错误码。
- 禁用被其他能力依赖的能力时返回 409，或要求显式确认并同步将依赖项设为不可用。
- 所有新增、编辑、启停和测试写管理审计。

## 9. 模型管理

### 9.1 查询

```http
GET /admin/models?query=qwen&provider=阿里云&status=enabled&page=1&page_size=20
```

列表字段：名称、Provider、Model ID、Base URL、接入方式、上下文长度、工具调用支持、启停、默认、密钥配置状态、测试状态、最后测试时间、更新时间。

### 9.2 新增和编辑

```http
POST /admin/models
PATCH /admin/models/{id}
```

请求字段：

- `name`、`provider`、`model_id`、`base_url`。
- `api_key`：只写；编辑时省略或空值表示保留原值。
- `access_mode`：`api` 或 `local`。
- `context_length`：正整数。
- `supports_tools`、`enabled`、`is_default`。
- `description`。

约束：

- 同一时刻最多一个启用的默认模型。
- 默认模型不能直接停用；应先切换默认或在同一事务中完成切换。
- Base URL 仅允许 HTTP/HTTPS，不允许 URL 用户信息、查询参数、片段和任意重定向。
- 生产环境建议限制允许的内网/外网目标，防止 SSRF。
- `local` 只有在后端执行器支持时才能启用，否则返回 409。

### 9.3 连接测试

```http
POST /admin/models/{id}/test
```

测试至少验证：网络连接、鉴权、模型 ID、最小文本响应；声明支持工具调用时增加最小工具调用测试。保存测试状态和时间，不记录模型原始敏感响应。

## 10. 用户与部门

### 10.1 用户查询和维护

```http
GET /admin/users?query=张三&department_id=...&position=民警&system_role=user&status=enabled&page=1&page_size=20
POST /admin/users
PATCH /admin/users/{id}
POST /admin/users/{id}/reset-password
GET /admin/users/summary
```

用户字段：

- 账号 `username`。
- 姓名 `display_name`。
- 警号 `police_no`，全局唯一。
- 部门 `department_id`。
- 警务职务 `position`。
- 系统权限 `system_role`。
- 账号状态 `active`。
- 最近登录 `last_login_at`。
- 模型和能力授权。

汇总接口返回 `users`、`departments`、`enabled`。统计口径只统计普通业务账号，并在接口说明中固定口径。

创建/重置密码时，自动生成的密码只允许在本次响应返回一次，不得写日志。用户使用该密码可直接登录，系统不再执行首次登录强制改密；部署方应通过安全渠道交付密码，并保留个人主动改密能力。

### 10.2 部门树

```http
GET /admin/departments/tree
POST /admin/departments
PATCH /admin/departments/{id}
DELETE /admin/departments/{id}
```

部门字段：`id`、`name`、`code`、`parent_id`、`sort_order`、`created_at`、`updated_at`。

必须校验：

- 部门编码唯一。
- 上级部门存在。
- 不能将部门设为自身或其后代的子部门。
- 删除存在子部门或用户的部门返回 409，不级联删除。
- 返回树结构时节点顺序稳定；若继续返回扁平 `items`，必须明确由 `parent_id` 组树。

需由项目方确认部门数据来源是平台维护还是定期同步。如果接组织系统同步，应增加外部 ID、同步状态和“外部维护只读”规则，避免人工编辑被覆盖。

## 11. 调用审计

管理操作审计与业务调用审计必须分表或通过明确类型区分。

```http
GET /admin/invocations
GET /admin/invocations/{id}
GET /admin/invocations/export
```

查询条件：开始/结束时间、关键字、用户、部门、模型、Skill、插件、状态、page、page_size。

列表字段：调用时间、用户、部门、模型、Skill、插件摘要、状态、耗时、记录数、查询摘要、session_id、run_id。

详情字段：

- 基本信息和关联会话/运行。
- 模型、Skill 及其运行时版本快照。
- 调用过的插件/公安工具。
- 执行步骤、起止时间、耗时、记录数和错误码。
- 脱敏后的查询条件与输出摘要。
- trace_id。

审计禁止记录：密码、Cookie、CSRF、API Key、AppSecret、完整身份证号、完整电话号码、未经脱敏的报警内容或其他业务原文、模型内部思维过程。

CSV 导出必须应用与列表相同的筛选条件和权限，使用 UTF-8 BOM，设置行数上限；大数据量建议异步导出并记录导出审计。

建议审计留存时间、归档和销毁策略由公安安全要求确认，后端提供可配置实现。

## 12. 公安业务数据适配层

### 12.1 基本原则

- 前端不得直接调用公安数据源。
- 只有后端插件/工具适配层可以读取数据源凭据。
- 适配层统一处理鉴权、超时、重试、限流、字段映射、脱敏、审计和 trace_id。
- 上游 HTTP 200 但响应结构错误时视为失败，不能返回空数组冒充无数据。
- 默认不自动重试非幂等请求；当前查询类 POST 可在确认上游语义后最多重试 1 次。
- 单数据源默认超时建议 15～30 秒，总研判任务设置独立总超时。

### 12.2 统一工具响应

```json
{
  "data": [],
  "record_count": 0,
  "source": "person_trajectory",
  "queried_at": 1789520000,
  "trace_id": "trace-id",
  "partial": false,
  "next_page": null,
  "error": null
}
```

失败时 `error`：

```json
{
  "code": "upstream_timeout",
  "message": "轨迹数据服务响应超时",
  "retryable": true
}
```

### 12.3 首批正式适配能力

| 内部工具标识 | 依据 | 必要输入 | 主要标准化输出 |
| --- | --- | --- | --- |
| `person_basic_info` | 人员档案基本信息文档 | 身份标识 | 姓名、性别、年龄、基础档案摘要 |
| `family_relationship` | 家庭关系接口 | 身份标识、分页 | 关系类型、关联人员令牌、来源、采集时间 |
| `person_trajectory` | 人员轨迹接口 | 身份标识、起止时间；轨迹类型可选 | 时间、地点/设备、轨迹类型、图像安全引用 |
| `case_person` | 涉案人员接口 | 身份标识、人员类别、分页 | 案件编号、类型、状态、时间、单位、案情脱敏摘要 |
| `police_incident_person` | 涉警人员接口 | 身份标识、起止时间、分页 | 接警编号、涉警类别、时间、地点、单位、内容脱敏摘要 |

严禁把上游身份证号码作为前端对象主键。适配层应生成运行内对象引用或不可逆令牌。身份证、手机号等展示必须按权限和页面用途脱敏。

### 12.4 场所、同行和车辆

当前资料不完整，统一按以下方式处理：

- 开发环境提供与正式结构一致的 Mock Provider，并强制返回 `mock=true`。
- 生产环境未配置正式 Provider 时能力显示不可用，不得自动回退 Mock。
- 同行分析应由多目标轨迹在给定时间/空间阈值内计算，保存算法版本、阈值和来源轨迹引用。
- 场所信息需要明确地点 ID、名称、类型、经纬度权限和敏感级别。
- 车辆信息需要明确号牌、车辆标识、抓拍时间、地点、人员关系及访问权限。

## 13. 数据库和一致性要求

至少需要以下正式实体：

- `users`、`user_profiles`、`departments`。
- `models`、`model_credentials`、`model_test_results`。
- `skills`、`skill_versions`、`skill_drafts`、`capabilities`、`capability_visibility`、`capability_dependencies`。
- `runs`、`run_events`、`run_evidence`、`reports`。
- `invocations`、`invocation_steps`、`login_events`、`admin_audit`。

要求：

- 外键和删除策略明确，不能因删除配置破坏历史审计。
- 历史运行保存模型、Skill 和能力版本快照，而不是只引用当前版本。
- `run_events(run_id, sequence)` 唯一并建立索引。
- 调用审计按 `created_at`、用户、部门、模型、状态建立组合索引。
- 用户警号、部门编码等业务唯一字段建立唯一约束。
- 默认模型唯一性通过事务和数据库约束共同保证。
- 数据库迁移必须可重复执行、有版本号、有回滚或备份方案，不能在应用启动时静默吞掉迁移失败。

## 14. 非功能要求

### 14.1 性能

- 普通管理列表在 10 万级审计数据下，P95 响应不超过 2 秒。
- 登录、当前用户、能力目录等普通接口 P95 不超过 500 毫秒，不包含外部服务时间。
- 所有列表必须后端分页，禁止一次返回全部用户、审计或业务记录。
- 业务查询按数据源配置最大页数和最大记录数，超过阈值返回 `partial=true`，不能无限拉取。

### 14.2 可用性

- Runtime、模型或某个公安数据源失败时，错误必须定位到对应步骤，其他已获得证据仍可标记为部分完成。
- 长任务支持取消、超时和服务重启后的状态恢复或明确失败收敛。
- 接口幂等：消息提交、运行回写、报告生成建议支持 `Idempotency-Key`。
- 禁止多实例部署时依赖仅进程内的运行锁、SSE 缓存或任务状态；如暂不支持集群，需要在部署说明中明确单实例限制。

### 14.3 日志和监控

- 结构化日志包含 request_id、trace_id、run_id、接口、耗时、结果码，不记录敏感正文。
- 监控指标至少包括登录失败率、运行成功率、运行耗时、各数据源成功率/超时率、模型错误率、SSE 连接数和任务积压。
- 对登录暴增、连续数据源失败、审计导出和管理员敏感配置变更设置告警。

## 15. 开发优先级与交付顺序

### P0：前端核心联调必需

1. 消息请求体 `mode`、持久 `run_id` 和真实运行状态回写。
2. 执行轨迹历史和 SSE。
3. 能力目录授权与依赖可用性。
4. Skill 草稿真实生成、测试和保存。
5. 用户/部门分页筛选及部门树完整校验。
6. 模型管理字段、密钥安全和真实连接测试。
7. 调用审计运行完成回写、详情和导出。

### P1：业务闭环

1. 人员基本信息、家庭关系、人员轨迹、涉案、涉警正式适配。
2. 证据标准化、持久化及结论引用。
3. 重新研判真实执行。
4. DOCX/PDF 报告生成。
5. 登录限流、安全日志和监控。

### P2：资料齐备后开发

1. 场所数据正式接口。
2. 同行分析算法和正式数据源。
3. 车辆信息正式接口。
4. 组织系统自动同步和集群化任务恢复。

## 16. 后端交付物

后端团队每个阶段至少交付：

- 可部署代码、数据库迁移和配置模板。
- 更新后的 OpenAPI 3 文档。
- 每个接口的成功、无数据、无权限、参数错误、上游超时示例。
- Mock Provider 和正式 Provider 切换说明。
- 单元测试、集成测试和权限隔离测试。
- 公安接口字段映射表、错误码映射表和数据脱敏清单。
- 部署说明、密钥配置说明、监控指标和回滚方案。
- 更新 `specs/peixian-api-gap-register.md` 中的状态、负责人、联调结果和遗留问题。

## 17. 验收标准

后端完成需同时满足：

1. 普通用户只能访问自己的会话、文件、Skill、运行和证据。
2. 管理员无法通过管理 API 读取用户业务正文或原始证据。
3. 职务与系统权限分字段保存并分别筛选。
4. 执行轨迹可实时更新，刷新后可完整回放，失败、超时和取消状态正确。
5. 每条核心结论可以追溯到证据 ID、数据来源和查询条件。
6. 重新研判生成新 run，不覆盖历史记录。
7. API Key、公安凭据不回显且不进入日志、审计和导出文件。
8. 模型默认切换、启停和连接测试具备事务一致性。
9. 部门存在用户或子部门时无法删除，部门树不能形成环。
10. 个人 Skill 只能归当前用户，不能伪造为部门或公共 Skill。
11. 调用审计可按组合条件查询、查看详情和导出，敏感信息已脱敏。
12. 正式环境中未配置的数据源显示不可用，不允许静默使用 Mock。
13. OpenAPI 与实际路由、字段白名单、状态码一致。
14. 自动化测试覆盖成功、失败、越权、跨用户访问、重放和并发场景。

## 18. 联调前需要项目方确认的问题

| 编号 | 待确认项 | 对实现的影响 |
| --- | --- | --- |
| Q1 | 部门和用户是平台维护还是从公安组织系统同步 | 决定部门/用户写接口及冲突策略 |
| Q2 | 管理员是否都可进入隐藏能力配置，还是仅超级管理员 | 决定 `plugins.manage` 授权范围 |
| Q3 | 正式报告格式优先 DOCX 还是 PDF，是否有固定模板 | 决定报告服务和模板引擎 |
| Q4 | 公安数据访问是否按人员、部门、案件或数据域授权 | 决定工具适配层权限参数和审计字段 |
| Q5 | 证据原始记录允许保存多久、是否允许缓存图片 | 决定证据存储、加密和清理策略 |
| Q6 | 场所、同行、车辆正式接口和字段契约 | 决定 P2 能力是否可以转正式 |
| Q7 | 运行和审计的法定留存期限 | 决定归档、分区和删除任务 |
| Q8 | 是否要求国产数据库、中间件和离线模型部署 | 决定数据访问层、部署和模型接入方式 |
| Q9 | 单次研判允许的最大数据量和最长执行时间 | 决定分页上限、任务超时和资源配额 |

本文确认后，建议后端先冻结 P0 OpenAPI 契约，再由前端基于契约完成正式联调；字段或状态机变更必须同步更新 OpenAPI 和接口对齐记录。
