# 沛警智枢分支合并与前后端联调说明

## 1. 适用对象

本文供原项目开发人员执行代码评审、分支合并、本地启动、接口替换和联合验收。接口字段以 `peixian-api-contract.md` 和 `services/peixian-control/docs/openapi.json` 为准；需求目标以 `peixian-backend-requirements.md` 为准。

## 2. 推荐合并方式

```bash
git fetch origin peixian-ui-final
git switch codex/generic-agent-platform
git switch -c peixian-merge-review
git merge --no-ff origin/peixian-ui-final
```

如果目标开发分支已经包含基线后的其他提交，建议先在临时评审分支合并并重点检查：

- `packages/peixian-console/src/App.tsx`
- `packages/peixian-console/src/pages/Chat.tsx`
- `packages/peixian-console/src/styles.css`
- `services/peixian-control/control/store.py`
- `services/peixian-control/control/administration.py`
- `services/peixian-control/control/app.py`

不要只复制编译后的 `dist`；本分支不提交前端构建产物，部署时由流水线构建。

## 3. 开发环境准备

### 3.1 前端

在 `packages/peixian-console` 中使用仓库既有依赖：

```powershell
node_modules\.bin\tsc.cmd --noEmit
node_modules\.bin\vite.cmd build
```

若重新安装依赖，优先遵循仓库锁文件和 Bun 工作区流程。不要在仓库根目录运行测试。

### 3.2 Control Service

Control Service 需要可写数据目录、控制密钥、Worker 密钥、管理员密码文件和前端静态目录：

```powershell
$env:CONTROL_DATA = '<独立测试数据目录>'
$env:CONTROL_KEY_FILE = '<控制密钥文件>'
$env:WORKER_KEY_FILE = '<Worker 密钥文件>'
$env:ADMIN_PASSWORD_FILE = '<管理员密码文件>'
$env:CONSOLE_STATIC = '<仓库>\packages\peixian-console\dist'
$env:CONSOLE_ORIGINS = 'http://127.0.0.1:14090,http://localhost:14090'
python -m uvicorn control.app:app --host 127.0.0.1 --port 14090 --workers 1
```

测试目录必须与生产数据隔离，不要复制本地测试数据库或密码文件到 Git。

## 4. 联调顺序

### 阶段 A：认证和页面框架

1. 调用 `POST /auth/login`，保存 HttpOnly Cookie 和响应 `csrf_token`。
2. 调用 `GET /me`，确认姓名、警号、部门、职务和系统角色完整。
3. 使用普通用户验证只能进入智能研判；使用管理员验证只能看到模型管理、用户与部门、调用审计三个入口。
4. 检查禁用用户、错误密码、退出和越权接口。

完成标准：无需强制改密即可进入工作台，前端路由隐藏与后端 403 同时生效。

### 阶段 B：模型、部门和用户

1. 建立部门树。
2. 新增模型并执行连接测试。
3. 新增普通用户，同时分配部门、模型和必要插件。
4. 确认警务职务 `position` 与系统权限 `system_role` 不混用。
5. 确认 API Key 只返回 `api_key_configured`。

完成标准：普通用户 `GET /models` 能看到至少一个启用模型，Runtime 能进入 `ready`。

### 阶段 C：会话、文件和能力

1. 验证会话新建、列表、改名和删除。
2. 验证文件上传、解析状态、预览、下载和删除。
3. 调用 `GET /capabilities`，确认结果只包含当前用户可用能力。
4. 验证右侧能力列表、能力弹窗和 `/` 筛选使用同一目录契约。
5. 使用两种来源创建 Skill 草稿，完成编辑、测试、保存和个人 Skill 删除。

完成标准：不依赖前端 Mock 也能完成目录和 Skill Creator 基础流程。

### 阶段 D：运行、证据和审计

1. `POST /sessions/{sid}/messages` 获取 `run_id`。
2. 轮询或订阅运行事件，并由 Runtime/工具执行回写步骤状态。
3. 证据接口返回真实记录、来源、时间和 `trace_id`。
4. 报告引用相同 `run_id` 和证据引用。
5. 管理端调用审计可按用户、部门、模型、Skill、状态和时间查询并导出。

完成标准：一次真实研判能从消息请求追溯到运行、步骤、证据、报告和审计记录。

## 5. 前端 Mock 替换规则

当前前端在模型、会话和能力接口返回空列表时提供演示数据，用于无后端环境下的页面验收。联调时必须注意：

