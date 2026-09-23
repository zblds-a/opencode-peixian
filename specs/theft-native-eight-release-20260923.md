# 盗窃助手八项资料插件发布与清理记录（2026-09-23）

## 交付状态

本次已在 `https://36.134.45.38:19460/` 对应的测试站点部署八项独立资料插件 `3.0.0`，并将两个普通测试账号的当前运行环境切换到这组插件。八项受控服务连接指向服务器现有的私网合成资料 Mock（`172.17.0.1:19464`），没有指向真实供应方资料接口。用户另行明确授权后，活动控制库中其余 31 个旧插件发布版本、旧安装与绑定，以及无新引用的 31 个旧包已物理清除；历史 Run 和完整备份保留。

**已完成的是八插件发布、Mock 接入、账号运行环境切换和旧插件清理。模型实际选择并调用插件、非空来源跨步骤链路及真实供应方接口仍未通过本轮验收。**

## 版本与运行身份

| 项目 | 本轮身份 |
|---|---|
| 源码分支 | `eight-data-tools`（服务器隔离工作树，未推送 GitHub） |
| 本轮运行源码提交 | `5f81991167ea1983fb14b6023a1cfb4f949f0297` |
| 数据库 | schema v11，升级过程中未提高版本 |
| Control 镜像 | `sha256:3f98aab4c334c1b1419d70caaf6affb8d1f80f5c28e88713a01a7473a5dba908` |
| Gateway 镜像 | `sha256:b04aff3516e50c9802fd9ad035abbf261babb5a999a5b802ac60f98cf0fb96b8` |
| Agent 镜像 | `sha256:7eb5b8e2d442ca1dce7f18acc77170533dbf4abee8a5a5ab46cf12221607de48`（沿用原匹配镜像） |
| HTTPS 镜像 | `sha256:c318e336065b17ff460aeac6d14bce5d0b13e35f25d5cb1843b635359fc00c9a` |
| 前端静态入口 SHA-256 | `272076ab21c5cb836c5cec6e0f8588d01d5a2c703959363bc86a9620489b7513`，与发布前一致 |
| 站点 | `https://36.134.45.38:19460/`；本轮只读检查首页 HTTP 200 |
| Worker | `peixian-alignment-worker.service`，本轮只读检查 `active` |

本轮在目标机保存了已验证的完整备份：`/srv/peixian-eight-complete-backup-20260923-1635`。备份验证状态为 `verified`，包含 7 个持久卷和 2 个运行环境；清单 SHA-256 为 `69457b5f3d2886b8e4f0880fc246e291a5cbc990fa9f3393bb407be55f30d819`。原始平台配置另以权限受限文件保存在该备份目录。**本轮未在空命名空间执行完整恢复演练**，不能将“备份验证”表述为“恢复验收通过”。

## 八项插件与 Mock 连接

| 独立插件 | 模型工具 | Mock 合同路径 |
|---|---|---|
| `peixian-theft-incidents` | `peixian_query_incidents` | `POST /jq/search` |
| `peixian-theft-captures` | `peixian_query_captures` | `POST /jq/capture` |
| `peixian-theft-tracks` | `peixian_query_tracks` | `POST /track/person` |
| `peixian-theft-night` | `peixian_query_night` | `GET /caputer/selectNightList` |
| `peixian-theft-community` | `peixian_query_community` | `GET /system/croess/list` |
| `peixian-theft-warning-detail` | `peixian_query_warning_detail` | `GET /system/multiDimension/idCard/{idCard}` |
| `peixian-theft-warning-logs` | `peixian_query_warning_logs` | `GET /system/multiDimension/logs/{idCard}` |
| `peixian-theft-profile` | `peixian_query_profile` | `GET /caputer/profile/{idCard}` |

各连接经只读核对仅允许相应的方法和路径，固定在现有私网 Mock 地址；插件包只向模型注册表中所列的单一资料工具。原始路径拼写 `caputer`、`croess` 依合同保留。服务器 Mock 的 `/jq/search` 使用合成位置发起一次受控请求，返回 HTTP 200、`synthetic=true`、`total=6` 与 6 条记录；这只能证明该接口的 Mock 连通与非空响应，不能证明八项都经历过模型工具调用。连接凭据和合成对象字段未写入本记录。

## 迁移、物理清理与数据保护

在控制库副本中先演练八项发布、两个账号迁移和旧插件归档，确认旧运行环境仍在使用旧版时清理会被拒绝。目标站点停写、完整备份并更换匹配 Control/Gateway 后，先迁移账号 A，确认环境 `ready`、实际发布目录只含八项 `3.0.0`；再迁移账号 B，作相同确认。两账号当前 Gateway 均使用本轮镜像，Agent 镜像未变，当前环境无旧工具注册。

两个账号切换后，先归档 31 个旧发布并停用 16 条旧专用连接，再依据用户的明确授权执行物理清理。工具回执：`deleted_releases=31`、`deleted_packages=31`、`historical_runs_unchanged=true`。之后从实际活动控制库只读复核：`plugins=8`、`plugin_connections=8`、包目录 ZIP 数量 `8`、`business_runs=176`、`PRAGMA quick_check=ok`。旧发布不再位于活动目录；历史 Run、消息、证据及完整备份未清除。历史运行环境发布目录可能仍包含旧版文件，作为冻结历史及恢复材料，不属于当前运行工具目录。

回退需使用与 schema v11 兼容的成套 Control、Gateway、Worker 版本和旧账号完整配置；若恢复升级前完整备份，只能恢复到空目标并核对升级后新增的数据，不能让旧程序直接读取当前库，也不能用旧备份覆盖新会话或文件。

## 测试证据与验收缺口

- 源码定向测试：Control `82 passed`，Gateway `12 passed`；平台配置兼容验证 `2 passed`。测试覆盖八包独立工具、固定路径和参数、来源/意图绑定、撤权前拦截、同 Run 独立调用、历史回执及 OpenAPI。
- 控制库副本：schema v11、`quick_check=ok`，八插件发布及双账号迁移完成；在旧 runtime 尚未退出时归档保护按预期拒绝。
- 目标站点：Worker `active`；Control 与 HTTPS 容器健康；首页 HTTP 200；两账号运行环境 `ready`；活动插件与包文件均仅剩八项；数据库 `quick_check=ok`。
- 广覆盖 Control 回归曾得到 `101 passed / 20 failed`，失败包含仍假定旧 `sample-records` 可发布的旧夹具及 Windows 符号链接权限。未将广覆盖回归计为通过，也没有把旧测试结果冒充目标机验收。
- **尚未完成**：两个账号通过模型原生工具调用执行八项中的定向请求；从问答补条件到实际调用、来源卡片、逐条复核和导出的完整链路；真实供应方连接与合同条件确认；两条有非空来源的真实业务链路；完整备份恢复演练。这些项目应单独验收，不能由 Mock 直连、环境 `ready` 或首页 200 推断通过。

后续联调时，先在现有测试账号中分别发起一条周边警情和一条人员资料问题，核对冻结参数、独立意图复核、实际插件回执、来源记录及中文说明；失败或结果未知不自动重试。再按已确认来源串接后续步骤，并检查复核和导出，不在无凭据或合同不明确时调用真实供应方接口。
