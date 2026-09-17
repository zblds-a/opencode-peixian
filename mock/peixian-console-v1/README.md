# 沛警智枢 Mock 数据包使用说明

## 1. 用途

本数据包汇总 `peixian-ui-final` 分支终版前端当前使用的全部演示/回退数据，并补充了让数据可以独立运行所需的登录、平台、运行事件和空列表响应。

这里的“全部 Mock”指当前终版产品页面可见或接口联调所需的 Mock 数据；不包含仓库单元测试中的 `MockTransport`、压力测试合成流量、历史旧控制台页面 Fixture 或基准测试结果文件，这些内容不参与当前前端展示，也不应交给业务接口作为响应样例。

适用场景：

- 前端页面和交互的离线视觉验收。
- 后端按接口逐项对照字段、枚举和响应外壳。
- 使用 curl、Postman 或自动化测试模拟接口响应。
- 在正式公安数据接口未接通时进行前后端联调。

不适用场景：

- 性能、并发、权限或安全验收。
- 验证真实模型、公安业务接口、文件解析和审计落库。
- 生产部署或作为正式业务数据导入。

数据均为人工合成信息，不包含真实密码、API Key、Cookie、业务凭证或未经脱敏的公安数据。

## 2. 版本基线

| 项目 | 值 |
| --- | --- |
| 仓库 | `https://github.com/zblds-a/opencode-peixian.git` |
| 分支 | `peixian-ui-final` |
| 提取基线 | `b7cf3e2aa` |
| API 基础路径 | `/api/console/v1` |
| 结构化结果 | `peixian.analysis-result@1.0` |
| 默认 Mock 服务端口 | `127.0.0.1:14090` |
| 前端开发端口 | `127.0.0.1:5178` |

## 3. 目录结构

```text
peixian-console-v1/
├─ README.md
├─ manifest.json
├─ mock_server.py
├─ api/
│  ├─ platform.json
│  ├─ auth-user.json
│  ├─ auth-admin.json
│  ├─ models.json
│  ├─ sessions.json
│  ├─ capabilities.json
│  ├─ messages-structured.json
│  ├─ messages-markdown.json
│  ├─ files-empty.json
│  ├─ skills-empty.json
│  ├─ run-events.json
│  ├─ run-evidence.json
│  ├─ admin-models.json
│  ├─ admin-departments-tree.json
│  ├─ admin-users.json
│  ├─ admin-users-summary.json
│  ├─ admin-invocations.json
│  └─ operation-responses.json
└─ schemas/
   └─ analysis-result.schema.json
```

`manifest.json` 是机器可读索引，说明每个文件对应的接口、用途和数据条数。

## 4. 数据分类

### 4.1 当前 UI 实际回退数据

以下数据逐项提取自当前前端源码，接口返回为空或不可用时页面会回退展示：

| 数据文件 | 当前源码变量 | 页面 |
| --- | --- | --- |
| `models.json` | `Chat.tsx` 的 `mockModels` | 用户端模型选择 |
| `sessions.json` | `Chat.tsx` 的 `mockSessions` | 用户端研判历史 |
| `capabilities.json` | `Chat.tsx` 的 `mockCapabilities` | 右侧插件技能、能力弹窗、斜线菜单 |
| `messages-structured.json` | `mockAnalysisMessages` + `mockAnalysisResult` | 结构化研判结果和智能线索 |
| `messages-markdown.json` | 普通 Mock 会话回复 | 普通 Markdown 对话 |
| `admin-models.json` | `FinalAdmin.tsx` 的 `mockModels` | 模型管理 |
| `admin-departments-tree.json` | `mockDepartments` | 部门管理 |
| `admin-users.json` | `mockUsers` | 用户管理 |
| `admin-users-summary.json` | `userSummary` 回退值 | 用户汇总卡片 |
| `admin-invocations.json` | `mockInvocations` | 调用审计 |

### 4.2 契约补全数据

这些文件不是额外产品功能，而是为了让包可以独立模拟接口：

- `platform.json`、`auth-user.json`、`auth-admin.json`：登录并进入用户端或管理端。
- `run-events.json`：运行步骤的完整示例。
- `files-empty.json`、`skills-empty.json`：当前 UI 没有对应实体 Mock，显式提供真实空列表。
- `operation-responses.json`：列表操作按钮的请求/响应参考。
- `analysis-result.schema.json`：结构化研判结果的 JSON Schema。

