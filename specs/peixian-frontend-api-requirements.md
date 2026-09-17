# 沛警智枢前端接口需求与对齐清单

## 1. 文档信息

- 代码仓库：`https://github.com/zblds-a/opencode-peixian.git`
- 当前分支：`peixian-ui-final`
- 核对提交：`0de0b0e480fa56b0e9dece9aa092c7988ff485cb`
- 前端目录：`packages/peixian-console/src`
- API 基础路径：`/api/console/v1`
- 文档用途：前端、后端按页面动作逐项冻结接口、字段、权限、Mock 和联调状态。

本文以当前实际挂载的前端代码为准。当前终版路由只有：

1. 账号登录。
2. 民警端“智能研判”。
3. 管理端“模型管理”。
4. 管理端“用户与部门”。
5. 管理端“调用审计”。

`Admin.tsx`、`Files.tsx`、`Plugins.tsx`、`Skills.tsx`、`Settings.tsx`、`Connections.tsx` 等文件仍保留在仓库中，但没有被当前 `App.tsx` 挂载。其接口不属于本轮终版页面必需范围，详见第 14 节。

## 2. 接口状态定义

| 状态 | 含义 |
| --- | --- |
| 现有可用 | 后端路由和当前页面使用方式基本匹配 |
| 现有待扩展 | 已有路由，但字段、筛选、分页或业务闭环不足 |
| 后端新增 | 当前没有满足页面动作的正式接口 |
| 前端待接入 | 后端已有基础接口，但当前按钮或交互尚未绑定 |
| Mock 可展示 | 当前前端使用 Mock 保证样式展示，不能视为正式联调完成 |
| 等待正式数据 | 契约可冻结，但公安数据源或 Runtime 尚未接通 |
| 正式联调完成 | 前后端在正式结构下完成正常、异常和权限测试 |

## 3. 通用协议约定

### 3.1 鉴权与 CSRF

- 浏览器登录成功后由后端设置 HttpOnly Cookie：`px_session`。
- 前端所有请求使用 `credentials: same-origin`。
- 登录响应和 `GET /me` 返回 `csrf_token`。
- 除 `GET/HEAD` 外，前端请求头携带 `X-CSRF-Token: <csrf_token>`。
- 登录失败统一提示“账号或密码不正确”，不得暴露账号是否存在、是否停用。
- 登录后不执行首次强制修改密码。

### 3.2 通用列表

当前前端辅助函数兼容最小响应：

```json
{
  "items": []
}
```

