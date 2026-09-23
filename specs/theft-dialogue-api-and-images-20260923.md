# 盗窃助手对话版：运行镜像与前后端接口联调说明

> 核对时间：2026-09-23（北京时间）
>
> 适用站点：`https://36.134.45.38:19460/`
>
> API 前缀：`/api/console/v1`
>
> 接口依据：该站点当时提供的 `/openapi.json`、运行容器与镜像标签；本文只说明已核对的部署版本，不把接口契约测试等同于真实资料联调。

## 1. 运行版本与镜像 ID

| 交付对象 | 当前运行镜像 ID | 作用 |
| --- | --- | --- |
| 后端 Control | `sha256:d948d79011280a79bf5b66b7ccb03f127ba6b3513d9b53d40f129c80d139f7ce` | FastAPI、会话、Run、规划及接口 |
| 前端页面 | `sha256:d948d79011280a79bf5b66b7ccb03f127ba6b3513d9b53d40f129c80d139f7ce` | SolidJS 构建产物由同一个 Control 镜像内的 `/candidate/static` 提供；**本版没有独立前端容器镜像** |
| HTTPS 入口代理（仅供部署核对） | `sha256:c318e336065b17ff460aeac6d14bce5d0b13e35f25d5cb1843b635359fc00c9a` | TLS 与反向代理；不是前端应用镜像 |

运行容器分别为 `peixian-alignment-20260917-console` 与 `peixian-alignment-20260917-https`。Control 镜像标签中的源码提交为 `cbb50b9695ced592fa18bb812a20d30a4370e664`；页面入口脚本为 `/assets/index-BVMqwYsk.js`。文档所在工作树在核对时为分支 `codex/theft-dialogue-simplification`、提交 `861b6da806afd2da34c4f2f59ad266a274e52193`。这两个提交号不同，是因为后一个提交只追加交付文档；运行镜像仍对应前一个源码提交。

部署或联调前应重新读取容器 `.Image` 和 `/openapi.json`；若镜像更换，以新运行版本重新核对本文。当前数据库 schema 为 v11。完整机器可读契约保存在同目录的 `theft-dialogue-openapi.json`，线上地址为 `https://36.134.45.38:19460/openapi.json`。本次逐字段比对确认线上与交付 JSON 的内容等价；其规范化 JSON SHA-256 为 `66671d95108d339882cd4680b8726d762f2c5df468d8f9f0396c612fcaf8`。

## 2. 登录、权限和请求约定

浏览器统一使用同源 HTTPS。`POST /auth/login` 传 `username`、`password`，成功后服务端设置 HttpOnly `px_session` Cookie，并在响应中返回 `user`、`csrf_token`、`capabilities`。后续 Cookie 写操作须带 `X-CSRF-Token: <登录或 GET /me 返回的值>`；GET 无须该头。跨源请求还受 Origin 校验。Python 等非浏览器客户端可使用平台签发的个人 Bearer Token：`Authorization: Bearer <token>`；Bearer 写操作不使用 Cookie CSRF。不要在 URL、文档、日志或前端持久存储中保存密码、Cookie、Token 或 CSRF 值。

普通用户只能读取本人会话、Run、证据与报告；跨账号资源按接口契约返回 404。管理员身份不会自动获得普通用户资料正文。当前盗窃对话版本的前端发送 `agent_id: "theft-assistant"`，同一会话不能中途换助手；若需要换助手，应创建新会话。新客户端应显式发送 `client_request_id`（UUID），服务端对同账号、同会话、同请求标识执行受理去重。它不同于管理写接口的 `Idempotency-Key`。

### 最小登录与身份查询

```http
POST /api/console/v1/auth/login
Content-Type: application/json

{"username":"<账号>","password":"<密码>"}
```

```json
{
  "user": {"id":"<账号ID>","username":"<账号>","role":"user","active":true,"must_change_password":false,"runtime":null},
  "csrf_token":"<仅本次浏览器会话使用>",
  "capabilities":["business.use"]
}
```