- 非空正式列表会覆盖对应 Mock。
- Mock ID 使用 `mock-` 前缀，不应发送到正式后端。
- Mock 历史记录不提供改名和删除操作。
- 右侧能力选中仅验证前端交互；官方 Skill/插件尚未全部映射到消息提交和 Runtime 工具调用。
- 联调完成后建议引入显式构建开关，例如 `VITE_ENABLE_DEMO_DATA=false`，生产构建强制关闭 Mock，而不是依赖“空列表时回退”。

## 6. Runtime 对接要求

- 用户必须具有已部署 Runtime/Gateway，状态为 `ready` 才能发送真实消息和上传文件。
- `POST /sessions/{sid}/messages` 当前把个人 Skill 内容和文件文本作为受控前置内容发送到 Runtime。
- 后端必须校验会话、文件、Skill 和运行记录均属于当前用户。
- Runtime 完成、失败、取消和超时必须回写 `runs`、`run_events` 和 `invocations`。
- 事件只返回执行事实和摘要，不返回 Chain-of-Thought。

建议回写状态：

| 对象 | 状态 |
| --- | --- |
| Run | `accepted`、`running`、`completed`、`failed`、`cancelled`、`timeout` |
| Step | `pending`、`running`、`completed`、`skipped`、`failed` |
| Invocation | 与 Run 对齐，并补充 `duration_ms`、`record_count`、`error` |

## 7. 公安数据适配

1. 前端禁止直接调用公安数据源。
2. 每个适配器统一处理凭据、超时、重试、限流、字段映射、脱敏和审计。
3. 工具返回采用 `data/record_count/source/queried_at/trace_id/mock/error` 契约。
4. 每条证据分配稳定引用 ID，写入运行事件的 `evidence_refs`。
5. 上游错误只向前端返回可读摘要，详细错误写受控日志并关联 `trace_id`。
6. Mock 只能在开发环境启用，并显式返回 `mock=true`。

## 8. 联调测试矩阵

| 模块 | 正常场景 | 异常场景 |
| --- | --- | --- |
| 登录 | 普通用户、管理员登录和退出 | 错误密码、禁用账号、限流、Cookie 失效 |
| 权限 | 用户访问研判、管理员访问管理接口 | 用户直接请求 `/admin/*` 返回 403 |
| 模型 | 新增、编辑、测试、默认切换、启停 | 地址非法、密钥错误、Model ID 不存在 |
| 用户部门 | 新增、筛选、编辑、重置密码 | 重复警号、部门不存在、删除非空部门 |
| 会话 | 新建、恢复、改名、删除、中止 | 非本人会话、Runtime 不可用 |
| 文件 | 上传、解析、引用、下载 | 超限、部分解析、跨用户访问 |
| 能力 | 搜索、分类、个人隔离、官方分发 | 停用能力、依赖停用、越权访问 |
| Skill Creator | 两种来源、编辑、测试、保存 | 同名、空内容、非本人会话/草稿 |
| 运行证据 | 状态回放、证据关联、报告 | 失败、取消、超时、刷新恢复 |
| 审计 | 组合筛选、详情、CSV | 敏感字段泄漏、大数据量导出 |

## 9. 提交前检查

```powershell
git diff --check
Set-Location packages\peixian-console
node_modules\.bin\tsc.cmd --noEmit
node_modules\.bin\vite.cmd build
Set-Location ..\..\services\peixian-control
python -m pytest -q
```

后端测试必须从 `services/peixian-control` 执行；不要从仓库根目录运行。

## 10. 当前已知限制

- 自动浏览器视觉核验通道在最后一轮出现本地浏览器策略加载错误；代码已构建通过，最终像素级验收仍需人工浏览器检查。
- 当前运行步骤只在接收消息时创建初始记录，尚未接收真实 Runtime 逐步回写。
- 证据链和 Markdown 报告仍为联调占位实现。
- 官方 Skill 和插件选择到 Runtime 的完整执行映射尚未完成。
- 调用审计列表尚无正式分页，Skill 筛选和大数据量导出需要补齐。
- `CapabilityAdmin.tsx` 提供隐藏能力配置基础，但本轮最终主导航和路由未暴露该页面；是否保留管理员头像菜单入口需产品方再次确认。

## 11. 交付文档索引

- `specs/peixian-change-summary.md`：实际改动和合并注意事项。
- `specs/peixian-api-contract.md`：当前代码可用接口契约。
- `specs/peixian-integration-guide.md`：合并、启动和联调步骤。
- `specs/peixian-backend-requirements.md`：正式后端建设目标。
- `specs/peixian-api-gap-register.md`：接口状态台账。
- `specs/peixian-frontend-development-plan.md`：页面范围和阶段计划。
- `specs/peixian-manual-test-guide.md`：人工验收操作说明。