### 4.3 当前后端兜底数据

`run-evidence.json` 对应控制服务在正式业务数据未接通时返回的证据链兜底内容，明确包含 `"mock": true`。

## 5. 最快使用方式：启动随包 Mock 服务

要求：Python 3.10 或更高版本；脚本只使用标准库，不需要安装依赖。

在解压后的数据包目录执行：

```powershell
python .\mock_server.py
```

看到以下输出即表示启动成功：

```text
Peixian Mock API: http://127.0.0.1:14090/api/console/v1
```

前端 `packages/peixian-console/vite.config.ts` 已将 `/api` 代理到 `http://127.0.0.1:14090`。另开终端启动前端：

```powershell
cd packages\peixian-console
npm install
npm run dev
```

浏览器访问：

```text
http://127.0.0.1:5178
```

Mock 登录规则仅用于本地开发：

| 入口 | 账号 | 密码 |
| --- | --- | --- |
| 管理端 | `admin` | 任意非空字符串 |
| 用户端 | 除 `admin` 外任意非空账号，例如 `320722001` | 任意非空字符串 |

Mock 服务不会保存密码，也不会验证真实身份。不要在共享或公网环境开放该端口。

### 5.1 端口冲突

正式控制服务默认也可能占用 `14090`。启动 Mock 前应先停止本机正式控制服务，禁止让两个服务同时争用端口。

如需改端口，需要同时修改 `mock_server.py` 中的监听端口和前端 `vite.config.ts` 的代理目标；这类改动仅用于本地，不应提交为生产配置。

### 5.2 Mock 服务的行为边界

- GET 接口返回对应 JSON 文件。
- `admin` 登录返回管理员身份；其他账号返回普通用户身份。
- 创建会话、发送消息、测试、启停、禁用、重置密码等写操作只返回成功示例，不持久化。
- 用户端选择“张某夜间活动研判”会返回结构化结果；其他 Mock 会话返回普通 Markdown。
- `/events` 返回 HTTP 204，避免 EventSource 在纯 Mock 模式反复触发全量刷新。
- 文件上传、报告下载、真实 SSE、数据库写入和模型调用不在该轻量服务范围内。

## 6. 使用 curl 验证

### 6.1 平台信息

```powershell
curl.exe http://127.0.0.1:14090/api/console/v1/platform
```

### 6.2 用户登录并保存 Cookie

```powershell
curl.exe -c mock-cookie.txt -H "Content-Type: application/json" -d '{"username":"320722001","password":"demo"}' http://127.0.0.1:14090/api/console/v1/auth/login
curl.exe -b mock-cookie.txt http://127.0.0.1:14090/api/console/v1/me
```

### 6.3 管理员登录

```powershell
curl.exe -c mock-admin-cookie.txt -H "Content-Type: application/json" -d '{"username":"admin","password":"demo"}' http://127.0.0.1:14090/api/console/v1/auth/login
curl.exe -b mock-admin-cookie.txt http://127.0.0.1:14090/api/console/v1/admin/models
```

### 6.4 结构化消息

```powershell
curl.exe -b mock-cookie.txt http://127.0.0.1:14090/api/console/v1/sessions/mock-night/messages
```

### 6.5 调用审计

```powershell
curl.exe -b mock-admin-cookie.txt http://127.0.0.1:14090/api/console/v1/admin/invocations
```

Cookie 文件只是本地 Mock 测试产物，用完可删除，不要提交到仓库。

## 7. 后端直接使用 JSON 文件

后端可以不启动 `mock_server.py`，直接把 `api/*.json` 用作路由 Fixture。映射关系如下：

| 方法和路径 | 文件 |
| --- | --- |
| `GET /platform` | `platform.json` |
| `POST /auth/login`、`GET /me` | `auth-user.json` 或 `auth-admin.json` |
| `GET /models` | `models.json` |
| `GET /sessions` | `sessions.json` |
| `GET /capabilities` | `capabilities.json` |
| `GET /sessions/mock-night/messages` | `messages-structured.json` |
| `GET /sessions/{其他ID}/messages` | `messages-markdown.json` |
| `GET /files` | `files-empty.json` |
| `GET /skills` | `skills-empty.json` |
| `GET /sessions/{sid}/runs/{run_id}/events` | `run-events.json` |
| `GET /sessions/{sid}/runs/{run_id}/evidence` | `run-evidence.json` |
| `GET /admin/models` | `admin-models.json` |
| `GET /admin/departments/tree` | `admin-departments-tree.json` |
| `GET /admin/users` | `admin-users.json` |
| `GET /admin/users/summary` | `admin-users-summary.json` |
| `GET /admin/invocations` | `admin-invocations.json` |