示例仅示意关键字段：`user.runtime` 实际可能为对象，`user` 还可含显示名、部门、授权模型等字段。登录后用 `GET /api/console/v1/me` 恢复身份和 CSRF 值；初次登录要求改密时按接口提示完成改密。退出使用 `POST /api/console/v1/auth/logout`。

## 3. 用户对话的接口调用顺序

```text
登录 /me
  → GET /models（取得可用 model_id）
  → POST /sessions（建立会话）
  → GET /sessions/{sid}/task-context（可选：恢复会话上下文版本）
  → POST /sessions/{sid}/messages（HTTP 202，取得 run_id）
  → GET /events（接收失效通知）+ GET /runs/{rid}、/events、/messages（补查）
  → 如需补充信息：读取 Run.clarification → 另发一条消息，或 reject
  → GET /runs/{rid}/result、/evidence（读取可信结果）
  → GET /runs/{rid}/report?format=md|html（导出）
```

SSE 只通知资源发生变化，不承载可靠的完整正文。刷新、断线重连和重新登录后以 GET 查询持久 Run、步骤和消息。不要因为 SSE 重连或消息提交超时自动重发模型写请求。

## 4. 主要接口速查

表中路径均相对于 `/api/console/v1`。除登录外均需本人认证；POST/DELETE 在 Cookie 模式下还需 `X-CSRF-Token`。

| 方法与路径 | 用途 | 主要返回 |
| --- | --- | --- |
| `GET /models` | 当前账号已授权模型 | `{ "items": Model[] }`，`Model` 含 `id/name/description/is_default` |
| `GET /capabilities` | 当前账号能力目录；盗窃助手不要求用户先挑插件 | `{items,total,page,page_size}` |
| `GET /sessions` | 会话列表 | `{items: Session[]}` |
| `POST /sessions` | 创建空会话；可传 `title` | HTTP 200，`Session`，至少含 `id` |
| `GET /sessions/{sid}/messages` | 当前会话消息和服务端投影 | `{items: Message[]}`；单条含 `info`、`parts` |
| `POST /sessions/{sid}/messages` | 受理一轮用户请求或回答补充问题 | HTTP 202，`{accepted,run_id,message_id}` |
| `GET /sessions/{sid}/task-context` | 恢复该会话的 Agent、上下文版本和待补充问题 | `TaskContext` |
| `DELETE /sessions/{sid}/task-context` | 清除后续续接上下文；并不删除历史 Run | `TaskContext` |
| `GET /sessions/{sid}/runs?page=1&page_size=20` | 恢复会话 Run 列表 | `{items,total,page,page_size}` |
| `GET /sessions/{sid}/runs/{rid}` | 查询执行状态、资料结果概况、待补充字段 | `Run` |
| `GET /sessions/{sid}/runs/{rid}/events?after=0&page=1&page_size=100` | 按序号补查持久步骤 | `{items,total,page,page_size}` |
| `GET /sessions/{sid}/runs/{rid}/task` | 查询冻结的任务规划摘要和澄清结果 | `{run_id,task_spec,response,...}` |
| `GET /sessions/{sid}/runs/{rid}/data-usage` | 区分取数、未取数、复用、未知等状态 | `{run_id,result_version,data_usage}`；`data_usage` 可为 `DataUsageV1` 或 `null` |
| `GET /sessions/{sid}/runs/{rid}/result` | 读取该 Run 的不可变可信结果 | Result V2、pending 或 legacy 之一 |
| `GET /sessions/{sid}/runs/{rid}/evidence` | 读取来源卡片、摘要、图形等 | `RunEvidence` |
| `POST /sessions/{sid}/runs/{rid}/clarification/reject` | 对当前规划问题选择“暂不回答”；不触发模型或资料查询 | HTTP 200，`{"dismissed":true}` |
| `POST /sessions/{sid}/runs/{rid}/abort` | 请求中止指定 Run | HTTP 202，`Run`；中止请求不等于外部调用已撤销 |
| `GET /sessions/{sid}/runs/{rid}/report?format=md` | 导出 Markdown 资料包 | `text/markdown; charset=utf-8`，下载文件名见 `Content-Disposition` |
| `GET /sessions/{sid}/runs/{rid}/report?format=html` | 导出 HTML 资料包，可在浏览器打印 | `text/html; charset=utf-8` |
| `GET /events` | 订阅本账号 SSE 失效通知 | `text/event-stream`，`event: change` |

