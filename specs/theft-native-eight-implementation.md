# 盗窃助手原生工具调用与八项资料插件：候选交付记录

> 状态：源码候选；未部署现网，未访问真实供应方接口，真实双链路验收未完成。基线提交 `0c3fff36cdf0d7ba6b3bf30934fffecc91bf8e60`。本文件随实现提交冻结；发布前须重新核对服务器源代码、镜像及数据库状态。

## 用户如何使用

普通用户选择盗窃助手后直接用简体中文提问。问候或解释已有结果可不取数；需要新资料时，模型选择零个、一个或多个可用工具。缺少人员、位置来源、时间或半径时使用平台问答工具追问。由案到人、由人到案只是同一会话内可变化的提问方向，不是两个固定业务流程。用户无需选择接口。

模型提出工具名和参数后，Control 先从当前账号、会话、持久 Run 与用户确认范围核对参数；Gateway 用独立、禁用工具的模型调用复核意图。允许结论仅绑定本次 call ID、冻结参数摘要、来源引用、配置和范围版本。实际资料投递前再次核对授权、运行状态和连接绑定。未知结果不自动重发。模型说明与已核对来源卡片分离；有来源编号不等于句子已核验。

## 当前八项业务资料插件

| ID | 工具 | 上游接口 | 最小确认条件 |
|---|---|---|---|
| `peixian-theft-incidents` | `peixian_query_incidents` | `POST /jq/search` | 经度、纬度、半径；仅空间和分页 |
| `peixian-theft-captures` | `peixian_query_captures` | `POST /jq/capture` | 单个位置来源、独立确认抓拍时间及半径 |
| `peixian-theft-tracks` | `peixian_query_tracks` | `POST /track/person` | 一名明确人员、轨迹起止时间 |
| `peixian-theft-night` | `peixian_query_night` | `GET /caputer/selectNightList` | 一名明确人员、合同时间及分页 |
| `peixian-theft-community` | `peixian_query_community` | `GET /system/croess/list` | 一名明确人员、适用时间及分页 |
| `peixian-theft-warning-detail` | `peixian_query_warning_detail` | `GET /system/multiDimension/idCard/{idCard}` | 一名明确人员；类型数不作事件数 |
| `peixian-theft-warning-logs` | `peixian_query_warning_logs` | `GET /system/multiDimension/logs/{idCard}` | 一名明确人员；固定近七天口径 |
| `peixian-theft-profile` | `peixian_query_profile` | `GET /caputer/profile/{idCard}` | 一名明确人员；最近抓拍非完整轨迹 |

新版本为不可变 `3.0.0` 插件包，由 `deploy/peixian/examples/theft_provider_v2/build_native.py` 生成。每包只声明一个模型资料工具。模型侧 loader 强制实际导出工具与 manifest 完全相同，随后通过私有 Gateway 桥接；Agent 不持有服务连接。Gateway 执行的是 Control 冻结的请求，出口继续校验固定方法、路径、请求字段、单位、分页、响应大小和连接身份。`caputer` 与 `croess` 路径按供应方合同保留原拼写。合同有歧义的额外明细不在八项允许清单内。

## 请求、状态和结果

普通消息继续使用 `POST /api/console/v1/sessions/{sid}/messages`，`client_request_id` 为用户请求幂等标识，`agent_id` 为 `theft-assistant`。已有 `scope`、`source_refs` 可供前端在问答后提交结构化已确认条件；它们不让客户端直接选择上游地址或绕过审查。示意：

```json
{
  "agent_id": "theft-assistant",
  "text": "请查询这个明确位置周边的警情",
  "scope": {"lon": "116.1", "lat": "34.1", "radius_m": 500},
  "client_request_id": "7f1c17f0-639c-45dc-a404-9280f8f18d1f"
}
```

受理仍返回 HTTP 202 的 `accepted/run_id/message_id`。同键同内容返回原 Run；不同内容为 409。每个模型工具调用使用 OpenCode call ID 建立独立冻结记录，状态为核对中、允许、投递中、完成、拒绝或未知。独立意图核对只返回 `allow/clarify/deny`，不能改参数。取消或撤权后不得投递新资料；取消未确认仍保留待核对。连续重复已冻结查询拒绝，不以随机重发扩大范围。

终态 `Result V2` 沿用原路径，增加原生执行的来源记录、代码 Claim、逐次模块回执和 `native-provider-gate-v1` 版本信息。`narrative.status=unverified` 表明模型自由说明未自动获事实认证。历史 Run 保留原冻结版本和结果，不从当前接口重取或重算。

## 部署和归档顺序

1. 在完整备份中包含控制库、密钥、发布包、账号配置、镜像清单、宿主执行状态与账号卷；记录源码 SHA、镜像 digest 和数据库 schema。先在副本验证恢复。
2. 隔离部署匹配 Control、Gateway、Agent 与 Worker，确保 `schema >= 11`。连接凭据仅由受控配置渠道提供；合同、认证和验收范围未确认的真实接口保持关闭。
3. 发布八个 `3.0.0` 包，为测试账号按最小权限分别授权、安装、绑定受控服务连接，完成配置发布并核对实际运行工具目录。新原生路由由 `PX_THEFT_NATIVE_UIDS` 按账号启用；旧规划路由不得用于这些账号。
4. 用 `python -m control.eight_plugin_archive inventory` 只读盘点发布、授权、安装及已应用旧插件。账号没有活动 Run 和环境任务时逐一执行 `account --uid ... --receipt ...`，撤销旧授权、停用旧安装、阻断并排队发布完整新配置；保存加密回执。核对该账号运行环境和八项范围后再迁移下一账号。
5. 所有账号确认不再应用旧插件后执行 `archive`；历史发布包和 Run 不删除。仅旧插件专用连接会停用。不要将数据库或整卷回退覆盖迁移后新增的会话与文件。

归档工具不会为账号自动授予全部八项；已有个人 Skill 不覆盖，旧依赖在能力目录中标记不可用。平台内置问答、会话、文件和运行管理能力不在业务插件清理范围。

## 本轮验证和缺口

已在隔离 Windows 工作区完成：新八包逐一 Node 行为测试、固定接口拒绝、Control 参数与来源/意图绑定、撤权前投递拦截、同一 Run 两次独立调用、历史 v1/v2 回执及 OpenAPI 回归。最终定向测试为 Control 80 通过、Gateway 12 通过。未使用模型或真实资料接口。全量旧测试仍使用可发布 `sample-records` 等已归档插件的旧夹具，因此严格白名单下有兼容性失败；Windows 符号链接权限也导致一项平台无关失败。不能把这些项目计为全量回归通过。

发布前仍须补齐：旧测试夹具按新白名单改造、归档工具在控制库副本的迁移/恢复演练、Gateway/Agent/Worker 匹配镜像构建、两个账号真实非空来源跨步骤联调、逐条复核与报告导出、前端实际问答体验。服务器在开发期间出现独立 `backend-separation` 候选 Control/前端容器，发布前须确认其归属并整合最新镜像，不能覆盖同事工作。未确认的供应方接口和凭据保持待联调。
