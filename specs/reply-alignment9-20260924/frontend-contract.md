# 前后端第九轮适配：接口与接入说明

## 1. 版本与边界

本轮基线为后端提交 `03f60dbb4ebed1d115ca559457eb1d34ba3e6c64`。检查时正式镜像为 `peixian-control:chat-ui-9bc8e5989-20260924-r4-prod`，ID `sha256:ce7bbbccc6e050659d52bf84fc5d332b945cea7b79491831199672d863568b4c`，前端版本 `9bc8e59898f07fcc3bf1acd8d58897ab9f92baa3`。

这是新增后端候选契约，不代表该正式镜像已经包含新接口。保留 schema 11、现有 Cookie/Bearer、CSRF、消息、Run、报告和图谱入口。未修改前端源码、提示词、评分或排名逻辑。部署前比对发现正式镜像已移除旧内置Skill自动加载，候选保留该线上行为；个人Skill显式选择仍沿用正文注入，不重新启用被移除的隐式加载。实例来自隔离的虚构数据契约测试，不是生产账号或真实供应方验收。

本轮增量是“已校验的完整资料片段”，不是未经校验的模型 token。最终回答仍为独立消息；片段与最终回答使用不同稳定消息 ID，不以替换片段的方式展示最终回答。

## 2. 能力与附件支持查询

`GET /api/console/v1/capabilities` 仍返回 `items/total/page/page_size`，新增：

```json
{"message_support":{"version":"message-support-v1","file_ids":true,"max_files":5,"file_usage":"user_reference","requires_ready":true,"allows_truncated":false,"plugin_ids":"preference","skill_ids":"method"}}
```

每项能力新增 `selectable_in_message`、`selection_mode`、`selection_unavailable_reason`。`enabled` 只是安装开关，不代表可选或已经调用。前端使用 `selectable_in_message` 决定能否附加单轮选择。

原生工具模式接受已经授权、生效的插件偏好和个人技能以及已解析的文件。旧规划模式仍返回 `planning_attachments_unsupported`，其能力支持标志为 false/unavailable；不能仅根据助手显示名推断是否支持。

插件 preference 不保证执行、不限制其他已授权能力。个人技能作为方法正文进入当前上下文，不赋予权限。公共模板仍需复制为个人技能。

## 3. 上传和随消息关联

1. 沿用原 `/files` 上传与解析查询，文件必须属于当前账号。
2. 等待解析 ready，且 truncated=false。上传成功不等于进入当前消息。
3. 前端保留待发送附件 chip，并提交 file_ids。

```http
POST /api/console/v1/sessions/{sid}/messages
Content-Type: application/json
X-CSRF-Token: <当前登录会话的 csrf_token>
```

```json
{"text":"请整理我上传材料中明确记载的内容","agent_id":"theft-assistant","file_ids":["file-example"],"skill_ids":[],"plugin_ids":[],"mode":"standard","client_request_id":"e52df1a7-e5bd-4ec9-8509-b9cd732e58aa"}
```

受理仍为 202 和 `accepted/run_id/message_id`。client_request_id 同键同内容返回原 Run，不重复读取后再执行；冲突内容返回409。新请求重新验证文件归属和解析状态。

文件解析正文、分块来源进入加密 Run 请求快照；快照中的附件元数据保存 `id/name/parse_status/content_sha256/text_bytes/chunk_count/usage/verified_source`。消息 attachments 回显这些字段及 available/unavailable。文件后续重命名不改历史名称；删除不会导致历史请求重新取数。正文不会在普通元数据审计中回显。

附件只作 user_reference，verified_source=false，不直接生成已批准 Claim、图谱或来源卡片。文件内对象、时间和指令不自动成为工具调用授权；当前范围解析和执行核对继续依据用户要求及已确认上下文。

| 拒绝条件 | HTTP | code | field_errors |
|---|---|---|---|
| 不存在或无权 |404|file_not_found|文件ID: not_found|
| 未解析完成 |409|file_not_ready|文件ID: not_ready|
| 部分解析或截断 |413|file_truncated|文件ID: truncated|
| 无正文 |409|file_text_empty|文件ID: empty_text|
| 解析结构错误 |409|file_parse_invalid|文件ID: invalid_chunks|
| 引用超预算 |413|file_budget_exceeded|文件ID: budget_exceeded|
| 文本、技能、文件总量超预算 |413|message_budget_exceeded|text: UTF-8限制|

保持最多5文件、24000字符文件引用上限、文字技能与文件合计18000 UTF-8字节限制。前端显示明确的文件错误，不能静默丢附件后发送。

## 4. V2 来源卡片

`GET /sessions/{sid}/runs/{rid}/result` 的已保存 V2 增加 `presentation`：

- version: source-clues-v1；status: ready/partial/empty；revision: 内容摘要。
- clues[]：稳定 id、type、title、headline、summary、discoveries、evidence、source_run_id、source_ids、claim_ids、missing。
- evidence[]：稳定 id、label、content、occurred_at、time_semantics、source_run_id、record_id、claim_id、snapshot_id。

卡片只使用已批准的逐条事实及相符的来源字段、快照；不读取模型自由说明或排名。当前映射为轨迹/抓拍/预警→observation，档案→person，警情/跨小区→place，夜间→night。当前八接口没有资金或车辆专用记录时不会凑出相应卡片。六种类型是显示协议，不承诺每次均有六类数据。

