# 沛警智枢简要使用与人工测试说明

## 1 当前启动信息

- 访问地址：<http://127.0.0.1:14090>
- 当前进程 PID：`37540`
- 初始管理员账号：`admin`
- 初始管理员密码：由本地 `ADMIN_PASSWORD_FILE` 提供，不写入仓库
- 用户端测试账号：`320722099`
- 用户端初始密码：由管理员创建或重置后一次性提供，不写入仓库
- 用户展示身份：`张警官 / 刑警大队 / 民警`
- 测试数据目录：`tmp/peixian-manual-test/data`
- 标准输出：`tmp/peixian-manual-test/server.stdout.log`
- 错误日志：`tmp/peixian-manual-test/server.stderr.log`

登录后直接进入对应工作台，不再执行首次登录强制修改密码。需要修改密码时，可由管理员重置或通过后续提供的个人账号功能主动修改。

当前实例使用独立本地测试数据库，不读取或修改正式环境数据。请勿在此实例录入真实公安业务数据、正式 API Key 或其他生产凭据。

## 2 管理端测试流程

### 2.1 登录和框架

1. 使用上述管理员账号登录。
2. 检查登录后直接进入管理端，不出现强制修改密码页面。
3. 检查左侧只显示“模型管理、用户与部门、调用审计”，不应出现插件管理、Skill 审核等旧入口。
4. 检查退出登录、重新登录、错误密码提示和页面刷新后的登录状态。

### 2.2 模型管理

进入“系统管理 → 模型管理”：

1. 新增模型，填写名称、Provider、Model ID、Base URL、API Key、上下文长度等字段。
2. 检查列表是否展示 Provider、接入方式、状态和更新时间。
3. 编辑模型并切换启停、默认模型和工具调用支持状态。
4. 使用“测试”检查连接结果。未配置可访问的模型服务时，连接失败属于预期结果。
5. 返回编辑弹窗，确认 API Key 不会以明文回显。

### 2.3 用户与部门

进入“系统管理 → 用户与部门”：

1. 先打开部门管理，新增上级部门和下级部门。
2. 新增普通用户，分别填写账号、姓名、警号、部门、警务职务和系统权限。
3. 检查警务职务与系统权限是否为两个独立字段。
4. 编辑用户，测试启用和禁用。
5. 测试管理员重置密码，确认普通用户可使用重置后的密码直接登录。
6. 尝试删除仍包含用户或下级部门的部门，应收到冲突提示且数据不会被级联删除。

### 2.4 隐藏能力配置

后端已提供 `/admin/capabilities` 接口，前端也保留了隐藏能力配置页面基础组件，但本轮终版管理框架没有在主导航或头像菜单中暴露该入口。待产品方确认最终入口后再进行页面联调；不要恢复插件市场、Skill 审核和发布审批流程。

### 2.5 调用审计

进入“系统管理 → 调用审计”：

1. 检查时间、用户、部门、模型、Skill、状态和查询摘要列。
2. 使用“导出”下载 CSV。
3. 本地实例尚未完成真实业务调用时，列表为空属于正常情况。

## 3 民警端测试流程

管理员创建的普通用户只有在账号 Runtime 被宿主执行器部署并进入 `ready` 状态后，才能完整测试会话、文件、模型调用和中止任务。

本轮用于前端样式核验的用户端账号可直接登录，不要求首次修改密码。其 Runtime 当前为 `pending`，可核验登录页、用户端框架、历史研判区、空白对话区、输入区、右侧能力区和能力弹窗等前端样式；涉及真实会话、文件、模型及公安数据的操作仍需等待宿主 Worker 和相关后端服务就绪。

Runtime 就绪后按以下顺序测试：

1. 登录后确认主导航只保留“智能研判”。
2. 新建、切换、重命名和删除历史研判。
3. 切换模型，输入研判问题并发送。
4. 检查输入区只保留“能力、文件”，不存在联网搜索和深度研判。
5. 打开能力弹窗，按全部、分析 Skill、插件工具筛选和搜索。
6. 选择“创建 Skill”，分别测试“从需求创建”和“从当前对话生成”。
7. 编辑 Skill 名称、使用场景和 `SKILL.md`，测试后保存。
8. 在能力弹窗内编辑、测试和删除个人 Skill，确认没有独立“我的 Skill”页面。
9. 发送消息后检查研判执行过程、报告导出和“研判依据 / 证据链”抽屉。
10. 在输入框输入 `/`，确认能够搜索和选择 Skill/插件。
11. 确认证据链中没有“使用 Skill / 插件”卡片。

当前独立开发进程没有启动宿主 Worker、用户 Gateway 和模型服务。因此普通用户可能显示“环境尚未就绪”，会话和文件请求不可用；这是部署依赖未启动，不是前端路由故障。公安场所、同行和车辆证据目前为明确标识的 Mock 数据契约。

## 4 建议验收清单

| 检查项 | 预期结果 |
| --- | --- |
| 登录页 | 只有账号、密码登录 |
| 废弃入口 | 我的智能体、Skill/插件中心、插件管理、Skill 审核均不可见 |
| 管理导航 | 只有模型管理、用户与部门、调用审计 |
| 能力配置 | 主导航不显示；后端接口和页面基础组件待确认入口后联调 |
| 职务与权限 | `position` 与 `system_role` 独立维护 |
| 密钥 | API Key 和其他凭据不回显明文 |
| 部门删除 | 存在用户或子部门时拒绝删除 |
| 个人 Skill | 在能力弹窗内创建、编辑、测试和删除 |
| 研判输入区 | 只有能力、文件，不含联网搜索和深度研判；输入 `/` 可选择能力 |
| 证据链 | 不展示“使用 Skill / 插件”区域，Mock 数据有明确提示 |

## 5 进程管理

停止当前实例：

```powershell
Stop-Process -Id 37540
```

重新启动时，在 PowerShell 中执行：

```powershell
$env:CONTROL_DATA = 'H:\Projects\opencode-peixian\tmp\peixian-manual-test\data'
$env:CONTROL_KEY_FILE = 'H:\Projects\opencode-peixian\tmp\peixian-manual-test\control-key'
$env:WORKER_KEY_FILE = 'H:\Projects\opencode-peixian\tmp\peixian-manual-test\worker-key'
$env:ADMIN_PASSWORD_FILE = 'H:\Projects\opencode-peixian\tmp\peixian-manual-test\admin-password'
$env:CONSOLE_STATIC = 'H:\Projects\opencode-peixian\packages\peixian-console\dist'
$env:CONSOLE_ORIGINS = 'http://127.0.0.1:14090,http://localhost:14090'
Set-Location 'H:\Projects\opencode-peixian\services\peixian-control'
& 'C:\Users\13952\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m uvicorn control.app:app --host 127.0.0.1 --port 14090 --workers 1 --no-access-log
```

前端代码有修改时，先在 `packages/peixian-console` 目录运行 `node_modules\.bin\vite.cmd build`，再重启后端。

## 6 问题记录

人工测试发现的问题建议同时记录：页面、账号角色、操作步骤、预期结果、实际结果、截图、浏览器版本和发生时间。接口完成度及正式数据依赖以 [接口对齐记录](./peixian-api-gap-register.md) 为准。
