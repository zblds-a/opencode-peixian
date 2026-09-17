# 沛警智枢前后端快速对齐交接文档

> 本文是后端开发、接口评审和前后端联调的单文件交接基线。接收方无需再阅读其他需求文档即可理解代码位置、页面范围、接口需求、结构化研判消息格式、优先级和验收标准。

## 1. 交接基线

| 项目 | 内容 |
| --- | --- |
| 最新代码仓库 | `https://github.com/zblds-a/opencode-peixian.git` |
| 交接分支 | `peixian-ui-final` |
| 本轮 UI 基线提交 | `4c43143b1` |
| 前端目录 | `packages/peixian-console/src` |
| 后端控制服务 | `services/peixian-control` |
| API 基础路径 | `/api/console/v1` |
| 结构化消息版本 | `peixian.analysis-result@1.0` |
| 联调目标 | 以正式接口替换前端 Mock，保持当前页面结构和交互不变 |

本文中的“必须”表示 V1 联调阻断项，“建议”表示允许在不破坏现有契约的前提下协商调整。若接口与本文不一致，应先更新 OpenAPI 和本文，再调整前端，避免前后端各自猜测。

## 2. 获取最新代码

### 2.1 首次克隆

```bash
git clone --branch peixian-ui-final --single-branch https://github.com/zblds-a/opencode-peixian.git
cd opencode-peixian
git status
git log -1 --oneline
```

### 2.2 已有仓库，尚未配置该远端

```bash
git remote add zblds https://github.com/zblds-a/opencode-peixian.git
git fetch zblds --prune
git switch -c peixian-ui-final --track zblds/peixian-ui-final
```

如果本地已经存在同名分支：

```bash
git fetch zblds --prune
git switch peixian-ui-final
git pull --ff-only zblds peixian-ui-final
```

如果远端名 `zblds` 已存在但地址不正确：

```bash
git remote set-url zblds https://github.com/zblds-a/opencode-peixian.git
git fetch zblds --prune
git switch peixian-ui-final
git pull --ff-only zblds peixian-ui-final
```

### 2.3 核验

```bash
git branch --show-current
git rev-parse --short HEAD
git status --short
```

应处于 `peixian-ui-final` 分支。`git status --short` 在未修改代码时应无输出。交接期间以后端实际拉取到的该分支最新提交为准；`4c43143b1` 是本文编制时已核验的 UI 基线，不是限制后续文档提交的固定 HEAD。

## 3. 当前产品范围

### 3.1 正式页面

1. 账号登录。
2. 民警端“智能研判”：历史研判、模型选择、能力选择、文件引用、普通问答、结构化研判结果、智能发现线索。
3. 弹窗/抽屉：能力选择、Skill 创建方式、从需求或会话生成 Skill、Skill 编辑测试、线索详情、研判依据。
4. 管理端“模型管理”。
5. 管理端“用户与部门”。
6. 管理端“调用审计”。
7. 隐藏的管理员“能力配置”仅在产品确认恢复入口后接入，不进入左侧主导航。

### 3.2 明确取消

- 我的智能体。
- Skill 中心、插件中心、插件管理、Skill 审核等独立页面及导航。
- 短信登录和其他登录方式。
- 联网搜索、深度研判按钮。
- 白天/黑夜主题切换。
- 用户端右侧“推荐 Skill”和“相关插件”分区；当前统一为“相关插件技能”。
- 管理端页面内部的二级跳转入口；只能从左侧“模型管理、用户与部门、调用审计”切换。

源码中仍保留的旧页面文件不等于本轮需求，后端不应因这些遗留文件恢复已取消模块。

## 4. 后端交付优先级

### P0：首轮正式联调必须完成

1. 登录、当前用户、退出和 CSRF。
2. 可用模型、会话、消息发送/读取、中止。
3. 消息同时支持普通 Markdown Part 和 `analysis_result` 结构化 Part。
4. 统一能力目录，支持官方 Skill、个人 Skill、插件工具，并完成用户/部门/依赖授权过滤。
5. 消息提交支持 `skill_ids`、`plugin_ids`、`file_ids`，返回可追踪的 `run_id`。
6. Run 状态与可审计步骤实时落库，可在刷新后恢复。
7. 文件上传、解析状态、选择和预览。
8. 模型管理、用户与部门、调用审计列表的正式数据和权限控制。
9. 所有公安数据通过服务端适配层访问、脱敏并审计，前端不得直连。

### P1：核心页面稳定后完成

- Skill 草稿生成、测试、保存为个人 Skill。
- 研判报告导出、修改条件重新研判。
- 用户重置密码、部门删除冲突、调用审计详情和导出。
- 管理员隐藏能力配置。

## 5. 全局协议约定

### 5.1 鉴权和 CSRF

- 登录成功由服务端设置 HttpOnly、SameSite Cookie，建议名称 `px_session`。
- 浏览器请求使用 `credentials: same-origin`。
- 登录响应及 `GET /me` 返回 `csrf_token`。
- 除 `GET/HEAD` 外，请求头携带 `X-CSRF-Token: <csrf_token>`。
- 登录失败统一返回“账号或密码不正确”，不暴露账号是否存在或已停用。
- 禁用账号不可登录；账号被禁用、会话注销或密码重置后，已有 Cookie/SSE 应失效。
- 普通用户请求 `/admin/*` 必须返回 403，不能只依赖前端隐藏入口。
- 登录后不再执行强制修改密码流程，`must_change_password` 固定为 `false` 或逐步废弃。

### 5.2 权限模型

- `system_role`：系统权限，至少 `user`、`admin`、`super_admin`。
- `position`：警务职务，仅用于展示和筛选，如民警、中队长、科员、副大队长。
- 两者必须分字段保存，不得用警务职务推断系统权限。
- 建议 capability：普通用户 `business.use`；管理员按职责返回 `models.manage`、`users.manage`、`audit.read`。