`GET /sessions/{sid}/evidence` 是已有的会话级兼容视图；新页面宜按明确 `run_id` 使用 Run 级结果和证据，避免把上一轮事实显示在本轮。

## 5. 消息受理：请求和返回

通用 `MessageBody` 的必填字段仅为非空 `text`，`mode` 当前仅支持 `standard`。盗窃助手的常规自然语言对话使用以下请求；`model_id` 应来自 `/models`，省略时使用本账号获授权的默认模型。新客户端每次用户动作生成一个新 UUID。

```http
POST /api/console/v1/sessions/{sid}/messages
Content-Type: application/json
X-CSRF-Token: <Cookie 模式下由 /me 取得>

{
  "text":"请帮我核对这起警情的来源记录，还缺少哪些条件？",
  "agent_id":"theft-assistant",
  "model_id":"<可用模型ID>",
  "mode":"standard",
  "client_request_id":"00000000-0000-4000-8000-000000000001"
}
```

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{"accepted":true,"run_id":"<本轮Run ID>","message_id":"<本轮用户消息ID>"}
```

`202` 只证明持久受理，**不代表资料查询成功、模型已结束或已有事实**。随后读取 Run。对同一请求标识、同一内容的重放返回首次受理结果；同标识、不同内容返回 409。旧客户端可省略 `client_request_id`，但该兼容路径没有客户端重试去重保证。提交结果未知（例如 504 或连接中断）时先查询会话消息和 Run，不能自动生成新标识重发。

契约还允许 `skill_ids`、`plugin_ids`、`file_ids`、`scope`、`source_refs`、`analysis_task_id` 等字段，用于通用或明确授权的路径。当前盗窃自然语言入口由服务端选择单个受控查询步骤；普通用户无需看到插件、Skill 或接口选择表单。`plugin_ids` 在通用契约里是偏好，不是新的授权。服务端仍检查账号权限、已生效配置、对象、范围、来源和调用预算。前端不得把 `scope` 中未经确认的条件悄悄删去后提交更宽查询。

## 6. Run 状态、补充提问与步骤

`GET /sessions/{sid}/runs/{rid}` 的基本结构：

```json
{
  "id":"<Run ID>",
  "session_id":"<会话ID>",
  "status":"running",
  "phase":"<当前阶段>",
  "created_at":"2026-09-23T09:00:00+08:00",
  "outcome":{
    "version":"run-outcome-v1",
    "status":"processing",
    "label":"<中文状态>",
    "message":"<中文说明>",
    "next_steps":[],
    "execution_status":"<执行状态>",
    "data_status":"<取数状态>",
    "queried":null
  },
  "clarification":null
}
```

以上为**字段形状示例**，并非某条真实 Run 的响应。`Run.status` 为 `queued/running/cancelling/reconciling/completed/failed/cancelled`。`outcome.status` 另有 `processing/unconfirmed/cancelled/failed/needs_input/historical/partial/data_ready/no_query`；两者不要合并成一个“已完成”。`queried` 可为 `true/false/null`，`null` 表示尚不能确认。`completed` 与 `no_query` 可以同时成立，意思是执行结束但没有新的资料查询。

需要反问时，Run 的 `clarification` 为：

```json
{
  "version":"theft-clarification-v1",
  "id":"<问题ID>",
  "missing":["lon","lat","radius_m"]
}
```

前端应在对话里按 `missing` 显示对应的补充问题，而非让用户选择插件。允许的缺项为 `lon/lat/radius_m/start/end/page/page_size/person_identity/source/supported_scope`。用户补齐后作为**新的一条消息**再次调用 `POST /sessions/{sid}/messages`，并使用**新的** `client_request_id`；同一会话上下文会续接该问题。`person_identity` 不要写入前端日志或分析埋点。`supported_scope` 仅在用户明确同意上游默认覆盖范围时填写，不能代替对“近期”“仅盗窃”等限制条件的支持。用户选择“暂不回答”则调用 `POST .../clarification/reject`，请求体为空，返回 `{"dismissed":true}`。

`GET /runs/{rid}/events` 返回持久步骤列表；每项必有 `id/sequence/step_type/name/status`，可选 `started_at/completed_at/elapsed_ms/input_summary/output_summary/record_count/evidence_refs/error_message`。按 `sequence` 增量补查，不能只依赖浏览器保持在线。前端可以默认折叠步骤，让一般用户优先看到自然语言结果。

`GET /sessions/{sid}/task-context` 返回 `schema: "session-context-v1"`、`agent_id`、`version`、`generation`、`last_completed_run_id`、`last_data_run_id`、`pending_clarification_id` 等。可把读取到的 `version` 作为下一次消息的 `context_version`；若期间上下文已变，服务端返回 409 `task_context_changed`，前端应刷新上下文后让用户确认新请求。不能复用旧问题 ID 或跨会话复制上下文。

## 7. 可信结果、取数状态与证据

`GET /runs/{rid}/result` 返回三种结构，由 `version` 区分：

| `version` | 结构 | 页面处理 |
| --- | --- | --- |
| `2.0` | `schema="peixian.analysis-result"`，`run_id/agent/task/data_environment/data_usage/claims/records/missing/narrative/versions/generated_at`，可有 `answer` | 新 Run 的可信结果；按来源展示，允许部分结果和缺口 |
| `2.0` 且 `status="pending"` | `schema/version/run_id/status/data_environment/data_usage` | 正在处理；不要显示为“已取数” |
| `legacy` | `schema/version/run_id/status="legacy"/result:null` | 旧 Run 兼容投影；不按新规则补造来源 |

新策略下的 `answer` 为 `controlled-zh-v1`，包含 `status`（`ready/partial/needs_input/unavailable`）、`summary`、`items`、`missing`、`next_steps`。`claims[]` 每项包含已批准 `claim_id`、`type`（`fact/computed/gap`）、`statement`、`source_ids`、`source_run_id`、`verification_status="approved"` 等。`narrative` 是模型自由说明的核验诊断；前端不能把未经核验的 `narrative.text` 当成可信事实。未知的 `answer.version` 不应按当前受控中文说明渲染。

`data_usage.status` 可为 `not_started/in_flight/confirmed/partial/reused_current_run/historical_evidence/unknown/rejected/cancelled`。此外有 `attempted`、`may_have_sent`、`queried`、`new_call_count`、`reuse_count`、`source_data_run_id`、`modules[]`、`basis`。关键区别：

- `confirmed` 表示响应已确认；`unknown` 表示外部结果待核对，不能自动重发。
- `not_started` 或 `no_query` 不能显示“取得零条资料”；零记录应来自一次已确认的查询。
- `historical_evidence` 标明复用来源 Run，不是本轮再次查询。
- `partial` 保留已取得事实，并展示未取得的模块和资料缺口。

独立读取取数状态时，`GET /runs/{rid}/data-usage` 返回的是外层 `{run_id,result_version,data_usage}`，不要误把外层对象本身解析成 `DataUsageV1`。`data_usage:null` 表示该 Result 没有可用的该结构，不能当成 `queried:false`。`answer.items[]` 中每个条目都带 `text/claim_id/source_run_id/source_ids`，页面点击事实时可据此打开对应来源。

`GET /runs/{rid}/evidence` 至少包含 `run_id/status/cards/summary`。`status` 为 `pending/empty/partial/complete/unavailable`，可选 `presentation`、`diagram`、`missing`、`processing_version`、`execution_methods`、`plugin_versions`。卡片的 `source_ids`、`snapshot_id`、`message_id` 用于返回原始来源；图形可缺席，旧 Run 无图形时保持文字结果。会话消息 `parts` 支持 `text/tool/analysis_result`；服务端生成的可信 `analysis_result` 有 `origin="verified_result"`，不能把模型消息中任意同名字段直接提升为证据。

## 8. SSE、取消、错误与恢复

`GET /events` 使用 `text/event-stream`，保留 `event: change`。`data` 的 `type` 可为 `connected/updated/run.updated`，也可能通知 `resync_required`；可附 `resources`（例如 `messages/runs/sessions`）、`session_id`、`run_id`。收到事件后按当前会话和 Run 做合并 GET 补查。旧版 `updated` 没有资源类别时刷新消息及会话；断线后重新读取持久历史。心跳不是新消息，前端不应生成重复卡片。

中止使用 `POST /sessions/{sid}/runs/{rid}/abort`。返回 HTTP 202 和当前 Run；若状态是 `cancelling` 或 `reconciling`，界面应显示处理中或待核对，不能说外部资料操作已经撤销。任务终态仍以之后的 GET 为准。

错误响应至少有 `message`、`code`，可有 `request_id`、`field_errors`：

```json
{"message":"<面向用户的说明>","code":"<稳定错误码>","request_id":"<排障关联号>","field_errors":{"<字段>":"<原因>"}}
```

| HTTP 状态 | 前端处理 |
| --- | --- |
| 400 / 422 | 显示字段或范围问题；保留输入，按具体 `code` 提示 |
| 401 | 重新登录；旧 SSE 应关闭 |
| 403 | 权限、CSRF、Origin 或初次改密要求不满足；不要把受限接口当空数据 |
| 404 | 资源不存在或不属于本账号；不要泄露其他账号是否存在该 ID |
| 409 | 会话忙、上下文版本过期、配置或资源状态冲突；先 GET 核对 |
| 413 | 文本、文件或引用预算超限；让用户拆分或缩小输入 |
| 429 / 503 | 尊重适用的 `Retry-After`；只对读取做退避，不自动重放模型写请求 |
| 504 | 写入结果可能已提交；先查 Run、消息及上下文，不自动重新发起 |

`Run.error` 的 `code/message` 是执行层错误；`Run.outcome` 是面向用户的状态解释；HTTP 错误表示本次接口请求失败。三者可能处于不同时间点，页面刷新时以最新持久 Run 为准。

## 9. 前端接入核对清单

1. 确认页面使用同源 `19460` 入口，Cookie 模式写请求附 `X-CSRF-Token`；退出后清理本地 Run 与 SSE 状态。
2. 会话创建后才发送消息；盗窃助手发送 `agent_id="theft-assistant"`，用户自然输入即可，无需先选插件或接口。
3. 收到 202 后保存 `run_id`，由 SSE 触发 GET；刷新后通过 Run 列表恢复，不自动重发消息。
4. `Run.clarification` 存在时用问答卡片补齐缺项；“暂不回答”走 reject；新回答使用新请求标识。
5. 将 `Run.status`、`outcome.status`、`data_usage.status` 分开显示。执行结束、未取数、已确认零记录和结果未知必须有不同文案。
6. 可信事实仅用 Result V2、服务端 `analysis_result` 和 Run 级证据；来源记录、版本、缺口应可追溯。
7. 报告在 Run 达到允许导出的状态后获取；`format=md|html` 由用户明确选择。未知版本、旧 Run 和部分结果保持可读的降级提示。
8. 联调记录同时标注运行镜像 ID、源码提交、OpenAPI 规范化摘要、测试账号角色和实际 Run ID；记录前脱敏账号资料与请求正文。

## 10. 核对范围与限制

本文已核对**运行容器镜像、镜像源码标签、页面入口脚本和线上 OpenAPI 结构**。接口示例使用占位符，没有在编写本文时提交新模型请求、调用真实资料接口或改动运行配置。盗窃真实资料连接是否可用、具体上游数据覆盖和完整业务链路通过情况，仍应以对应联调报告和每次 Run 的 `data_usage`、来源记录为准。OpenAPI 包含一些历史兼容或管理接口；本文聚焦当前盗窃助手自然语言对话链路，其他接口以同版本机器可读契约为准。
