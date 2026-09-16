# 沛警智枢终版前端与接口扩展改进说明

## 1. 文档目的

本文面向代码评审、分支合并和后续维护人员，说明 `peixian-ui-final` 分支相对基线 `origin/codex/generic-agent-platform` 的实际变更、设计边界、测试结论和未完成事项。

本分支以 12 张终版原型图和项目终版开发口径为依据，重点完成页面收敛、视觉重构、用户组织属性补充以及前端联调所需的接口骨架。公安业务数据适配、真实模型运行状态回写和正式证据链仍需后续后端开发。

## 2. 合并基线与范围

- 基线提交：`dff944188 feat(platform): deliver generic agent workbench and single-server package`
- 基线远程分支：`origin/codex/generic-agent-platform`
- 交付分支：`peixian-ui-final`
- 前端目录：`packages/peixian-console`
- 控制服务目录：`services/peixian-control`
- 项目专项文档目录：`specs/peixian-*.md`

本分支没有修改 OpenCode 通用 Session Core、SDK 生成代码或其他产品包；改动集中在沛县公安专用 Console 和 Control Service。

## 3. 页面与交互改进

### 3.1 登录页

- 按终版图 1 重构左右分栏、公安蓝配色、品牌标题、背景图和登录卡片。
- 只保留账号密码登录，删除短信、第三方认证等未纳入范围的入口。
- 支持记住账号、密码显隐、错误提示和重新连接。
- 登录后不再强制修改初始密码；个人改密和管理员重置密码接口仍保留。

### 3.2 民警端智能研判

- 左侧主导航只保留“智能研判”。
- 用户姓名、职务和退出入口移动至顶部右侧，左侧底部不再显示账号或主题切换。
- 历史区统一使用“研判记录”“新建研判”文案。
- 新建研判时对话主区域保持空白；已有消息继续使用通用 Markdown、工具执行详情和错误状态渲染。
- 对话顶部保留模型选择和“沉淀为 Skill”，删除省略号入口。
- 输入区只保留“能力、文件”，删除联网搜索和深度研判按钮。
- 保留 `/` 斜线能力选择：输入 `/` 或 `/关键字` 可筛选并选择 Skill、插件。
- 右侧只保留“相关插件技能”，汇总管理员开放能力、授权插件和个人 Skill；后端无数据时使用明确的前端 Mock 便于样式验收。
- 能力弹窗支持 Skill/插件筛选、选用以及个人 Skill 的编辑、测试和删除入口。
- Skill Creator 支持从需求或当前对话生成草稿、编辑、测试并保存为个人 Skill。
- 证据链使用抽屉展示，不展示已取消的“使用 Skill/插件”卡片。

### 3.3 管理端

- 左侧只保留“模型管理、用户与部门、调用审计”三个入口，页面切换完全通过左侧导航完成。
- 管理员信息移至顶部右侧，删除左侧底部账号区和明暗主题切换。
- 模型管理按图 9/10 重构列表、筛选、状态标签、操作区和新增/编辑弹窗。
- 用户与部门按图 11 重构汇总卡片、用户/部门切换、筛选、表格和编辑流程。
- 调用审计按图 12 重构组合筛选、表格、状态、详情和导出入口。
- 当接口无正式数据时使用页面 Mock，确保视觉评审不依赖后端数据准备。
- 插件管理、Skill 审核、Skill 中心、插件中心、我的智能体等旧入口不再出现在主导航。

## 4. 后端与数据模型改进

### 4.1 身份和组织属性

- 用户增加 `display_name`、`police_no`、`department_id`、`department`、`position`、`system_role`、`last_login_at`。
- 警务职务与系统角色分开保存；前者用于业务展示，后者用于权限判断。
- 登录成功和失败写入安全事件；失败响应统一为“账号或密码不正确”。
- 新建及重置密码不再设置首次登录强制改密标记，已有账号在服务初始化时归一化。

### 4.2 模型管理

- 模型增加 Provider、上下文长度、接入方式、工具调用支持、测试状态和更新时间。
- API Key 继续加密存储，响应只返回 `api_key_configured`。
- 连接测试以 OpenAI 兼容 `/models` 端点检查目标 Model ID。

### 4.3 新增联调接口