### 5.3 列表、时间和 ID

列表统一响应：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10
}
```

- `page` 从 1 开始；`page_size` 默认 10、最大 100。
- 关键字统一为 `query`；排序统一为 `sort_by`、`sort_order=asc|desc`。
- 所有资源 ID 均为字符串，前端不推断格式。
- 新接口时间建议统一 ISO 8601；现有 Unix 秒字段可兼容保留，但同一字段不得混用秒、毫秒和字符串。

### 5.4 通用错误

```json
{
  "message": "可直接展示给用户的错误提示",
  "code": "stable_error_code",
  "request_id": "服务端追踪号",
  "field_errors": {
    "optional_field": "字段错误说明"
  }
}
```

| 状态码 | 含义 |
| --- | --- |
| 400 | 参数格式或业务规则错误 |
| 401 | 未登录、会话失效 |
| 403 | 已登录但无权限 |
| 404 | 资源不存在或不属于当前用户 |
| 409 | 同名、状态、依赖或部门删除冲突 |
| 413 | 文件、消息或引用内容过大 |
| 422 | 字段校验失败 |
| 429 | 登录或业务接口限流 |
| 500 | 未预期错误，必须提供 `request_id` |

错误响应和日志中不得包含堆栈、SQL、内网地址、密码、Cookie、CSRF、API Key、公安原始数据或模型隐藏思维过程。

### 5.5 幂等、超时和脱敏

- 消息发送支持 `client_request_id`，网络重试不得创建重复 Run。
- 新增/测试类接口应设置明确超时并返回稳定错误码。
- 身份证、手机号、详细地址、车主信息等由后端完成脱敏，不能依赖前端遮盖。
- 所有业务调用关联 `session_id`、`run_id`、`invocation_id` 和 `trace_id`。

## 6. 接口总表

所有路径均相对于 `/api/console/v1`。

| 编号 | 方法与路径 | 用途 | 后端状态/要求 | 优先级 |
| --- | --- | --- | --- | --- |
| BASE-01 | `GET /platform` | 品牌信息 | 现有可复用 | P0 |
| AUTH-01 | `POST /auth/login` | 账号登录 | 现有可复用，补登录审计 | P0 |
| AUTH-02 | `GET /me` | 当前用户、权限、Runtime | 现有待扩展字段 | P0 |
| AUTH-03 | `POST /auth/logout` | 退出 | 现有可复用 | P0 |
| EVT-01 | `GET /events` | 全局变化/SSE | 现有待扩展 | P0 |
| CHAT-01 | `GET /models` | 用户可用模型 | 现有可复用 | P0 |
| CHAT-02 | `GET /sessions` | 研判历史 | 现有可复用 | P0 |
| CHAT-03 | `POST /sessions` | 新建研判 | 现有可复用 | P0 |
| CHAT-04 | `PATCH /sessions/{sid}` | 重命名 | 现有可复用 | P1 |
| CHAT-05 | `DELETE /sessions/{sid}` | 删除 | 现有可复用 | P1 |
| CHAT-06 | `GET /sessions/{sid}/messages` | 消息和结构化结果 | 必须扩展 `analysis_result` | P0 |
| CHAT-07 | `POST /sessions/{sid}/messages` | 提交问答/研判 | 必须扩展能力选择与 `run_id` | P0 |
| CHAT-08 | `POST /sessions/{sid}/abort` | 中止 | 现有可复用，需同步 Run/审计 | P0 |
| FILE-01 | `GET /files` | 文件列表 | 现有可复用 | P0 |
| FILE-02 | `POST /files` | 上传 | 前端待接入 | P0 |
| FILE-03 | `GET /files/{id}/preview` | 预览 | 前端待接入 | P1 |
| FILE-04 | `GET /files/{id}/download` | 下载 | 现有可复用 | P1 |
| FILE-05 | `DELETE /files/{id}` | 删除 | 现有可复用 | P1 |
| CAP-01 | `GET /capabilities` | 统一 Skill/插件目录 | 现有待扩展 | P0 |
| SKILL-01 | `GET /skills` | 个人 Skill | 现有待扩展字段 | P0 |
| SKILL-02 | `POST /skills` | 新建个人 Skill | 现有可复用 | P1 |
| SKILL-03 | `PATCH /skills/{id}` | 编辑/启停 | 现有可复用 | P0 |
| SKILL-04 | `POST /skills/{id}/test` | 测试 | 需返回真实测试步骤 | P1 |
| SKILL-05 | `DELETE /skills/{id}` | 删除 | 现有可复用 | P1 |
| DRAFT-01 | `POST /skill-drafts/from-requirement` | 从需求生成 | 需正式实现 | P1 |
| DRAFT-02 | `POST /skill-drafts/from-session` | 从会话生成 | 需读取真实消息 | P1 |
| DRAFT-03 | `GET /skill-drafts/{id}` | 草稿恢复 | 现有可复用 | P1 |
| DRAFT-04 | `PATCH /skill-drafts/{id}` | 编辑草稿 | 现有可复用 | P1 |
| DRAFT-05 | `POST /skill-drafts/{id}/test` | 草稿测试 | 需正式实现 | P1 |
| DRAFT-06 | `POST /skill-drafts/{id}/save` | 保存个人 Skill | 现有可复用 | P1 |
| RUN-01 | `GET /sessions/{sid}/runs/{run_id}` | Run 状态恢复 | 前端待接入 | P0 |
| RUN-02 | `GET /sessions/{sid}/runs/{run_id}/events` | 可审计执行步骤 | Runtime 必须真实回写 | P0 |
| RUN-03 | `GET /sessions/{sid}/runs/{run_id}/evidence` | 证据链详情 | 等待正式数据 | P0 |
| RUN-04 | `POST /sessions/{sid}/runs/{run_id}/rerun` | 修改条件重跑 | 前端待接入 | P1 |
| RUN-05 | `GET /sessions/{sid}/runs/{run_id}/report` | 报告导出 | 需确定文件格式 | P1 |
| CONF-01 | `GET /questions` | Runtime 补充问题 | 现有可复用 | P1 |
| CONF-02 | `POST /questions/{id}/reply` | 回答问题 | 现有可复用 | P1 |
| CONF-03 | `POST /questions/{id}/reject` | 拒绝问题 | 现有可复用 | P1 |
| CONF-04 | `GET /permissions` | Runtime 授权确认 | 现有可复用 | P1 |
| CONF-05 | `POST /permissions/{id}/reply` | 授权/拒绝 | 现有可复用 | P1 |
| MODEL-01 | `GET /admin/models` | 模型列表 | 补分页筛选字段 | P0 |
| MODEL-02 | `POST /admin/models` | 新增模型 | 现有可复用 | P0 |
| MODEL-03 | `PATCH /admin/models/{id}` | 编辑、列表启用/关停、默认 | 现有可复用；状态按钮已接入 | P0 |
| MODEL-04 | `POST /admin/models/{id}/test` | 已保存模型测试 | 现有可复用 | P0 |
| MODEL-05 | `POST /admin/models/test` | 保存前测试 | 后端新增 | P0 |
| USER-01 | `GET /admin/users` | 用户列表 | 补分页、组织属性 | P0 |
| USER-02 | `POST /admin/users` | 新增用户 | 现有可复用 | P0 |
| USER-03 | `PATCH /admin/users/{id}` | 编辑、列表禁用 | 现有可复用；禁用按钮已接入 | P0 |
| USER-04 | `POST /admin/users/{id}/reset-password` | 重置密码 | 现有可复用；按钮已接入 | P1 |
| USER-05 | `GET /admin/users/summary` | 汇总 | 现有可复用 | P0 |
| DEPT-01 | `GET /admin/departments/tree` | 部门列表 | 现有可复用 | P0 |
| DEPT-02 | `POST /admin/departments` | 新增部门 | 现有可复用 | P0 |
| DEPT-03 | `PATCH /admin/departments/{id}` | 编辑部门 | 现有可复用 | P0 |
| DEPT-04 | `DELETE /admin/departments/{id}` | 删除空部门 | 现有可复用，非空返回 409 | P1 |
| AUDIT-01 | `GET /admin/invocations` | 调用审计列表 | 后端需补完整业务审计 | P0 |
| AUDIT-02 | `GET /admin/invocations/{id}` | 审计详情 | 前端待接入 | P1 |
| AUDIT-03 | `GET /admin/invocations/export` | 筛选结果导出 | 需与列表筛选一致 | P1 |

## 7. 认证、平台和事件接口

### 7.1 `GET /platform`

无需登录：

```json
{
  "name": "沛警智枢",
  "short_name": "沛警",
  "description": "沛县公安智能研判平台"
}
```

### 7.2 `POST /auth/login`

请求：

```json
{
  "username": "320722099",
  "password": "用户密码"
}
```

成功：

```json
{
  "user": {
    "id": "usr_01",
    "username": "320722099",
    "role": "user",
    "system_role": "user",
    "active": true,
    "must_change_password": false,
    "display_name": "张警官",
    "police_no": "320722099",
    "department_id": "dept_01",
    "department": { "id": "dept_01", "name": "刑警大队", "code": "32032201" },
    "position": "民警",
    "last_login_at": "2026-09-17T15:30:00+08:00",
    "runtime": { "id": "rt_01", "status": "ready", "revision": 3, "error": null }
  },
  "csrf_token": "csrf-token",
  "capabilities": ["business.use"]
}
```

成功和失败登录均写安全日志，但日志不得保存密码。失败限流按账号和来源综合控制，返回信息不得用于枚举账号。

### 7.3 `GET /me` 与 `POST /auth/logout`

`GET /me` 返回与登录成功一致的 `user/csrf_token/capabilities`。前端可能每 5 秒刷新，应保持轻量，不触发公安数据源等昂贵查询。

退出响应：

```json
{ "ok": true }
```

### 7.4 `GET /events`

- `Content-Type: text/event-stream`，使用登录 Cookie 鉴权。
- 前端当前监听 `change` 事件，用于刷新用户、会话、消息和资源。
- 心跳不能使用 `change`，避免触发全量刷新。
- 用户只能收到本人资源事件。

```text
event: change
data: {"type":"run.updated","session_id":"ses_01","run_id":"run_01","updated_at":"2026-09-17T15:34:18+08:00"}

