# 前后端第十二轮适配：实时推送与追问作答接口

## 1. 版本与边界

后端基线为 `codex/theft-prompt-entry` 提交 `02e4d20f3`，前端基线为 `chat-ui-r3` 提交 `81e6fe157`。前端改动在新分支 `chat-ui-r4-live`。

本轮只作用于新产生的执行。旧会话、旧执行不迁移、不回填：旧执行没有推送事件，`/messages` 里旧的追问回复也没有 `message_kind`，前端按原样显示。schema 仍为 11，没有新增数据表。

推送的内容只有两类：已校验的来源片段，以及平台按章节切开的最终回答。模型原文、推理过程、未校验的 token 都不推送。

## 2. 能力声明

`GET /capabilities` 的 `message_support` 新增两个字段：

```json
{"message_support":{"version":"message-support-v1","question_answers":true,"live_push":"live-push-v1"}}
```

前端只在 `question_answers === true` 时调用新作答接口，否则继续走旧的 `POST /messages`。

## 3. `/events` 新增事件

仍是 `event: change`，`data` 是 JSON。旧的 `updated`、`resync_required` 不变。新增两种，都带 `"version":"live-push-v1"`。

### 3.1 回答片段 `answer.segment`

```json
{"type":"answer.segment","version":"live-push-v1","session_id":"ses_x","run_id":"run_x","message_id":"msg_a","part_id":"part_answer_run_x","sequence":4,"display_kind":"final_answer","origin":"controlled_answer","final":false,"index":1,"count":3,"text":"### 人员一\n\n……"}
```

- `display_kind=source_answer`：某次资料查询完成后的来源片段，`part_id` 为 `part_delivery_<run>_<序号>`，`message_id` 是来源片段专用消息。
- `display_kind=final_answer`：执行完成后，最终回答按 `### ` 标题切成最多 16 段依次推送。所有段共用 `part_id=part_answer_<run>`，`index` 从 0 开始，`count` 是总段数。按 `index` 顺序拼接后与 `/messages` 中同一 `part_id` 的文本逐字相同。`message_id` 是该执行的助手消息 ID。
- `sequence` 在同一执行内连续递增，来源片段在前，最终回答段接在后面。
- `final=true` 只出现在最终回答最后一段，表示片段流结束，不表示执行成功。
- 单段转义后超过 192 KiB 时不带 `text`，改为 `"truncated":true`，前端需要补读。

### 3.2 执行进度 `run.progress`

```json
{"type":"run.progress","version":"live-push-v1","session_id":"ses_x","run_id":"run_x","phase":"tool_running","label":"正在查询「警情」"}
```

`label` 是固定中文文案，可直接展示。`phase` 取值：`queued`、`thinking`、`tool_running`、`tool_done`、`tool_failed`、`waiting_question`、`waiting_permission`、`reconciling`、`cancelling`，以及终态 `completed`、`failed`、`cancelled`（终态事件同时带 `status`）。

### 3.3 丢失与补读

事件可能因断线或队列溢出丢失（溢出时会收到 `resync_required`）。以下情况前端应补读 `GET /sessions/{sid}/runs/{rid}/answer-segments?after=0&limit=100`：收到的 `sequence` 与本地已有的不连续，或事件不带 `text`。补读结果中 `display_kind=final_answer` 的条目与推送字段一致。

补读或推送都失败时，`/messages` 仍返回完整的持久化内容，前端以它为准：同一 `part_id` 出现在 `/messages` 后，丢弃本地推送的副本。

### 3.4 通知合并

同一内容的 `updated` 通知 150 ms 内只发首条和一条尾随通知；`answer.segment`、`run.progress` 不合并、不延迟。

## 4. 追问作答接口

```http
POST /api/console/v1/sessions/{sid}/runs/{rid}/answers
X-CSRF-Token: <csrf_token>
```

`rid` 是提出问题的那次执行。回复文字由服务端生成，前端不再自己拼。

| kind | 请求体 | 服务端生成的文字 |
|---|---|---|
| `clarification` | `question_id`（即 `run.clarification.id`），`values`：按 `missing` 字段逐项填写；`supported_scope` 填 `option-1` 或原选项文字 | 与原前端 `clarificationAnswer` 相同，例如 `经度：116.1；纬度：34.2；半径：500 米` |
| `next_question` | `question_id`（即 `answer_view.next_question.id`），`option_ids`，可选 `custom_value`（≤500 字） | 选中选项文字与自定义内容用 `；` 连接 |
| `stop` | `question_id` 可省略 | `不再追问，请基于已取得资料直接作答。` |

所有请求都必须带 `client_request_id`（UUID），可选 `model_id`，省略时沿用原执行的模型。

`next_question.options[]` 新增 `id`（`option-1`、`option-2`…），只有新执行有。`send=false` 的选项仍由前端放进输入框让用户编辑，不能通过本接口提交（返回 422）。

成功返回 202：

```json
{"accepted":true,"run_id":"run_child","message_id":"msg_child","question_id":"next-run_x","kind":"next_question","parent_run_id":"run_x","answer_label":"核查夜间出现","message_kind":"question_answer"}
```

错误：

- 422 `invalid_answer`：字段格式不对，`field_errors` 指出具体字段。
- 409 `question_already_answered`：该问题已被另一个请求回答。
- 409 `question_expired`：问题不存在、已关闭，或会话里已有更新的执行。
- 409 `request_conflict`：同一 `client_request_id` 提交了不同内容。
- 同一 `client_request_id`、同一内容重试，返回首次受理结果，不会重复派发。

## 5. 消息与执行字段

`GET /sessions/{sid}/messages` 中，通过本接口产生的用户消息的 `info` 增加：

```json
{"message_kind":"question_answer","question_id":"next-run_x","question_kind":"next_question","parent_run_id":"run_x","answer_label":"核查夜间出现"}
```

前端据此显示“已选答案”样式，不再使用 `sessionStorage`。

`GET /runs/{rid}` 增加 `answered_questions`：已经回答过的问题 ID 列表。前端据此不再弹出已回答的下一步问题卡片。

## 6. 前端改动（`chat-ui-r4-live`）

- `events.ts`：新增 `parseLive`，只接受 `live-push-v1` 且 ID 合法的事件；变更总线增加 `subscribeLive`。
- `live-answer.ts`：合并推送片段；最终回答各段只在 `index` 连续时拼接，缺段就停在缺口前，不会拼错；`/messages` 返回同一 `part_id` 后让位。
- `Chat.tsx`：
  - 推送片段即时显示，并沿用 `SmoothMarkdown` 的逐字效果；
  - 等待提示显示 `run.progress` 的文案；
  - 追问卡片、下一步卡片、“不再追问”改为调用 `/answers`；
  - 用户消息是否显示为“已选答案”，改看 `message_kind`。
- 服务端未声明 `question_answers` 时，全部回退到旧行为。