- 统一能力目录：`GET /capabilities`。
- Skill 草稿：`/skill-drafts/*`。
- 结构化运行、事件、证据、重跑和报告：`/sessions/{sid}/runs/{run_id}/*`。
- 部门维护：`/admin/departments/*`。
- 用户统计：`GET /admin/users/summary`。
- 官方能力配置：`/admin/capabilities/*`。
- 业务调用审计：`/admin/invocations/*`。

这些接口为前端联调提供了稳定数据形状，但运行事件完成状态、证据内容、报告格式和公安数据查询仍有 Mock 或占位实现，不能视为生产完成。

## 5. 安全和权限边界

- 浏览器会话使用 HttpOnly `px_session` Cookie；变更请求使用 `X-CSRF-Token`。
- 管理端接口继续在后端校验 capability，隐藏菜单不等同于权限控制。
- Session、Skill 草稿和运行记录按当前用户校验归属。
- 模型 API Key、公安凭据不得回显、写入审计或进入前端 Mock。
- 审计查询摘要只保存有限长度文本；生产接入前仍需完成公安业务字段分级脱敏。
- 当前前端 Mock 仅用于页面展示，正式环境必须由部署配置关闭或替换，不能混入正式研判结论。

## 6. 主要文件

| 文件 | 说明 |
| --- | --- |
| `packages/peixian-console/src/App.tsx` | 登录页、角色框架、导航和顶部用户区 |
| `packages/peixian-console/src/pages/Chat.tsx` | 研判页、能力选择、Skill Creator、右侧能力区和 `/` 选择 |
| `packages/peixian-console/src/pages/FinalAdmin.tsx` | 模型、用户部门、调用审计终版页面 |
| `packages/peixian-console/src/pages/CapabilityAdmin.tsx` | 隐藏能力配置页面基础实现 |
| `packages/peixian-console/src/styles.css` | 登录、民警端和管理端终版样式 |
| `services/peixian-control/control/final_platform.py` | 新增能力、草稿、运行、部门和调用审计接口 |
| `services/peixian-control/control/administration.py` | 用户组织属性和模型字段扩展 |
| `services/peixian-control/control/store.py` | 专项数据表和升级逻辑 |
| `services/peixian-control/docs/openapi.json` | 当前服务生成的 OpenAPI 快照 |

## 7. 验证结果

- 前端 TypeScript：`node_modules\.bin\tsc.cmd --noEmit`，通过。
- 前端生产构建：`node_modules\.bin\vite.cmd build`，通过。
- Control Service 全量测试：172 项通过、8 项跳过。
- Git 空白错误检查：`git diff --check`，通过。
- 本地服务健康检查：`GET /health` 和 Console 首页返回成功。

构建时存在仓库既有警告：根 `tsconfig.json` 引用的 `@tsconfig/bun/tsconfig.json` 在当前独立安装环境中未找到，但不阻止本包构建。

## 8. 合并注意事项

1. 建议整体合并专项前端、数据库迁移、接口实现、OpenAPI 和测试，避免只合并页面导致契约错位。
2. 若目标分支同期修改了 `App.tsx`、`styles.css` 或 Control Store schema，应人工解决冲突并重新运行专项测试。
3. `services/peixian-control/docs/openapi.json` 是生成结果；接口路由变更后应重新生成并检查差异。
4. 不要把 `tmp/peixian-manual-test`、本地数据库、日志、密码文件或测试凭据加入版本控制。
5. 正式环境上线前必须完成本文第 9 节事项。

## 9. 后续必做事项

- 将运行事件由当前初始记录改为 Runtime/工具执行实时回写，并补充 SSE 增量推送。
- 对接人员、关系、轨迹、场所、同行、车辆等正式公安数据适配器。
- 用真实证据记录替换证据链 Mock，并建立 `evidence_refs` 可追溯关系。
- 确认报告最终格式（Markdown、Word 或 PDF）并实现正式模板。
- 完成调用审计分页、Skill 条件筛选、详情脱敏和大数据量导出。
- 由部署环境提供正式模型、能力授权、部门树和用户初始化数据。
- 对照 `specs/peixian-api-gap-register.md` 将状态逐项更新为“正式联调完成”。