管理列表正式联调建议统一为：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10
}
```

请求参数统一建议：

- `page`：从 1 开始。
- `page_size`：默认 10，最大 100。
- `query`：关键字。
- 排序使用 `sort_by`、`sort_order=asc|desc`。

### 3.3 通用错误

```json
{
  "message": "可直接展示给用户的错误提示",
  "code": "stable_error_code",
  "request_id": "服务端追踪号"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| 400 | 参数或业务规则错误 |
| 401 | 未登录、会话失效 |
| 403 | 已登录但无权限 |
| 404 | 资源不存在或不属于当前用户 |
| 409 | 状态冲突、同名、依赖或部门删除冲突 |
| 413 | 文件或引用内容过大 |
| 422 | 字段校验错误 |
| 429 | 登录或接口限流 |
| 500 | 未预期服务错误，必须返回 `request_id` |

前端会过滤响应中的 URL、IP 和典型密钥文本；后端仍不得把堆栈、SQL、内网地址、凭据或公安原始数据放入错误响应。

### 3.4 时间和 ID

- 当前代码主要使用 Unix 秒级时间戳。
- 新接口统一建议使用 Unix 毫秒或 ISO 8601，但必须在接口冻结时二选一，不能同字段混用。
- 所有资源 ID 均使用字符串，不允许前端推断 ID 结构。

## 4. 接口总表

### 4.1 当前页面直接调用

| 编号 | 方法与路径 | 页面用途 | 当前状态 | 优先级 |
| --- | --- | --- | --- | --- |
| BASE-01 | `GET /platform` | 登录页和全局品牌信息 | 现有可用 | P0 |
| AUTH-01 | `POST /auth/login` | 账号密码登录 | 现有可用 | P0 |
| AUTH-02 | `GET /me` | 当前用户、权限、Runtime 状态 | 现有可用 | P0 |
| AUTH-03 | `POST /auth/logout` | 退出登录 | 现有可用 | P0 |
| EVT-01 | `GET /events` | 全局 SSE 更新通知 | 现有待扩展 | P0 |
| CHAT-01 | `GET /models` | 民警可用模型 | 现有可用 | P0 |
| CHAT-02 | `GET /sessions` | 研判历史列表 | 现有可用，依赖 Runtime | P0 |
| CHAT-03 | `POST /sessions` | 新建研判 | 现有可用，依赖 Runtime | P0 |
| CHAT-04 | `PATCH /sessions/{sid}` | 重命名研判 | 现有可用，依赖 Runtime | P1 |
| CHAT-05 | `DELETE /sessions/{sid}` | 删除研判 | 现有可用，依赖 Runtime | P1 |
| CHAT-06 | `GET /sessions/{sid}/messages` | 对话消息和 Markdown 内容 | 现有可用，依赖 Runtime | P0 |
| CHAT-07 | `POST /sessions/{sid}/messages` | 提交研判 | 现有待扩展 | P0 |
| CHAT-08 | `POST /sessions/{sid}/abort` | 停止生成 | 现有可用，依赖 Runtime | P0 |
| FILE-01 | `GET /files` | 文件选择弹窗 | 现有可用，依赖 Runtime | P0 |
| SKILL-01 | `GET /skills` | 个人 Skill 读取和编辑 | 现有可用 | P0 |
| SKILL-02 | `PATCH /skills/{id}` | 编辑个人 Skill | 现有可用 | P0 |
| SKILL-03 | `POST /skills/{id}/test` | 测试个人 Skill | 现有待扩展 | P1 |
| SKILL-04 | `DELETE /skills/{id}` | 删除个人 Skill | 现有可用 | P1 |
| CAP-01 | `GET /capabilities` | 右侧能力、能力弹窗、`/` 菜单 | 现有待扩展 | P0 |
| DRAFT-01 | `POST /skill-drafts/from-requirement` | 从需求生成 Skill | Mock 可联调 | P0 |
| DRAFT-02 | `POST /skill-drafts/from-session` | 从对话生成 Skill | Mock 可联调 | P0 |
| DRAFT-03 | `PATCH /skill-drafts/{id}` | 编辑 Skill 草稿 | 现有可用 | P0 |
| DRAFT-04 | `POST /skill-drafts/{id}/test` | 测试草稿 | Mock 可联调 | P1 |
| DRAFT-05 | `POST /skill-drafts/{id}/save` | 保存为个人 Skill | 现有可用 | P0 |
| RUN-01 | `GET /sessions/{sid}/runs/{run_id}/events` | 研判执行过程 | 现有待扩展 | P0 |
| RUN-02 | `GET /sessions/{sid}/runs/{run_id}/evidence` | 研判依据/证据链 | Mock 可联调 | P0 |
| RUN-03 | `GET /sessions/{sid}/runs/{run_id}/report` | 导出研判报告 | Mock 可联调 | P1 |
| CONF-01 | `GET /questions` | Runtime 补充问题 | 现有可用，依赖 Runtime | P1 |
| CONF-02 | `POST /questions/{id}/reply` | 提交问题答案 | 现有可用，依赖 Runtime | P1 |
| CONF-03 | `POST /questions/{id}/reject` | 拒绝补充问题 | 现有可用，依赖 Runtime | P1 |
| CONF-04 | `GET /permissions` | Runtime 操作授权请求 | 现有可用，依赖 Runtime | P1 |
| CONF-05 | `POST /permissions/{id}/reply` | 单次允许或拒绝 | 现有可用，依赖 Runtime | P1 |
| MODEL-01 | `GET /admin/models` | 模型列表 | 现有待扩展 | P0 |
| MODEL-02 | `POST /admin/models` | 新增模型 | 现有可用 | P0 |
| MODEL-03 | `PATCH /admin/models/{id}` | 编辑、列表启用/关停、默认切换 | 现有可用，状态按钮已接入 | P0 |
| MODEL-04 | `POST /admin/models/{id}/test` | 已保存模型连接测试 | 现有可用 | P0 |
| USER-01 | `GET /admin/users` | 用户列表 | 现有待扩展 | P0 |
| USER-02 | `POST /admin/users` | 新增用户 | 现有可用 | P0 |
| USER-03 | `PATCH /admin/users/{id}` | 编辑、列表禁用用户 | 现有可用，按钮已接入 | P0 |
| USER-04 | `GET /admin/users/summary` | 用户/部门/启用账号统计 | 现有可用 | P0 |
| DEPT-01 | `GET /admin/departments/tree` | 部门列表 | 现有可用 | P0 |
| DEPT-02 | `POST /admin/departments` | 新增部门 | 现有可用 | P0 |
| DEPT-03 | `PATCH /admin/departments/{id}` | 编辑部门 | 现有可用 | P0 |
| AUDIT-01 | `GET /admin/invocations` | 调用审计列表 | 现有待扩展 | P0 |
| AUDIT-02 | `GET /admin/invocations/export` | 导出调用记录 | 现有待扩展 | P1 |

### 4.2 页面已展示但当前按钮未绑定

| 编号 | 方法与路径 | 页面动作 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| MODEL-05 | `POST /admin/models/test` | 新增模型保存前连接测试 | 后端新增、前端待接入 | 当前弹窗仅用定时器模拟成功 |
| USER-05 | `POST /admin/users/{id}/reset-password` | 重置密码 | 后端已有、按钮已接入 | 正式联调补一次性密码安全弹窗 |
| DEPT-04 | `DELETE /admin/departments/{id}` | 删除空部门 | 后端已有、前端待增加入口 | 非空部门返回 409 |
| AUDIT-03 | `GET /admin/invocations/{id}` | 调用详情 | 后端已有、前端待接入 | “详情”按钮当前无事件 |
| RUN-04 | `GET /sessions/{sid}/runs/{run_id}` | 刷新后恢复运行状态 | 后端已有、前端待接入 | 当前仅保存本次发送得到的 `run_id` |
| RUN-05 | `POST /sessions/{sid}/runs/{run_id}/rerun` | 修改条件重新研判 | 后端已有、前端待接入 | 图 8 后续动作 |
| FILE-02 | `POST /files` | 在文件弹窗上传文件 | 后端已有、前端待接入 | 当前弹窗只能选择已有文件 |
| FILE-03 | `GET /files/{id}/preview` | 文件预览 | 后端已有、前端待接入 | 建议在选择前查看 |

### 4.3 管理员隐藏能力配置

`CapabilityAdmin.tsx` 已有页面组件，但当前没有挂载到路由或头像菜单。若产品确认恢复隐藏入口，需要以下接口：

- `GET /admin/capabilities`
- `POST /admin/capabilities`
- `PATCH /admin/capabilities/{id}`
- `POST /admin/capabilities/{id}/test`

当前后端已有基础实现，但正式接入前必须补齐可见范围校验、指定部门范围、敏感配置只写不读和真实连通测试。

## 5. 平台、登录与当前用户

### 5.1 `GET /platform`

无需登录。

```json
{
  "name": "沛警智枢",
  "short_name": "沛警",
  "description": "沛县公安智能研判平台"
}
```

### 5.2 `POST /auth/login`

```json
{
  "username": "警号或用户名",
  "password": "密码"
}
```

成功响应：

```json
{
  "user": {
    "id": "user-id",
    "username": "320722099",
    "role": "user",
    "system_role": "user",
    "active": true,
    "must_change_password": false,
    "display_name": "张警官",
    "police_no": "320722099",
    "department_id": "department-id",
    "department": {
      "id": "department-id",
      "name": "刑警大队",
      "code": "32032201"
    },
    "position": "民警",
    "last_login_at": 1789550000,
    "runtime": {
      "id": "runtime-id",
      "status": "ready",
      "revision": 3,
      "error": null
    }
  },
  "csrf_token": "csrf-token",
  "capabilities": ["business.use"]
}
```

管理员 `capabilities` 至少按职责返回：`models.manage`、`users.manage`、`audit.read`。普通用户使用 `business.use`。

### 5.3 `GET /me`

返回与登录成功相同的结构。前端每 5 秒刷新一次，用于更新账号状态、权限和 Runtime 状态，后端应保持轻量且不可触发昂贵下游查询。

### 5.4 `POST /auth/logout`

```json
{ "ok": true }
```

必须删除当前会话并清除 Cookie。

## 6. SSE 更新通知

### 6.1 `GET /events`

- `Content-Type: text/event-stream`
- 使用登录 Cookie 鉴权。
- 只有民警端 Runtime 状态允许时前端建立连接。
- 当前前端监听事件名 `change`，收到后刷新 `/me`、会话、消息和资源。

最低兼容事件：

```text
event: change
data: {"type":"connected"}

```

正式建议：

```text
event: change
data: {"type":"run.updated","session_id":"sid","run_id":"rid","updated_at":1789550000}

```

后端要求：

- 心跳不应触发前端全量刷新。
- 用户只能收到本人会话、文件、Skill 和 Runtime 事件。
- Cookie 被注销、账号禁用或密码重置后，连接必须及时终止。

## 7. 智能研判基础接口

### 7.1 `GET /models`

仅返回当前用户获授权且已启用的模型：

```json
{
  "items": [
    {
      "id": "model-id",
      "name": "Qwen3-32B",
      "description": "研判模型",
      "is_default": true
    }
  ]
}
```

至少保证只有一个默认模型；默认模型不可用时后端应返回另一个可用模型，不能返回密钥和 Base URL。

### 7.2 会话接口

`GET /sessions`

```json
{
  "items": [
    {
      "id": "session-id",
      "title": "张某夜间活动研判",
      "status": "idle",
      "time": { "updated": 1789550000 }
    }
  ]
}
```

`status` 至少支持 `idle`、`busy`、`retry`。当前前端使用 `busy/retry` 判断是否显示生成中状态。

`POST /sessions`

```json
{ "title": "输入内容前 35 个字符" }
```

返回单个 Session 对象。

`PATCH /sessions/{sid}`

```json
{ "title": "新标题" }
```

`DELETE /sessions/{sid}` 返回 `{ "ok": true }`。

所有会话接口必须校验当前用户归属；管理员也不能通过普通业务接口读取其他用户会话。

### 7.3 `GET /sessions/{sid}/messages`

```json
{
  "items": [
    {
      "info": {
        "id": "message-id",
        "role": "assistant",
        "time": { "created": 1789550000, "completed": 1789550002 },
        "finish": "stop",
        "error": null
      },
      "parts": [
        { "type": "text", "text": "## 研判结果\nMarkdown 内容" },
        {
          "id": "part-id",
          "type": "tool",
          "tool": "轨迹查询",
          "state": { "status": "completed", "title": "查询轨迹", "error": null },
          "details": {
            "inputs": { "time_range": "近30天" },
            "outputs": { "record_count": 126 }
          }
        }
      ]
    }
  ]
}
```

安全要求：

- Markdown 由前端安全渲染，后端仍不得输出可执行 HTML。
- 工具参数和结果只返回白名单展示字段。
- 身份证、电话、地址等字段按项目脱敏规则处理。
- 不返回模型内部思维过程、插件密钥、内部 URL 或文件路径。

结构化研判结果使用独立消息 Part：`type=analysis_result`，其 `data.schema` 固定为 `peixian.analysis-result`，当前版本为 `1.0`。完整字段、示例和演进规则见 `specs/peixian-structured-analysis-contract.md`，机器可读 Schema 见 `specs/contracts/analysis-result.schema.json`。普通 `type=text` 消息仍按 Markdown 渲染。

### 7.4 `POST /sessions/{sid}/messages`

当前前端实际发送：

```http
X-Analysis-Mode: standard
```

```json
{
  "text": "分析目标人员近期活动",
  "model_id": "model-id",
  "skill_ids": ["skill-id"],
  "file_ids": ["file-id"]
}
```

目标终版契约必须扩展为：

```json
{
  "text": "分析目标人员近期活动",
  "model_id": "model-id",
  "skill_ids": ["personal-or-official-skill-id"],
  "plugin_ids": ["plugin-id"],
  "file_ids": ["file-id"],
  "mode": "standard",
  "client_request_id": "optional-idempotency-id"
}
```

成功响应 HTTP 202：

```json
{
  "accepted": true,
  "run_id": "run-id",
  "message_id": "optional-user-message-id"
}
```

必须解决的当前缺口：

1. 前端右侧和 `/` 菜单可以选择插件，但当前请求没有发送 `plugin_ids`。
2. 当前后端只按个人 Skill 表校验 `skill_ids`，官方 Skill ID 无法执行。
3. 统一能力目录中的依赖关系尚未在执行前完整校验。
4. 消息请求成功后只读取一次运行事件，刷新页面也无法找回最近 `run_id`。
5. 建议把固定 `standard` 模式放入 JSON，逐步废弃专用请求头。

服务端校验：

- 模型、Skill、插件、文件必须处于启用状态并授权给当前用户。
- 用户生成 Skill 只能由所有者使用。
- 单次选择数量、文本长度和文件引用预算由后端最终限制。
- `client_request_id` 重试应幂等，避免网络重试创建重复任务。

### 7.5 `POST /sessions/{sid}/abort`

返回 `{ "ok": true }`。中止后 Run 和 Invocation 必须更新为 `cancelled`，不能只停止上游请求。

## 8. 文件接口

### 8.1 `GET /files`

```json
{
  "items": [
    {
      "id": "file-id",
      "name": "研判资料.pdf",
      "size": 102400,
      "status": "ready",
      "error": null,
      "created": 1789550000
    }
  ]
}
```

`status` 建议统一：`queued`、`parsing`、`ready`、`partial`、`failed`。当前选择弹窗只允许 `ready/partial`，但发送时后端会拒绝截断的 `partial` 文件；建议前端和后端统一为只有 `ready` 可引用。

### 8.2 上传、预览和下载

- `POST /files`：`multipart/form-data`，字段名 `file`。
- `GET /files/{id}/preview`：文本或结构化预览。
- `GET /files/{id}/download`：附件下载。
- `DELETE /files/{id}`：如后续允许在弹窗中删除。

当前智能研判页仅调用列表，未提供上传入口。为了让“文件”功能形成闭环，应在能力/文件弹窗中接入上传、解析状态刷新和预览。

## 9. 能力目录和个人 Skill

### 9.1 `GET /capabilities`

查询参数：

- `query`：名称或描述关键字。
- `kind=skill|plugin`：类型。
- 建议增加 `category`、`owner=personal|official|authorized`。

响应：

```json
{
  "items": [
    {
      "id": "capability-id",
      "kind": "skill",
      "name": "人员夜间活动分析",
      "description": "分析夜间活动规律、高频地点及同行人员",
      "version": "1.3",
      "category": "人员研判",
      "recommended": true,
      "enabled": true,
      "owned": false,
      "scope": "official",
      "dependency_ids": ["plugin-id"],
      "available": true,
      "unavailable_reason": null
    }
  ]
}
```

当前前端最少依赖前九个字段；`dependency_ids/available/unavailable_reason` 是完成执行前校验所必需的扩展字段。

后端聚合规则：

- 个人 Skill：仅当前用户所有且已启用。
- 官方 Skill：按 `visibility` 和部门范围过滤。
- 插件：用户获授权、版本启用、依赖连接完整且 Runtime 可用。
- 依赖停用时返回 `available=false`，不能让前端选择后才失败。
- 不得因列表为空自动返回演示数据；生产前端也应关闭当前空列表 Mock 回退。

### 9.2 `GET /skills`

```json
{
  "items": [
    {
      "id": "skill-id",
      "owner_id": "user-id",
      "name": "人员夜间活动分析",
      "description": "...",
      "content": "# SKILL.md",
      "enabled": true,
      "version": 2,
      "source_type": "conversation",
      "dependency_ids": ["plugin-id"],
      "input_schema": {},
      "default_rules": [],
      "scope": "personal",
      "updated_at": 1789550000
    }
  ]
}
```

### 9.3 个人 Skill 操作

`PATCH /skills/{id}` 请求：

```json
{
  "name": "人员夜间活动分析",
  "description": "...",
  "content": "# SKILL.md",
  "enabled": true,
  "source_type": "manual",
  "dependency_ids": ["plugin-id"],
  "input_schema": {},
  "default_rules": [],
  "scope": "personal"
}
```

- `POST /skills/{id}/test` 返回 `{ "ok": true, "message": "...", "steps": [] }`。
- `DELETE /skills/{id}` 返回 `{ "ok": true }`。

测试接口当前只检查 Runtime 是否已加载 Skill。正式测试应校验依赖、参数 Schema，并提供脱敏的结构化步骤。

## 10. Skill Creator

### 10.1 从需求创建

`POST /skill-drafts/from-requirement`

```json
{
  "requirement": "分析人员近 30 天夜间活动",
  "name": "可选名称",
  "dependency_ids": [],
  "input_schema": {},
  "default_rules": []
}
```

### 10.2 从当前对话创建

`POST /skill-drafts/from-session`

```json
{
  "session_id": "session-id",
  "summary": "当前对话标题或提炼说明",
  "message_ids": ["建议新增：选定消息范围"]
}
```

必须校验会话和消息归属。当前后端只根据 `summary` 生成模板，没有读取并提炼真实会话内容，属于 Mock 联调。

### 10.3 草稿响应

```json
{
  "id": "draft-id",
  "session_id": "session-id",
  "source_type": "conversation",
  "name": "人员夜间活动分析",
  "description": "...",
  "content": "# SKILL.md",
  "dependency_ids": ["plugin-id"],
  "input_schema": {},
  "default_rules": [],
  "created": 1789550000,
  "updated": 1789550000
}
```

### 10.4 草稿维护

- `GET /skill-drafts/{id}`：用于刷新恢复，当前前端尚未调用。
- `PATCH /skill-drafts/{id}`：字段同草稿响应的可编辑字段。
- `POST /skill-drafts/{id}/test`：返回 `ok/message/steps`。
- `POST /skill-drafts/{id}/save`：保存为个人 Skill，返回 Skill ID，并删除或标记草稿已保存。

正式生成要求：

- 不将未经脱敏的原始公安数据写入 `SKILL.md`。
- 只沉淀方法、参数、依赖和规则，不沉淀具体人员信息。
- 生成过程必须有超时、失败和重试状态，不能始终同步返回成功模板。

## 11. 运行、执行轨迹、证据和报告

### 11.1 运行详情

`GET /sessions/{sid}/runs/{run_id}`

```json
{
  "id": "run-id",
  "session_id": "session-id",
  "model_id": "model-id",
  "mode": "standard",
  "status": "running",
  "started": 1789550000,
  "completed": null,
  "duration_ms": null,
  "error": null
}
```

状态统一建议：`accepted`、`running`、`completed`、`failed`、`cancelled`、`timeout`。

### 11.2 执行轨迹

`GET /sessions/{sid}/runs/{run_id}/events`

```json
{
  "items": [
    {
      "id": "event-id",
      "sequence": 1,
      "step_type": "requirement",
      "name": "需求理解",
      "status": "completed",
      "started": 1789550000,
      "completed": 1789550001,
      "input_summary": "识别目标和时间范围",
      "output_summary": "已识别研判条件",
      "record_count": 0,
      "error": null,
      "evidence_refs": []
    }
  ]
}
```

`step_type`：`requirement`、`skill`、`plugin`、`analysis`、`result`。

当前后端只在请求开始时写入固定初始步骤，尚未由 Runtime 实时回写；这是 P0 后端缺口。前端也需在 SSE 或轮询时重新读取事件，而不是只在发送成功后读取一次。

### 11.3 证据链

`GET /sessions/{sid}/runs/{run_id}/evidence`

```json
{
  "conclusion": {
    "confidence": "high",
    "summary": "结构化研判结论"
  },
  "tabs": {
    "trajectory": [],
    "places": [],
    "companions": []
  },
  "chain": [
    { "type": "object", "label": "目标对象" },
    { "type": "analysis", "label": "行为规律与关联分析" },
    { "type": "risk", "label": "风险判断" },
    { "type": "result", "label": "研判建议" }
  ],
  "conditions": {
    "time_range": "近30天",
    "dimensions": ["trajectory", "places", "companions"]
  },
  "mock": false,
  "trace_id": "trace-id"
}
```

正式记录需包含证据 ID、来源系统、查询时间、脱敏字段和与运行事件的引用关系。当前后端返回 `mock=true` 的空内容，状态为“等待正式数据”。

### 11.4 重新研判和报告

`POST /sessions/{sid}/runs/{run_id}/rerun`

```json
{
  "query": "可选新问题",
  "conditions": {
    "time_range": { "start": "2026-08-01", "end": "2026-08-31" },
    "dimensions": ["trajectory", "companions"]
  }
}
```

返回 `{ "accepted": true, "run_id": "new-run-id" }`。

`GET /sessions/{sid}/runs/{run_id}/report` 应以附件响应，文件名和格式由产品方确认。当前为 Markdown 占位；若最终要求 Word/PDF，需同步更新 `Content-Type` 和文件名。

## 12. Runtime 补充问题和权限确认

### 12.1 待读取

`GET /questions`、`GET /permissions`

```json
{
  "items": [
    {
      "id": "request-id",
      "sessionID": "session-id",
      "description": "需要确认本次操作",
      "questions": [
        {
          "header": "时间范围",
          "question": "请选择研判时间范围",
          "multiple": false,
          "custom": true,
          "options": [
            { "label": "近7天", "description": "查询最近7天" }
          ]
        }
      ]
    }
  ]
}
```

前端每 4 秒读取一次，并按 `sessionID` 过滤。后端最好支持 `?session_id=`，减少传输和越权风险。

### 12.2 回复

- `POST /questions/{id}/reply`：`{ "answers": [["近7天"]] }`
- `POST /questions/{id}/reject`：`{}`
- `POST /permissions/{id}/reply`：`{ "reply": "once" }` 或 `{ "reply": "reject" }`

只允许回复当前用户、当前会话的待确认项，重复回复返回 409。

## 13. 管理端接口

### 13.1 模型管理

`GET /admin/models`

正式查询参数：`page`、`page_size`、`query`、`provider`、`status`、`sort_by`、`sort_order`。当前后端没有分页和筛选，当前前端下拉框也只是静态样式。

模型对象：

```json
{
  "id": "model-id",
  "name": "Qwen3-32B-Instruct",
  "description": "通义千问指令模型",
  "provider": "阿里云",
  "model_id": "qwen3-32b-instruct",
  "base_url": "https://example.internal/v1",
  "api_key_configured": true,
  "context_length": 131072,
  "access_mode": "api",
  "supports_tools": true,
  "enabled": true,
  "is_default": true,
  "test_status": "success",
  "updated_at": 1789550000
}
```

`POST /admin/models`、`PATCH /admin/models/{id}` 请求：

```json
{
  "name": "Qwen3-32B-Instruct",
  "description": "...",
  "provider": "阿里云",
  "model_id": "qwen3-32b-instruct",
  "base_url": "https://example.internal/v1",
  "api_key": "只写字段",
  "context_length": 131072,
  "access_mode": "api",
  "supports_tools": true,
  "enabled": true,
  "is_default": true
}
```

API Key 只写不读；编辑时不提交或传空表示保留旧值。

模型列表的状态列固定为两个操作按钮：

- “启用”：`PATCH /admin/models/{id}`，请求 `{ "enabled": true }`。
- “关停”：`PATCH /admin/models/{id}`，请求 `{ "enabled": false }`。
- 当前状态对应按钮为选中且不可重复点击；操作列仅保留“编辑、测试”，不再提供省略号菜单。

`POST /admin/models/{id}/test` 返回：

```json
{ "ok": true, "message": "连接成功，模型 ID 已确认" }
```

新增弹窗需要保存前测试，建议新增：

`POST /admin/models/test`

请求使用与新增模型相同字段，但不落库；响应同上。当前“连接测试”只是前端 650ms 模拟成功，必须替换。

`access_mode=local` 目前只有 UI 字段，后端仍按 HTTP Base URL 测试。若无本地模型执行器，应禁用该选项或明确返回 `unsupported_access_mode`。

### 13.2 用户列表与统计

`GET /admin/users`

查询参数：`page`、`page_size`、`query`、`department_id`、`position`、`system_role`、`status=enabled|disabled`。

响应用户对象沿用第 5.2 节，并增加：

```json
{
  "model_ids": ["model-id"],
  "plugin_ids": ["plugin-id"]
}
```

当前后端能按部分字段筛选但无分页；当前前端只做本地关键字过滤，部门、角色、状态下拉框尚未绑定。

`GET /admin/users/summary`

```json
{
  "users": 128,
  "departments": 18,
  "enabled": 116
}
```

原型中的环比百分比当前是固定 Mock。若需要真实环比，响应增加：

```json
{
  "users_change_percent": 12,
  "departments_change_percent": 6,
  "enabled_change_percent": 8
}
```

否则前端应去掉固定百分比，避免展示伪统计。

### 13.3 新增和编辑用户

`POST /admin/users`

```json
{
  "username": "320722099",
  "password": "可选；为空时后端生成",
  "role": "user",
  "display_name": "张警官",
  "police_no": "320722099",
  "department_id": "department-id",
  "position": "民警",
  "model_ids": ["model-id"],
  "plugin_ids": ["plugin-id"]
}
```

响应：

```json
{
  "user": {},
  "job": { "id": "job-id", "status": "queued" },
  "password": "仅本次返回的自动生成密码"
}
```

前端必须以一次性弹窗展示自动生成密码，禁止写日志或长期保存在状态中。当前终版 `FinalAdmin.tsx` 尚未处理返回的一次性密码，需要补齐。

`PATCH /admin/users/{id}` 可修改：

```json
{
  "display_name": "张警官",
  "police_no": "320722099",
  "department_id": "department-id-or-null",
  "position": "中队长",
  "model_ids": ["model-id"],
  "plugin_ids": ["plugin-id"],
  "active": true
}
```

角色不允许通过该接口修改。系统权限与警务职务必须分字段保存。

`POST /admin/users/{id}/reset-password`

```json
{ "password": "可选指定密码" }
```

响应中的密码只允许展示一次。当前按钮已绑定接口路径，但正式联调仍需增加一次性密码安全展示弹窗。

当前管理端用户列表操作列仅保留“编辑、重置密码、禁用”：禁用提交 `PATCH /admin/users/{id}` 与 `{ "active": false }`；已禁用账号的禁用按钮不可重复点击，重新启用通过编辑弹窗完成。重置密码按钮已调用正式路径，正式联调仍需补充自动生成密码的一次性安全展示。

### 13.4 部门

`GET /admin/departments/tree`

当前前端实际期待扁平数组，以 `parent_id` 自行显示上级部门：

```json
{
  "items": [
    {
      "id": "department-id",
      "name": "刑警大队",
      "parent_id": null,
      "code": "32032201",
      "sort_order": 1
    }
  ]
}
```

虽然路径名为 `tree`，后端不要直接改成嵌套结构，除非同时升级前端契约。

`POST /admin/departments`、`PATCH /admin/departments/{id}`：

```json
{
  "name": "刑警大队",
  "code": "32032201",
  "parent_id": null,
  "sort_order": 0
}
```

`DELETE /admin/departments/{id}`：存在用户或下级部门时返回 409，不得级联删除。当前前端未提供删除入口。

### 13.5 调用审计

`GET /admin/invocations`

正式查询参数：

- `page`、`page_size`
- `query`
- `start`、`end`
- `uid`、`department_id`
- `model_id`、`skill_id`
- `status`

建议列表项：

```json
{
  "id": "invocation-id",
  "run_id": "run-id",
  "session_id": "session-id",
  "created": 1789550000,
  "username": "320722099",
  "display_name": "张警官",
  "department_name": "刑警大队",
  "model_id": "model-id",
  "model_name": "Qwen3-32B",
  "skill_ids": ["skill-id"],
  "skills": [{ "id": "skill-id", "name": "人员夜间活动分析" }],
  "plugin_ids": ["plugin-id"],
  "plugins": [{ "id": "plugin-id", "name": "轨迹查询" }],
  "status": "completed",
  "duration_ms": 28600,
  "record_count": 126,
  "query_summary": "已脱敏的问题摘要"
}
```

当前调用审计列表固定列为：时间、用户、部门、模型、问题、会话 ID、结果状态、操作。`query_summary` 和 `session_id` 是列表必需字段；Skill、插件不再占用列表列位，但仍需在详情响应保留，以便追溯完整调用链。

Skill/插件不再显示在审计列表首屏，但详情仍需要可读名称。建议继续返回 `skills/plugins` 展示对象，避免详情直接展示裸 ID。

`GET /admin/invocations/{id}` 返回列表字段并增加 `steps`：

```json
{
  "steps": [
    {
      "sequence": 1,
      "step_type": "requirement",
      "name": "需求理解",
      "status": "completed",
      "started": 1789550000,
      "completed": 1789550001,
      "input_summary": "...",
      "output_summary": "...",
      "record_count": 0,
      "error": null
    }
  ]
}
```

`GET /admin/invocations/export` 必须接受与列表完全相同的筛选条件并导出当前筛选结果，建议 CSV UTF-8 BOM。当前前端导出链接没有携带筛选参数，需要同步修改。

审计禁止记录密码、Cookie、CSRF、API Key、身份证完整号码、完整电话号码、未经脱敏的业务原文、上游原始响应和模型内部思维过程。

## 14. 当前未路由页面及其接口

以下页面文件仍在源码中，但终版 `App.tsx` 没有 import 或路由入口。除非产品明确恢复，不应把它们列入本轮后端交付：

| 未路由页面 | 遗留调用 |
| --- | --- |
| `Files.tsx` | `/files`、`/results`、预览、下载、删除 |
| `Skills.tsx` | `/skills`、`/templates`、复制、回滚 |
| `Plugins.tsx` | `/plugins` 安装、配置、启停、测试、回滚 |
| `Settings.tsx` | `/me/password`、`/tokens` |
| `Admin.tsx` | 旧管理中心、插件发布、模板、任务、操作审计 |
| `Connections.tsx` | `/admin/connections` 和插件连接绑定 |
| `CapabilityAdmin.tsx` | 隐藏能力配置，组件存在但尚无入口 |

其中底层接口可继续保留供系统内部或未来使用，但不应恢复“插件中心、Skill 中心、插件管理、Skill 审核、我的智能体”等已取消主导航和页面。

## 15. 当前前端 Mock 清单

| 位置 | Mock 内容 | 触发条件 | 正式处理建议 |
| --- | --- | --- | --- |
| 智能研判 | 1 个模型 | `/models` 返回空或不可用 | 生产构建关闭 Mock，展示未配置状态 |
| 智能研判 | 6 条研判历史 | `/sessions` 返回空或不可用 | 空列表应展示真实空状态 |
| 智能研判 | 8 个 Skill/插件 | `/capabilities` 返回空或不可用 | 生产构建关闭 Mock |
| 模型管理 | 6 个模型 | 列表为空 | 生产显示空状态 |
| 用户与部门 | 部门、用户、汇总数 | 数据为空或用户数不大于 1 | 生产显示真实数据 |
| 调用审计 | 10 条调用记录 | 列表为空 | 生产显示空状态 |
| 模型弹窗 | 保存前连接测试成功 | 点击“连接测试” | 接入 `POST /admin/models/test` |

建议增加显式环境变量，例如 `VITE_ENABLE_DEMO_DATA=true|false`：

- 开发/视觉验收可开启。
- 联调环境默认关闭。
- 生产构建强制关闭。

不得以“正式接口返回空数组”为依据自动启用 Mock，否则真实空数据会被误显示为演示数据。

## 16. P0 对齐事项

后端联调前建议优先冻结以下事项：

1. 扩展消息提交，支持 `plugin_ids` 和官方 Skill，并完成授权/依赖校验。
2. Runtime 实时回写 Run、Step、Invocation，提供刷新后可恢复的最新运行关系。
3. 关闭联调/生产环境空列表 Mock，使用真实空状态。
4. 能力目录严格按用户、部门、启用状态和依赖可用性过滤。
5. Skill 从会话生成读取真实选定消息，但不沉淀具体敏感数据。
6. 模型保存前连接测试使用真实后端接口，取消前端定时器假成功。
7. 用户一次性重置密码展示、调用详情和筛选控件完成前端绑定。
8. 调用审计列表返回问题摘要和会话 ID，详情返回 Skill/插件显示名称，并增加分页和完整筛选。
9. 公安数据工具统一契约、脱敏、超时、限流、`trace_id` 和审计。
10. OpenAPI 与实际路由、请求字段、响应字段和错误码保持一致。

## 17. 公安业务工具统一响应

前端不直接请求公安数据源。所有人员、关系、轨迹、场所、同行、车辆等请求由后端插件/工具适配层处理，并归一化为：

```json
{
  "data": [],
  "record_count": 0,
  "source": "service-id",
  "queried_at": 1789550000,
  "trace_id": "trace-id",
  "mock": false,
  "error": null
}
```

要求：

- 统一鉴权、超时、重试、限流和熔断。
- 统一字段字典和脱敏规则。
- 每次调用关联 `session_id/run_id/invocation_id`。
- 原始业务响应不得直接进入浏览器或通用日志。
- 开发 Mock 必须返回 `mock=true`；生产未配置数据源时明确返回不可用。

## 18. 联调验收清单

### 18.1 登录和权限

- 普通用户只能进入智能研判。
- 管理员只显示模型管理、用户与部门、调用审计。
- 禁用账号无法登录，普通用户请求 `/admin/*` 返回 403。
- 登录、退出、Cookie 失效和 CSRF 校验符合预期。

### 18.2 智能研判

- 模型、会话、文件、能力均来自正式接口，不显示 Mock。
- `/` 和能力弹窗选择的 Skill/插件会真实进入消息请求。
- 新建、恢复、改名、删除、发送、中止均正常。
- Markdown 和工具摘要安全渲染。
- 运行轨迹实时更新，刷新后可恢复，失败和取消有明确状态。
- 证据、报告、运行和审计使用同一 `run_id`。

### 18.3 Skill Creator

- 两种来源均可创建草稿。
- 草稿编辑、测试、保存、个人 Skill 再编辑和删除正常。
- 同名、依赖停用、越权草稿和非本人会话被拒绝。

### 18.4 管理端

- 模型分页、筛选、新增、编辑、测试、列表启用/关停、默认切换正确。
- API Key 不回显，保存前测试不落库。
- 用户分页筛选、组织属性、编辑、禁用、重置密码和一次性密码展示正确。
- 非空部门删除返回 409。
- 调用审计八列展示、组合筛选、详情和导出一致，敏感信息不泄漏。

## 19. 前后端每日对齐记录建议

每个接口至少记录：

- 接口编号和 OpenAPI operationId。
- 前端负责人、后端负责人。
- 当前状态。
- 请求示例和脱敏响应示例。
- 鉴权 capability。
- 分页、排序、超时和限流。
- Mock 地址、联调地址和正式地址。
- 首次联调日期、最后验证日期。
- 正常、异常、越权测试结果。
- 遗留问题和计划完成时间。

状态请同步更新到 `specs/peixian-api-gap-register.md`，正式契约更新后同步更新 `services/peixian-control/docs/openapi.json`。