```

## 8. 智能研判基础接口

### 8.1 `GET /models`

仅返回当前用户获授权且启用的模型；不返回 Base URL 和密钥：

```json
{
  "items": [
    { "id": "mdl_01", "name": "Qwen3-32B", "description": "研判模型", "is_default": true }
  ]
}
```

### 8.2 会话

`GET /sessions`：

```json
{
  "items": [
    {
      "id": "ses_01",
      "title": "张某夜间活动研判",
      "status": "idle",
      "latest_run_id": "run_01",
      "time": { "created": 1789550000, "updated": 1789550100 }
    }
  ]
}
```

`status`：`idle|busy|retry`。增加 `latest_run_id` 可帮助刷新后恢复结构化 Run。

其他请求：

```text
POST /sessions
{ "title": "张某夜间活动研判" }

PATCH /sessions/{sid}
{ "title": "修改后的标题" }
```

`DELETE /sessions/{sid}` 返回 `{ "ok": true }`。所有会话接口必须校验当前用户归属，管理员也不能通过普通业务接口读取其他用户会话。

### 8.3 `POST /sessions/{sid}/messages`

目标请求：

```json
{
  "text": "分析张某最近30天夜间活动及同行人员",
  "model_id": "mdl_01",
  "skill_ids": ["skill_official_01", "skill_personal_01"],
  "plugin_ids": ["plugin_track_01"],
  "file_ids": ["file_01"],
  "mode": "standard",
  "client_request_id": "ce3f65e5-3078-4f76-a12d-f2d35c509ed8"
}
```

HTTP 202：

```json
{
  "accepted": true,
  "run_id": "run_01",
  "message_id": "msg_user_01"
}
```

服务端必须：

1. 校验模型、Skill、插件、文件均已启用且授权给当前用户。
2. 支持官方 Skill 和个人 Skill；个人 Skill 仅所有者可用。
3. 校验 Skill 所依赖插件/连接是否可用，不可用时在执行前返回 409。
4. 对 `client_request_id + session_id + user_id` 做幂等。
5. 创建 Run 和 Invocation，再异步执行。
6. 单次选择数量、文本长度、文件预算由后端限制并在 422 中给出字段错误。

### 8.4 `GET /sessions/{sid}/messages`

普通回复继续使用 `text` Part，前端按安全 Markdown 渲染：

```json
{
  "items": [
    {
      "info": {
        "id": "msg_01",
        "role": "assistant",
        "time": { "created": 1789550000, "completed": 1789550002 },
        "finish": "stop",
        "error": null
      },
      "parts": [
        { "id": "part_text_01", "type": "text", "text": "## 研判说明\n普通 Markdown 内容" }
      ]
    }
  ]
}
```

需要特殊渲染时返回第 9 节定义的 `analysis_result` Part。一个消息允许同时含文本说明、工具摘要和结构化结果，但同一含义不要重复返回两份。

### 8.5 中止

`POST /sessions/{sid}/abort` 返回 `{ "ok": true }`。中止后对应 Run、未完成步骤和 Invocation 必须同步更新为 `cancelled`。

## 9. 结构化研判消息契约 V1.0

### 9.1 目标和判别

两类助手回复：

- 普通回复：`type=text`，按 Markdown 渲染，右侧智能线索栏不出现。
- 结构化研判回复：`type=analysis_result`，渲染研判过程、0—N 个目标对象、核心结论、最多四张研判依据、普通文本下一步建议和右侧 0—N 条智能线索。

必须同时满足：

1. `part.type === "analysis_result"`。
2. `part.data.schema === "peixian.analysis-result"`。
3. `part.data.version === "1.0"`。

后端不得把该 JSON 放入 Markdown 代码块。版本未知时前端只显示“不支持的结构化消息”，不会猜测字段。

### 9.2 消息封装

```json
{
  "info": {
    "id": "msg_analysis_01",
    "role": "assistant",
    "time": { "created": 1770000000, "completed": 1770000030 },
    "finish": "stop",
    "error": null
  },
  "parts": [
    {
      "id": "part_analysis_01",
      "type": "analysis_result",
      "data": {
        "schema": "peixian.analysis-result",
        "version": "1.0",
        "run_id": "run_01",
        "generated_at": "2026-09-17T15:34:18+08:00",
        "intro": "已根据您的需求完成分析。",
        "process": [],
        "subjects": [],
        "conclusions": [],
        "evidence": [],
        "next_steps": "建议结合原始资料进一步核验。",
        "clues": []
      }
    }
  ]
}
```

### 9.3 完整数据示例

```json
{
  "schema": "peixian.analysis-result",
  "version": "1.0",
  "run_id": "run_night_001",
  "generated_at": "2026-09-17T15:34:18+08:00",
  "intro": "已根据您的需求完成分析，以下是张某最近30天的夜间活动情况及关联人员研判结果。",
  "process": [
    { "id": "step_1", "title": "获取目标对象信息", "detail": "调取目标对象基础信息和重点人员库数据", "time": "15:32:10", "status": "completed" },
    { "id": "step_2", "title": "查询近期轨迹", "detail": "检索最近30天授权范围内的轨迹记录", "time": "15:32:28", "status": "completed" },
    { "id": "step_3", "title": "分析同行人员", "detail": "基于时空碰撞分析同行人员及关联关系", "time": "15:33:05", "status": "completed" },
    { "id": "step_4", "title": "关联车辆信息", "detail": "检索关联车辆及共同出行记录", "time": "15:33:42", "status": "completed" },
    { "id": "step_5", "title": "生成研判结果", "detail": "整合多源数据形成结构化结论", "time": "15:34:18", "status": "completed" }
  ],
  "subjects": [
    {
      "id": "person_masked_01",
      "name": "张某",
      "fields": [
        { "label": "性别", "value": "男" },
        { "label": "年龄", "value": "36岁" },
        { "label": "身份证", "value": "320322********1234" },
        { "label": "户籍地", "value": "江苏省沛县汉城街道***" },
        { "label": "现居住地", "value": "沛县经济开发区***小区" }
      ],
      "tags": ["夜间活跃", "重点关注人员", "多名同行人员", "关联车辆"]
    }
  ],
  "conclusions": [
    "最近30天夜间活动频繁，共出现42次，主要集中在22:00—02:00时段。",
    "与王某、李某等3人关联密切，共同出现12次。",
    "活动地点主要集中在沛县经济开发区及周边区域。",
    "关联车辆苏C12345多次与目标对象存在夜间同行记录。"
  ],
  "evidence": [
    { "type": "trajectory", "title": "轨迹记录", "value": 42, "unit": "条", "summary": "最近30天夜间", "items": ["活动覆盖经济开发区、工业园等区域"] },
    { "type": "companion", "title": "同行人员", "value": 6, "unit": "人", "summary": "其中重点关注3人", "items": ["与王某共同出现12次"] },
    { "type": "vehicle", "title": "关联车辆", "value": 2, "unit": "辆", "summary": "苏C12345等", "items": ["存在11次轨迹高度重合"] },
    { "type": "place", "title": "高频地点", "value": 5, "unit": "个", "summary": "主要在工业园周边", "items": ["夜间出现频次较高"] }
  ],
  "next_steps": "建议进一步核验王某、李某的身份背景及共同活动目的，并结合原始资料复核苏C12345的完整活动轨迹。",
  "clues": [
    {
      "id": "clue_person_01",
      "type": "person",
      "title": "关联人员线索",
      "headline": "王某与张某共同出现12次",
      "summary": "王某（320322********5678）与张某在最近30天内多次在夜间共同出现，行为轨迹高度重合。",
      "time": "15:33",
      "level": "高",
      "source": "人员夜间活动分析",
      "discoveries": [
        "近30天共同出现12次，时空重合度较高。",
        "主要出现在沛县经济开发区、某工业园、汉城路周边。",
        "多在22:00—02:00时段共同活动。"
      ],
      "evidence": [
        { "type": "trajectory", "label": "2026-08-15 22:18", "content": "两人在某工业园西门附近同时出现，停留约1小时20分钟。" },
        { "type": "trajectory", "label": "2026-08-21 23:06", "content": "两人同时出现在某娱乐场所，停留约2小时。" }
      ]
    }
  ]
}
```

### 9.4 字段约束

| 字段 | 必填 | 约束与前端行为 |
| --- | --- | --- |
| `schema` | 是 | 固定 `peixian.analysis-result` |
| `version` | 是 | 当前固定 `1.0` |
| `run_id` | 强烈建议 | 关联 Run、证据、报告和审计 |
| `generated_at` | 否 | ISO 8601 |
| `intro` | 否 | 最长 1000 字符 |
| `process` | 是 | 数组；状态 `pending/running/completed/failed` |
| `subjects` | 是 | 0—N；不返回人物照片；字段使用 `label/value` |
| `conclusions` | 是 | 文本数组 |
| `evidence` | 是 | 可返回多项，前端只展示前 4 项 |
| `next_steps` | 否 | 最长 3000 字符，按普通文本展示，不作为按钮/链接 |
| `clues` | 是 | 0—N；为空时不显示右侧智能线索栏 |

依据类型优先支持 `trajectory|companion|vehicle|place`；线索类型优先支持 `person|vehicle|place|trajectory`。未知类型允许出现，前端使用通用卡片，不得导致整条消息失败。

### 9.5 演进和安全规则

- 对象允许增加字段，前端忽略未知字段。
- 允许增加新的 `type`，前端使用兜底样式。
- 不得改变现有字段类型；破坏性变更升级为 `2.0`。
- 无数据数组返回 `[]`，不要返回 `null`；可选文本缺失时省略，不返回字符串 `"null"`。
- `process` 只能包含可审计任务步骤、工具调用摘要和状态，不得返回模型隐藏思维链、系统提示词或内部推理原文。
- 单条摘要应精炼；大量原始记录通过受控证据详情接口查询，不塞入消息。
- 所有内容后端先脱敏再返回。

仓库内机器可读 Schema 位于 `specs/contracts/analysis-result.schema.json`；后端建议在序列化响应前用该 Schema 做契约测试。

## 10. Run、执行轨迹、证据和报告

### 10.1 `GET /sessions/{sid}/runs/{run_id}`

```json
{
  "id": "run_01",
  "session_id": "ses_01",
  "message_id": "msg_analysis_01",
  "model_id": "mdl_01",
  "mode": "standard",
  "status": "running",
  "started_at": "2026-09-17T15:32:10+08:00",
  "completed_at": null,
  "duration_ms": null,
  "error": null
}
```

状态固定：`accepted|running|completed|failed|cancelled|timeout`。

### 10.2 `GET /sessions/{sid}/runs/{run_id}/events`

```json
{
  "items": [
    {
      "id": "evt_01",
      "sequence": 1,
      "step_type": "requirement",
      "name": "需求理解",
      "status": "completed",
      "started_at": "2026-09-17T15:32:10+08:00",
      "completed_at": "2026-09-17T15:32:11+08:00",
      "elapsed_ms": 1000,
      "input_summary": "识别目标和时间范围",
      "output_summary": "已识别近30天夜间活动研判条件",
      "record_count": 0,
      "capability_id": null,
      "evidence_refs": [],
      "error_message": null
    }
  ]
}
```

`step_type`：`requirement|skill|plugin|analysis|result`。步骤必须由 Runtime 实际执行状态回写，不能在请求开始时一次性生成固定成功步骤。历史接口用于刷新回放，SSE 用于增量提醒；SSE 事件不是模型思维链。

### 10.3 `GET /sessions/{sid}/runs/{run_id}/evidence`

```json
{
  "conclusion": { "confidence": "high", "summary": "结构化研判结论" },
  "tabs": {
    "trajectory": [],
    "places": [],
    "companions": [],
    "vehicles": []
  },
  "chain": [
    { "type": "object", "label": "目标对象" },
    { "type": "analysis", "label": "行为规律与关联分析" },
    { "type": "risk", "label": "风险判断" },
    { "type": "result", "label": "研判建议" }
  ],
  "conditions": {
    "time_range": { "start": "2026-08-18", "end": "2026-09-17" },
    "dimensions": ["trajectory", "places", "companions", "vehicles"]
  },
  "mock": false,
  "trace_id": "trace_01"
}
```

每条证据建议包含 `id/source/queried_at/summary/masked_data/event_refs`，能追溯到执行步骤但不暴露原始敏感响应。

### 10.4 重跑和报告

```text
POST /sessions/{sid}/runs/{run_id}/rerun
{
  "query": "可选的新问题",
  "conditions": {
    "time_range": { "start": "2026-08-01", "end": "2026-08-31" },
    "dimensions": ["trajectory", "companions"]
  }
}
```

返回 `{ "accepted": true, "run_id": "run_new_01" }`。

`GET /sessions/{sid}/runs/{run_id}/report` 以附件响应。若使用 PDF：`Content-Type: application/pdf`；若使用 Word：`application/vnd.openxmlformats-officedocument.wordprocessingml.document`。文件名应安全编码，报告内容与该 `run_id` 的脱敏结果一致。

## 11. 文件、能力和个人 Skill

### 11.1 文件

`GET /files`：

```json
{
  "items": [
    {
      "id": "file_01",
      "name": "研判资料.pdf",
      "size": 102400,
      "mime_type": "application/pdf",
      "status": "ready",
      "error": null,
      "created_at": "2026-09-17T15:00:00+08:00"
    }
  ]
}
```

状态：`queued|parsing|ready|partial|failed`；只有 `ready` 可提交给研判。`POST /files` 使用 `multipart/form-data`，字段名 `file`。预览和下载必须校验文件归属、内容类型和下载文件名。

### 11.2 `GET /capabilities`

查询：`query`、`kind=skill|plugin`、`category`、`owner=personal|official|authorized`。

```json
{
  "items": [
    {
      "id": "skill_official_01",
      "kind": "skill",
      "name": "人员夜间活动分析",
      "description": "分析夜间活动规律、高频地点及同行人员",
      "version": "1.3",
      "category": "人员研判",
      "recommended": true,
      "enabled": true,
      "owned": false,
      "scope": "official",
      "dependency_ids": ["plugin_track_01"],
      "available": true,
      "unavailable_reason": null
    }
  ]
}
```

聚合和过滤规则：

- 个人 Skill：仅当前用户所有且启用。
- 官方 Skill：按可见范围和部门授权过滤。
- 插件工具：获授权、版本启用、依赖连接完整且 Runtime 可用。
- 依赖不可用时返回 `available=false` 和可展示原因，不能等执行后才失败。
- 列表为空就返回真实空数组，禁止服务端自动塞入演示数据。

### 11.3 个人 Skill

对象：

```json
{
  "id": "skill_personal_01",
  "owner_id": "usr_01",
  "name": "人员夜间活动分析",
  "description": "个人沉淀的分析方法",
  "content": "# SKILL.md",
  "enabled": true,
  "version": 2,
  "source_type": "conversation",
  "dependency_ids": ["plugin_track_01"],
  "input_schema": {},
  "default_rules": [],
  "scope": "personal",
  "updated_at": "2026-09-17T15:00:00+08:00"
}
```

`scope` 对用户创建内容固定为 `personal`，不得通过请求改为公共或部门发布。测试响应：

```json
{
  "ok": true,
  "message": "测试完成",
  "steps": [
    { "name": "依赖校验", "status": "completed", "summary": "所需插件可用" }
  ]
}
```

## 12. Skill Creator

### 12.1 从需求生成

```text
POST /skill-drafts/from-requirement
{
  "requirement": "分析人员近30天夜间活动",
  "name": "可选名称",
  "dependency_ids": [],
  "input_schema": {},
  "default_rules": []
}
```

### 12.2 从会话生成

```text
POST /skill-drafts/from-session
{
  "session_id": "ses_01",
  "summary": "当前会话提炼说明",
  "message_ids": ["msg_01", "msg_02"]
}
```

必须读取并校验真实消息归属。生成内容只能沉淀方法、参数、依赖和规则，不能把具体人员、身份证、轨迹等敏感事实写入 `SKILL.md`。

### 12.3 草稿对象和生命周期

```json
{
  "id": "draft_01",
  "session_id": "ses_01",
  "source_type": "conversation",
  "status": "ready",
  "name": "人员夜间活动分析",
  "description": "...",
  "content": "# SKILL.md",
  "dependency_ids": ["plugin_track_01"],
  "input_schema": {},
  "default_rules": [],
  "error": null,
  "created_at": "2026-09-17T15:00:00+08:00",
  "updated_at": "2026-09-17T15:00:10+08:00"
}
```

状态建议：`generating|ready|failed|saved`。生成应支持超时和失败，不应始终同步返回模板成功。保存后返回个人 Skill ID，并将草稿标记为 `saved`。

## 13. Runtime 补充问题和授权

`GET /questions?session_id={sid}`、`GET /permissions?session_id={sid}`：

```json
{
  "items": [
    {
      "id": "req_01",
      "sessionID": "ses_01",
      "description": "需要确认本次操作",
      "questions": [
        {
          "header": "时间范围",
          "question": "请选择研判时间范围",
          "multiple": false,
          "custom": true,
          "options": [{ "label": "近7天", "description": "查询最近7天" }]
        }
      ]
    }
  ]
}
```

- `POST /questions/{id}/reply`：`{ "answers": [["近7天"]] }`
- `POST /questions/{id}/reject`：`{}`
- `POST /permissions/{id}/reply`：`{ "reply": "once" }` 或 `{ "reply": "reject" }`

只允许回复当前用户、当前会话的待确认项；重复回复返回 409。

## 14. 管理端接口

### 14.1 模型管理

`GET /admin/models` 查询：`page/page_size/query/provider/status/sort_by/sort_order`。

```json
{
  "id": "mdl_01",
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
  "updated_at": "2026-09-17T15:00:00+08:00"
}
```

新增/编辑请求可包含 `api_key`，但响应永不返回明文。编辑时省略或空值表示保留旧密钥。

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

- `POST /admin/models/test`：保存前测试，不落库。
- `POST /admin/models/{id}/test`：已保存模型测试。
- 测试响应：`{ "ok": true, "message": "连接成功，模型 ID 已确认", "elapsed_ms": 320 }`。
- 模型列表状态列固定展示“启用”和“关停”两个按钮：启用调用 `PATCH /admin/models/{id}` 并提交 `{ "enabled": true }`，关停提交 `{ "enabled": false }`。当前状态对应按钮置为选中且不可重复点击。
- 模型列表操作列只展示“编辑、测试”，不再提供省略号或其他隐式菜单。
- 同一时刻只能有一个默认且启用的模型。
- 若后端没有本地模型执行能力，`access_mode=local` 返回 `unsupported_access_mode`，不能假成功。

### 14.2 用户和统计

`GET /admin/users` 查询：`page/page_size/query/department_id/position/system_role/status`。

用户对象在第 7.2 节基础上增加：

```json
{
  "model_ids": ["mdl_01"],
  "plugin_ids": ["plugin_track_01"]
}
```

`GET /admin/users/summary`：

```json
{
  "users": 128,
  "departments": 18,
  "enabled": 116,
  "users_change_percent": 12,
  "departments_change_percent": 6,
  "enabled_change_percent": 8
}
```

环比字段如果无法真实计算则省略，前端不应展示伪造百分比。

新增用户：

```text
POST /admin/users
{
  "username": "320722099",
  "password": "可选；为空由后端生成",
  "system_role": "user",
  "display_name": "张警官",
  "police_no": "320722099",
  "department_id": "dept_01",
  "position": "民警",
  "model_ids": ["mdl_01"],
  "plugin_ids": ["plugin_track_01"]
}
```

响应中的自动生成密码只返回一次：

```json
{
  "user": { "id": "usr_01", "username": "320722099" },
  "job": { "id": "job_01", "status": "queued" },
  "password": "仅本次响应返回"
}
```

`PATCH /admin/users/{id}` 可修改展示姓名、警号、部门、职务、模型、插件和 `active`。系统角色若需修改应设计独立高权限操作，避免普通管理员提权。

`POST /admin/users/{id}/reset-password` 请求 `{ "password": "可选指定密码" }`，生成密码同样只返回一次，不写日志。

用户列表操作列只展示“编辑、重置密码、禁用”，不再提供省略号菜单。禁用调用 `PATCH /admin/users/{id}` 并提交 `{ "active": false }`；账号已禁用时“禁用”按钮不可重复点击。重新启用暂通过“编辑用户”弹窗完成，不在列表操作列增加第四个按钮。重置密码操作已经绑定正式路径；若后端返回自动生成密码，后续正式联调需以一次性安全弹窗展示，不能写入 Toast、控制台或持久状态。

### 14.3 部门

当前前端虽使用 `/tree` 路径，实际期待扁平数组：

```json
{
  "items": [
    { "id": "dept_01", "name": "刑警大队", "parent_id": null, "code": "32032201", "sort_order": 1 }
  ]
}
```

新增/编辑：

```json
{
  "name": "刑警大队",
  "code": "32032201",
  "parent_id": null,
  "sort_order": 0
}
```

删除存在用户或下级部门的部门时返回 HTTP 409 和明确 `code`，不得级联删除。

### 14.4 调用审计

`GET /admin/invocations` 查询：`page/page_size/query/start/end/uid/department_id/model_id/skill_id/status`。

管理端列表固定展示八列：`时间、用户、部门、模型、问题、会话 ID、结果状态、操作`。因此列表响应中的 `created_at`（兼容现有 `created`）、`display_name/username`、`department_name`、`model_name`、`query_summary`、`session_id` 和 `status` 均为首屏必需字段；Skill 和插件不再占用列表列位，保留在详情接口中用于调用链追溯。

```json
{
  "id": "inv_01",
  "run_id": "run_01",
  "session_id": "ses_01",
  "created_at": "2026-09-17T15:32:10+08:00",
  "username": "320722099",
  "display_name": "张警官",
  "department_name": "刑警大队",
  "model_id": "mdl_01",
  "model_name": "Qwen3-32B",
  "skill_ids": ["skill_official_01"],
  "skills": [{ "id": "skill_official_01", "name": "人员夜间活动分析" }],
  "plugin_ids": ["plugin_track_01"],
  "plugins": [{ "id": "plugin_track_01", "name": "轨迹查询" }],
  "status": "completed",
  "duration_ms": 28600,
  "record_count": 126,
  "query_summary": "已脱敏的问题摘要"
}
```

`query_summary` 应是短且已脱敏的用户问题摘要，不能返回完整敏感原文；`session_id` 必须是可用于详情关联的真实会话 ID。问题过长时前端单行省略，完整摘要在详情中展示。

详情增加 `steps`，字段与第 10.2 节一致。导出接口接受与列表完全相同的筛选条件，建议输出 UTF-8 BOM CSV。

审计中严禁记录：密码、Cookie、CSRF、API Key、完整身份证/手机号、未经脱敏的业务原文、上游完整原始响应、模型内部思维链。

## 15. 管理员隐藏能力配置（非主导航）

仅管理员头像菜单未来确认入口后启用：

- `GET /admin/capabilities`
- `POST /admin/capabilities`
- `PATCH /admin/capabilities/{id}`
- `POST /admin/capabilities/{id}/test`

对象至少包含：`id/kind/name/description/version/enabled/visibility/department_ids/dependency_ids/configured/test_status/updated_at`。敏感配置只写不读；官方 Skill 和插件统一展示，但底层可复用既有插件、连接实现。不恢复插件市场、安装中心、版本回滚或 Skill 审核页面。

## 16. 公安业务数据适配层

前端不得直接访问人员、关系、轨迹、场所、同行、车辆等公安数据接口。所有访问由后端工具/插件适配层完成，统一鉴权、超时、限流、熔断、脱敏和审计。

统一响应：

```json
{
  "data": [],
  "record_count": 0,
  "source": "service-id",
  "queried_at": "2026-09-17T15:33:00+08:00",
  "trace_id": "trace_01",
  "mock": false,
  "error": null
}
```

要求：

- 人员基本信息、家庭关系、轨迹、涉案/涉警人员优先接正式适配。
- 场所、同行、车辆资料不完整时可先使用同契约 Mock，但必须返回 `mock=true`。
- 生产未配置数据源时明确返回不可用，禁止静默返回伪数据。
- 原始接口凭证不得写入前端、仓库、响应或日志；已暴露凭证应更换并迁移到凭证存储。
- 每次调用关联 `session_id/run_id/invocation_id/trace_id`。

## 17. 前端 Mock 现状和切换规则

当前为视觉验收准备了模型、历史会话、能力、用户、部门、审计及结构化研判示例数据。它们不是接口已完成的证明。

正式联调建议环境变量：

```text
VITE_ENABLE_DEMO_DATA=false
```

规则：

- 开发/纯视觉验收可开启。
- 联调环境默认关闭。
- 生产构建强制关闭。
- 正式接口返回空数组时展示真实空状态，绝不能据此自动启用 Mock。
- 模型“连接测试”必须替换前端定时器假成功。

## 18. 安全和数据治理最低要求

1. 所有资源接口执行服务端对象级授权，不能只检查“已登录”。
2. 普通业务接口不允许管理员绕过用户会话归属读取业务数据。
3. API Key 只写不读；响应仅返回 `api_key_configured`。
4. 登录、模型配置、用户变更、能力配置和业务调用分别审计。
5. Markdown 不返回可执行 HTML；结构化文本也按不可信内容处理。
6. 证据、线索、报告、审计中的敏感数据使用同一脱敏规则。
7. 下载接口校验权限、文件名和 Content-Type，防止路径穿越和内容嗅探。
8. 服务错误提供 `request_id`，但不向浏览器返回内部拓扑和堆栈。

## 19. 联调顺序

1. 冻结 `/auth/login`、`/me`、权限和错误结构。
2. 关闭 Mock，联调 `/models`、会话和普通 Markdown 消息。
3. 联调 `/capabilities`、文件上传及消息中的 Skill/插件/文件引用。
4. 用本文完整示例联调 `analysis_result@1.0`，先静态返回，再接 Runtime。
5. 接 Run 状态、步骤增量、刷新恢复、失败/取消。
6. 接真实公安数据适配和证据详情。
7. 联调模型管理、用户部门、调用审计。
8. 最后联调 Skill Creator、报告、重跑和隐藏能力配置。

## 20. 联调验收清单

### 登录和权限

- [ ] 正确、错误、禁用账号、退出和会话失效符合预期。
- [ ] 登录后不强制改密。
- [ ] 普通用户只能进入智能研判；管理员只显示三个管理入口。
- [ ] 普通用户直接请求 `/admin/*` 返回 403。
- [ ] CSRF、Cookie 和 SSE 注销行为正确。

### 智能研判

- [ ] 模型、会话、文件、能力来自正式接口，无演示数据。
- [ ] `/` 菜单和能力弹窗选择的 Skill/插件真实进入消息请求。
- [ ] 新建、恢复、改名、删除、发送、中止均正常。
- [ ] 普通 `text` Part 安全渲染 Markdown。
- [ ] `analysis_result@1.0` 可渲染 0/1/多个目标对象、0/多条线索。
- [ ] 依据超过 4 项时前端只展示前 4 项，完整内容仍可从详情读取。
- [ ] 普通回复不出现右侧线索栏；结构化回复有线索时出现并可滚动、查看详情。
- [ ] Run 实时更新，刷新后可恢复，失败、超时和取消状态明确。
- [ ] 结构化消息、证据、报告和审计使用同一 `run_id`。

### Skill Creator

- [ ] 从需求和从会话均可生成草稿。
- [ ] 草稿编辑、测试、保存、再次编辑和删除正常。
- [ ] 非本人会话、同名、依赖停用和越权访问被拒绝。
- [ ] `SKILL.md` 不含具体敏感业务事实。

### 管理端

- [ ] 模型分页、筛选、新增、编辑、测试、默认切换正确；列表“启用/关停”按钮状态和接口结果一致。
- [ ] API Key 不回显，保存前测试不落库。
- [ ] 用户分页筛选、组织属性、编辑、禁用、重置密码和一次性密码正确；列表只保留三个指定操作。
- [ ] 职务与系统权限分离。
- [ ] 非空部门删除返回 409。
- [ ] 调用审计按“时间、用户、部门、模型、问题、会话 ID、结果状态、操作”八列展示；列表、详情和导出筛选一致。
- [ ] 审计和错误响应不泄漏敏感数据。

## 21. 后端交付物

后端完成一批接口时，应同时交付：

1. 与真实实现一致的 OpenAPI，包括鉴权、请求、响应和错误码。
2. 数据库迁移及可回滚说明。
3. 脱敏规则、权限矩阵和审计字段说明。
4. 本地/联调环境配置说明，不包含真实凭证。
5. 正常、空数据、失败、超时、取消、越权测试结果。
6. 结构化消息 JSON Schema 契约测试。
7. 尚使用 Mock 的数据源清单及计划替换日期。

## 22. 接口状态登记模板

每个接口按以下字段登记，状态统一使用“现有可用、现有待扩展、后端新增、等待正式契约、Mock 可联调、正式联调完成”：

| 接口编号 | 方法与路径 | 状态 | 后端负责人 | 前端负责人 | OpenAPI | Mock | 首次联调 | 最后验证 | 遗留问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 示例 | `GET /models` | 现有待扩展 | 待填 | 待填 | 待更新 | 有 | 待填 | 待填 | 关闭空列表 Mock |

接口实现、OpenAPI 和本文有差异时，以双方评审后更新的契约为准；未经确认不得直接改变字段类型、状态枚举、权限语义或结构化消息主版本。