警情 cjsj 标记为处警时间来源，不能当作案发时间。未知时间为 null。前端按普通文本渲染动态字段，不执行内容里的 HTML。

稳定来源锚点用 evidence.id，不要再以 details 索引或模型生成的标题作为身份。来源详情通过 source_run_id 及 record_id 关联当前用户可访问的 Result，所有跨账号请求均拒绝。

旧 Run 不补写 presentation；返回其原有持久结果。前端未知版本显示不支持提示，不按任意原始记录自行推造卡片。

## 5. 受控资料增量

```http
GET /api/console/v1/sessions/{sid}/runs/{rid}/answer-segments?after=0&limit=100
```

新增只读、本人鉴权入口。after 是已成功应用的最后序号；limit 为1–100。不调用模型或上游。响应：

```json
{"version":"controlled-segments-v1","run_id":"run-example","message_id":"msg_delivery_run-example","status":"streaming","items":[{"sequence":1,"content_revision":1,"part_id":"part_delivery_run-example_1","operation":"append","origin":"controlled_source","visibility":"user","display_kind":"source_answer","text":"已核对的完整资料片段","source_ids":["source-example"],"claim_ids":["claim-example"]}],"next_sequence":1,"final":false,"has_more":false,"execution_status":"running"}
```

- 每次已授权插件完成并通过响应合同核对后，在同一保存事务内追加片段；失败、未知、未完成和不符合同的回执不产生成功片段。
- 每次展示最多5条已核对记录并明确显示取得数量，完整记录仍在结果中。没有擅自丢弃底层记录。
- `sequence` 在同一 Run 单调增加。片段发布后不修改，content_revision 固定1；收到重复序号按幂等处理。
- 新请求/重跑对应新 Run，不能把旧游标用于新 Run。游标超前返回 sequence_ahead 409。
- `final=true` 只表示片段流封闭，不能理解为执行成功；必须结合 execution_status。
- 取消中仍显示 cancelling，确认取消后 final=true，保留此前已经确认的来源，不把取消说成外部操作已撤销。
- 旧 Run 没有该日志，status=unavailable，不重新查询补造。

现有 messages 完整快照也会提供相同的稳定资料消息/part。前端只能选一种渲染归并方式：使用快照展示，或用增量按 message_id/part_id/sequence 合并；不能同时渲染两份。原有 SSE change/run 通知可用作 GET 补查信号，仍应保留周期补查；没有新建未经核验 token SSE。

最终模型回答沿用原有独立 part_answer，display_kind=final_answer。资料片段 display_kind=source_answer。两者不要求正文互为前缀；同一片段内全文与增量必须一致。本轮不提供撤回已发布事实的管理接口；需要更正时保留原来源并另行明确更正，不能承诺可撤销 token 协议。

## 6. Run 与消息状态

Run.status 是按钮、停止和执行终态的权威字段；会话 status 只是聚合展示。新增 status_revision（本次执行状态转换递增）、event_sequence（执行步骤序号），两者不可混用。

answer_delivery 元数据包含版本、最新片段序号、final、result_saved、phase。phase=running 表示未形成最终保存结果，answer_ready 表示结果已保存可读取，unavailable 表示没有最终可用结果。该值是展示投影，不修改 Run.status 枚举。

状态更新、终态结果与片段封闭均经现有事务保存；旧 Run 可能 status_revision=0。客户端忽略旧 revision 的状态响应。执行步骤提供 origin=execution、visibility=user、display_kind=execution_step，沿用稳定 step_id/call_id 和已有终态不倒退机制。

正常流程：202→running→一个或多个来源片段→终态与result_saved→最终回答快照。
取消流程：running→cancelling→确认cancelled；已有片段保留。
失败流程：已成功片段保留→failed；不能当作所有取数失败或零记录。
未知流程：reconciling/unknown，不自动重发。
重连流程：GET Run→按after补片段→GET messages/result；不重放POST。

## 7. 图谱

保持已有 graphs 目录、详情、节点、展开、路径接口。新投影版本只为有明确对象字段或冻结且核对一致的人员引用创建“人员—来源记录归属”边；不据轨迹相近、标签或时间接近推断人与人的关系。无明确对象的警情、无对象依据的汇总仍可有卡片而无图谱边。

新结果 versions.reply_projection=source-clues-v1 才启用新映射；旧结果读取不改用新规则。ready/partial 均可能有可用边；empty 无可投影关系，pending 未结束，unavailable 历史版本不支持。详见 contract-samples.json 的非空同Run样例。

## 8. 发布与前端待接入

1. 将文件chip的提交开关绑定 message_support.file_ids；上传成功后不立即发查询。
2. V2读取 presentation.clues，保留旧 V1 兼容，不从records猜线索。
3. 使用稳定来源evidence.id保存展开状态。
4. 增量按稳定消息/part/sequence合并，终态仍以Run为准；展示资料片段和最终回答的区别。
5. 不需要改CSS或切图。正式镜像125层，不能继续FROM叠加发布；重建/可审计扁平化后必须逐项核对入口、环境、用户、工作目录、卷、健康检查及静态文件哈希。

本轮未修改正式 Compose；正式发版、真实账号浏览器接入和双账号最终验收必须在候选验证后分别记录。