列表均使用 `{ items, total, page, page_size }` 外壳。当前前端最低只依赖 `items`，后端应保留完整分页字段，便于后续服务端分页。

## 8. 结构化研判数据说明

`messages-structured.json` 中第二条消息的第一个 Part 是特殊渲染数据：

```text
items[1].parts[0].type = "analysis_result"
items[1].parts[0].data.schema = "peixian.analysis-result"
items[1].parts[0].data.version = "1.0"
```

前端只有在三项均匹配时才进行特殊渲染。数据包括：

- `process`：5 个可审计研判步骤，不是模型隐藏思维链。
- `subjects`：1 个目标对象；允许为 0 个或多个，不包含人物照片。
- `conclusions`：4 条核心结论。
- `evidence`：轨迹、同行、车辆、高频地点四类卡片；前端最多展示前四项。
- `next_steps`：按普通文本展示。
- `clues`：4 条智能线索，支持人员、车辆、地点和轨迹类型。
- 每条线索含摘要、核心发现和证据列表，可打开右侧详情抽屉。

允许把数组改为 `[]` 测试空状态；不得返回 `null`。未知 evidence/clue 类型会使用通用样式。字段限制以 `schemas/analysis-result.schema.json` 为准。

## 9. 当前前端何时自动使用 Mock

当前代码中的回退规则是：

| 页面 | 回退条件 |
| --- | --- |
| 用户端模型 | `/models` 无条目 |
| 研判历史 | `/sessions` 无条目 |
| 插件技能 | `/capabilities` 无条目 |
| 管理模型 | `/admin/models` 无条目 |
| 用户 | `/admin/users` 条目不超过 1 条 |
| 部门 | `/admin/departments/tree` 无条目 |
| 汇总 | `summary.users` 为 0 |
| 调用审计 | `/admin/invocations` 无条目 |

注意：这种“空数据自动回退”只适合当前视觉验收。正式联调和生产环境必须关闭，真实空数组应展示空状态，不得显示合成数据。建议后续使用显式的 `VITE_ENABLE_DEMO_DATA=true|false` 控制，并在生产构建强制为 `false`。

## 10. 操作按钮的 Mock 说明

- 模型“测试”在 Mock 行上直接提示成功。
- 模型“启用/关停”只更新当前浏览器内存，刷新后恢复原 Fixture。
- 用户“编辑、重置密码、禁用”对 Mock 行只演示交互；禁用仅更新内存。
- `operation-responses.json` 提供正式后端应返回的最小结构参考。
- 自动生成的临时密码不能固化在 Fixture、日志或代码中；正式接口应运行时生成并只返回一次。

## 11. 修改和重新打包

1. 只修改 `api/*.json`，保持字段类型与接口契约一致。
2. 修改结构化结果后，用 Schema 校验。
3. 同步更新 `manifest.json` 的版本、条目数和说明。
4. 不要加入真实账号、密码、身份证、手机号、地址、Cookie、密钥或业务原始响应。
5. 从 `mock` 目录重新生成 ZIP：

```powershell
Compress-Archive -Path .\peixian-console-v1 -DestinationPath .\peixian-console-mock-data-v1.zip -Force
```

## 12. 校验方法

校验所有 JSON 可解析：

```powershell
Get-ChildItem .\peixian-console-v1 -Recurse -Filter *.json | ForEach-Object {
  Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json | Out-Null
  Write-Host "OK" $_.FullName
}
```

校验 Mock 服务脚本：

```powershell
python -m py_compile .\peixian-console-v1\mock_server.py
```

查看 ZIP 内容：

```powershell
tar -tf .\peixian-console-mock-data-v1.zip
```

## 13. 正式联调替换顺序

1. 登录、当前用户和权限。
2. 用户模型、会话和普通 Markdown 消息。
3. 能力目录和文件。
4. `analysis_result@1.0` 结构化消息。
5. Run 事件、证据和刷新恢复。
6. 管理模型、用户部门、调用审计。
7. 最后关闭全部自动回退 Mock，验证真实空状态、失败、超时、取消和越权。

正式接口与 Mock 不一致时，应先更新 OpenAPI、结构化 Schema 和前后端交接文档，再升级本数据包版本。
