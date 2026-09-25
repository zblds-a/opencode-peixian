# 盗窃助手唯一提示词入口修订

## 实现
- 官方配置3.3.0升级3.4.0，唯一绑定theft_prompt.md；删除theft_dialogue_prompt.md及隐藏覆盖入口。
- 新Run冻结query_rules_version=on-demand-v1，不写入adaptive-dialogue-v1。旧标识仅保留历史执行恢复兼容。
- 取消强制八项计划、查满才答复和自动候选补查。保留由人到案/由案到人方向说明。
- source_selection=explicit；不自动选择中心或补500米。capture_scope_version=capture-purpose-v1单独保存抓拍用途条件。
- clarification_completion_version=clarification-completion-v1独立保留取消后汇总已有结果；历史adaptive执行仍可恢复。
- 不恢复个人嫌疑评分和排序。旧结果、旧报告及评分历史不重新计算。
- 新资料终稿使用既有person-tables-v3结构协议，平台渲染人员基本信息/研判摘要/分析依据/下一步研判；问候及缺项问题保持自然对话。
- 新布局版本theft-four-sections-v1，修复模型建议未进入Markdown问题；最多3项，query建议限定当前允许工具。

## 接口增量
既有/api/console/v1路径不变，无数据库迁移。
GET /agents和/agents/{id}增加可选prompt_resource、prompt_sha256；运行任务agent_profile同样包含prompt_resource。资源值仅theft_prompt.md，不是服务器路径。
Result V2 answer_view可选layout_version=theft-four-sections-v1，旧结果不增加该字段。version仍person-tables-v3；原有客户端继续读取兼容Markdown。
执行快照保留agent_profile版本和文件SHA、effective_system_prompt_sha256；新查询规则和独立恢复版本均冻结在加密快照。幂等重放不重新解释。

## 状态与验证
候选构建及上线验收记录见release.json和验收回执。Mock不等于真实供应方验收。
实际候选镜像定向回归74通过23跳过；23个跳过用例不算通过。首次OpenAPI字段遗漏已修复；受理夹具改为真实set_state终态保存后通过。
扩展旧双Agent/受控回答回归31失败60通过；未修改线上基线复测为相同31项失败/60项通过，失败不得记为通过。
浏览器工具初始化失败，页面交互尚未执行。

## 回退
恢复发布前Control不可变镜像及匹配compose/platform配置；不恢复旧数据库覆盖新增数据。无schema变化。
重建Control后重新连接原账号management网络；repair_only等待账号recovery_required清零，再normal等待ready/open。保留数据卷、会话、问答及文件。
不修改Gateway自动允许配置，不覆盖用户编辑Skill，不推送GitHub。
