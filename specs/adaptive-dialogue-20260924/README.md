# 由人到案对话优化与接口兼容说明

## 范围

基线：19460 的 contract9-r7-20260924-r2，服务器源码 9ac7ff5e7f9b176b9a340b585dda2ea4895beb92。新策略为 adaptive-dialogue-v1，只用于新受理的原生资料对话；历史 Run 不重算、不改写。八插件和 Gateway 自动允许配置保持。

## 已实现

- 新策略绑定独立盗窃对话提示词，取消强制八接口全查及自动绑定停留中心、默认半径。模型按需调用；问候与解释不要求取数。
- 已确认条件继续继承；抓拍的时间和半径单独保存用途，不能自动借用轨迹时间。缺哪项问哪项。
- 活跃 Run 中已完成、合同有效的资料可以成为位置候选。候选仍须用户明确选择，不默认选择第一条。
- 单条来源引用使用 record-v1 摘要，绑定 Run、任务、助手、环境、记录与快照；追加其他调用不导致已选条目失效。所有引用继续执行账号和会话归属校验。
- 问答工具显示“补充查询条件”；仅精确的问答取消错误映射为取消，其他错误保持失败。
- Agent 确认结束且最后一步为取消问答时，若无未知或未结束资料调用，保存阶段摘要并完成对话；不追加模型或资料请求。整轮取消仍按取消处理，模型错误仍保留失败。
- 待补充或取消查询纳入资料缺口，成功结果保留。阶段摘要与来源独立保存，可刷新恢复。

## 前端接口

路径与原字段不变，无数据库迁移、无新增业务插件。现有 status=cancelled 已支持，不新增状态枚举。

Run.outcome 对补充取消后的正常收尾返回 status=partial，execution_status=completed；label 为“已有资料已整理 · 补充查询已停止”。data_status 仍表达资料状态，不等于执行状态。

Result V2 的 answer.status 在有成功资料且有未补充项时为 partial；missing 说明相关模块尚未查询。来源 records、claims 和原有四段式 answer_view 保留。

受控增量在现有 answer_delivery 中追加一次阶段摘要，稳定 part_id=part_completion_{run_id}。刷新与重复核对不追加第二条，不触发接口查询。

来源引用仍为 run_id/result_digest/record_id/snapshot_id。前端应原样传递 result_digest，不自行解析摘要；record-v1: 前缀表示单条来源摘要，旧的整份结果摘要继续兼容。

## 提示词位置

服务器候选工作区：/root/PeiXianDB/adaptive-dialogue。

新原生对话提示词：services/peixian-control/control/agents/profiles/theft_dialogue_prompt.md。

平台参数提示：control/native_tool_scope.py:model_context。

绑定入口：control/agents/runtime.py:bind(native_dialogue=True)。本轮请求保存 dialogue_policy 和最终组合提示词 SHA；不覆盖个人 Skill 或旧提示词文件。

## 测试边界

新增测试覆盖取消后已有结果保留、重复收尾、未知调用不得成功、整轮取消不得成功、模型错误不得伪装成功、跨请求消息不得串用、同轮来源、追加来源后摘要稳定、来源篡改、跨账号拒绝、抓拍时间用途隔离和提示词替换。

修复测试及插件回归 25 项通过。问答、表格、前端契约另有 29 项通过、16 项既有跳过。扩大原有回归出现 3 项失败，已在未修改基线复现：旧评分默认值断言 1 项；v6 夹具接口读/取消产生 OperationalError 2 项。它们未标记通过，也未为通过测试放宽代码。

没有调用真实供应方接口。确定性测试不能替代两个账号的完整浏览器与模型行为验收，部署与运行核查另见发布回执。

## 回退

恢复之前的 Control 镜像和匹配配置即可，新字段是可选快照字段；不覆盖数据库、不删除会话、来源或资料。Gateway、Agent 和前端静态资源本轮不变。
