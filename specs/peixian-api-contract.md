# 沛警智枢前后端接口契约（当前分支）

## 1. 通用约定

- API 前缀：`/api/console/v1`
- 数据格式：除文件上传、下载和 SSE 外均为 JSON。
- 时间字段：当前实现主要为 Unix 秒级时间戳。
- 浏览器鉴权：登录后由服务设置 HttpOnly Cookie `px_session`。
- CSRF：登录和 `GET/HEAD` 以外的请求携带响应中的 `csrf_token`，请求头为 `X-CSRF-Token`。
- 列表响应：统一使用 `{ "items": [] }`，部分管理接口同时返回 `total` 或 `capacity`。
- 错误响应：`{ "message": "用户可读提示", "code": "可选错误码", "request_id": "可选追踪号" }`。
- 常用状态码：`400` 参数错误、`401` 未登录、`403` 无权限、`404` 不存在或不属于当前用户、`409` 状态冲突、`413` 内容过大、`422` 校验错误、`429` 登录限流、`500` 内部错误。

以下路径均省略 `/api/console/v1` 前缀。

## 2. 认证与当前用户

### 2.1 登录

`POST /auth/login`

```json
{
  "username": "320722099",
  "password": "用户密码"
}
```

成功响应：

```json
{
  "user": {
    "id": "user-id",
    "username": "320722099",
    "role": "user",
    "system_role": "user",
    "display_name": "张警官",
    "police_no": "320722099",
    "department_id": "department-id",
    "department": "刑警大队",
    "position": "民警",
    "active": true,
    "last_login_at": 1789550000,
    "runtime": { "status": "ready" }
  },
  "csrf_token": "csrf-token",
  "capabilities": ["business.use"]
}
```

登录失败不得区分账号不存在、密码错误或账号停用。

### 2.2 当前用户和退出

- `GET /me`：返回与登录相同的认证对象。
- `POST /auth/logout`：返回 `{ "ok": true }` 并清除 Cookie。
- `POST /me/password`：请求 `{ "current_password": "...", "password": "..." }`。该接口用于主动改密，不再作为登录后强制步骤。

## 3. 会话、消息和文件

### 3.1 会话

- `GET /sessions`
- `POST /sessions`，请求 `{ "title": "新建研判" }`
- `PATCH /sessions/{sid}`，请求 `{ "title": "新的标题" }`
- `DELETE /sessions/{sid}`
- `GET /sessions/{sid}/messages`
- `POST /sessions/{sid}/abort`

### 3.2 提交消息

`POST /sessions/{sid}/messages`

```json
{
  "text": "查询并研判目标人员近期活动情况",
  "model_id": "model-id",
  "skill_ids": ["skill-id"],
  "file_ids": ["file-id"]
}
```

当前前端固定使用标准模式；后端仍兼容请求头 `X-Analysis-Mode: standard | deep_research`。每次最多选择 5 个 Skill 和 5 个文件，合计输入需满足服务端引用预算。

成功响应为 HTTP 202：

```json
{
  "accepted": true,
  "run_id": "run-id"
}
```

说明：当前接口只接受个人 Skill ID。右侧官方 Skill/插件的真实执行映射仍需后端补齐，前端 Mock 选择不能视为已经接入 Runtime。

### 3.3 文件

- `GET /files`
- `POST /files`：`multipart/form-data`，字段名 `file`，请求上限 21 MiB。
- `GET /files/{fid}/preview`
- `GET /files/{fid}/download`
- `DELETE /files/{fid}`

只有 `ready` 或 `partial` 文件可被选择；消息引用时 `partial/truncated` 文件会被拒绝，要求拆分后重新上传。

## 4. 模型和能力目录

### 4.1 用户可用模型

`GET /models`

```json
{
  "items": [
    {
      "id": "model-id",
      "name": "Qwen3-32B",
      "description": "研判模型",
      "is_default": true
    }
  ]
}
```

### 4.2 统一能力目录

`GET /capabilities?query=夜间&kind=skill`

- `query`：可选，按名称和描述模糊匹配。
- `kind`：可选，`skill` 或 `plugin`。

```json
{
  "items": [
    {
      "id": "capability-id",
      "kind": "skill",
      "name": "人员夜间活动分析",
      "description": "分析夜间活动规律",
      "version": "1.0",
      "category": "个人能力",
      "recommended": false,
      "enabled": true,
      "owned": true,
      "scope": "personal"
    }
  ]
}
```

目录聚合个人 Skill、授权插件和已启用的官方能力。后端必须按当前用户权限过滤。

## 5. Skill 草稿和个人 Skill

### 5.1 创建草稿

`POST /skill-drafts/from-requirement`

```json
{
  "requirement": "分析目标人员近 30 天夜间活动",
  "name": "人员夜间活动分析",
  "dependency_ids": ["plugin-id"],
  "input_schema": { "target": { "type": "string" } },
  "default_rules": ["夜间范围 22:00-06:00"]
}
```

`POST /skill-drafts/from-session`

```json
{
  "session_id": "session-id",
  "summary": "提炼当前研判方法",
  "dependency_ids": ["plugin-id"]
}
```

从会话生成时必须校验会话归属。当前实现根据需求生成结构化模板，后续应替换为受控模型提炼。

### 5.2 草稿维护

- `GET /skill-drafts/{id}`
- `PATCH /skill-drafts/{id}`
- `POST /skill-drafts/{id}/test`
- `POST /skill-drafts/{id}/save`

PATCH 可修改字段：`name`、`description`、`content`、`dependency_ids`、`input_schema`、`default_rules`。

草稿响应核心字段：

```json
{
  "id": "draft-id",
  "session_id": "session-id",
  "source_type": "requirement",
  "name": "人员夜间活动分析",
  "description": "...",
  "content": "# SKILL.md 内容",
  "dependency_ids": [],
  "input_schema": {},
  "default_rules": [],
  "created": 1789550000,
  "updated": 1789550000
}
```

保存后生成 `scope=personal` 的个人 Skill 并删除草稿。

### 5.3 个人 Skill

- `GET /skills`
- `POST /skills`
- `PATCH /skills/{sid}`
- `DELETE /skills/{sid}`
- `POST /skills/{sid}/test`
- `POST /skills/{sid}/rollback`

用户只能操作自己的 Skill。

## 6. 研判运行和证据

- `GET /sessions/{sid}/runs/{run_id}`：运行概要。
- `GET /sessions/{sid}/runs/{run_id}/events`：结构化步骤历史。
- `GET /sessions/{sid}/runs/{run_id}/evidence`：证据链。
- `POST /sessions/{sid}/runs/{run_id}/rerun`：按新条件创建关联运行。
- `GET /sessions/{sid}/runs/{run_id}/report`：当前导出 Markdown。

事件字段：

```json
{
  "sequence": 1,
  "step_type": "requirement",
  "name": "需求理解",
  "status": "completed",
  "started": 1789550000,
  "completed": 1789550001,
  "input_summary": null,
  "output_summary": "已识别研判目标",
  "record_count": 0,
  "error": null,
  "evidence_refs": []
}
```

`step_type` 使用 `requirement`、`skill`、`plugin`、`analysis`、`result`。不得返回模型内部思维过程。

当前证据响应带 `mock: true`，正式数据接入后应返回核心结论、轨迹、场所、同行人员、分析链条、查询条件和可追溯证据引用。

## 7. 管理端模型

- `GET /admin/models`
- `POST /admin/models`
- `PATCH /admin/models/{mid}`
- `POST /admin/models/{mid}/test`

新增/编辑请求：

```json
{
  "name": "Qwen3-32B-Instruct",
  "provider": "阿里云",
  "model_id": "qwen3-32b-instruct",
  "base_url": "https://example.internal/v1",
  "api_key": "只写不读",
  "description": "通义千问指令模型",
  "context_length": 131072,
  "access_mode": "api",
  "supports_tools": true,
  "enabled": true,
  "is_default": false
}
```

响应返回 `api_key_configured`，绝不返回 API Key。编辑时不提交 `api_key` 表示保留旧密钥。

## 8. 管理端用户和部门

### 8.1 用户

`GET /admin/users` 支持查询参数：`query`、`department_id`、`position`、`system_role`、`status=enabled|disabled`。

- `POST /admin/users`
- `PATCH /admin/users/{uid}`
- `POST /admin/users/{uid}/reset-password`
- `GET /admin/users/summary`

用户新增请求核心字段：

```json
{
  "username": "320722099",
  "password": "可选初始密码",
  "role": "user",
  "display_name": "张警官",
  "police_no": "320722099",
  "department_id": "department-id",
  "position": "民警",
  "model_ids": ["model-id"],
  "plugin_ids": ["plugin-id"]
}
```

`role/system_role` 控制系统权限，`position` 只表示警务职务。PATCH 不允许修改角色。新建和重置密码的响应只在当前请求中返回一次明文密码，调用端不得记录。

### 8.2 部门

- `GET /admin/departments/tree`
- `POST /admin/departments`
- `PATCH /admin/departments/{id}`
- `DELETE /admin/departments/{id}`

部门写入字段：`name`、`parent_id`、`code`、`sort_order`。存在下级部门或用户时删除返回 HTTP 409，不级联删除。

## 9. 官方能力配置

- `GET /admin/capabilities`
- `POST /admin/capabilities`
- `PATCH /admin/capabilities/{id}`
- `POST /admin/capabilities/{id}/test`

请求字段：`kind=skill|plugin`、`name`、`description`、`version`、`category`、`dependency_ids`、`visibility`、`enabled`、`config`。

当前 `/test` 只做配置结构和启用状态检查；真实连通和功能测试需要后端继续实现。配置中的敏感字段必须改为只写存储，不能使用当前通用 `config` 原样返回机制承载密钥。

## 10. 调用审计

- `GET /admin/invocations`
- `GET /admin/invocations/{id}`
- `GET /admin/invocations/export`

列表和导出支持：`uid`、`department_id`、`model_id`、`status`、`start`、`end`。当前列表上限 500 条，正式版本应增加分页和 Skill 筛选。

详情关联 `session_id`、`run_id`、模型、Skill、插件、执行步骤、查询摘要、记录数、耗时和错误。不得写入密码、Cookie、CSRF、API Key、完整身份证号、完整电话号码、业务原文或模型内部思维过程。

## 11. 公安业务工具统一契约（待正式适配）

前端不直接调用公安数据源，由后端工具适配层统一鉴权、限流、超时、脱敏和审计。建议所有工具归一化为：

```json
{
  "data": [],
  "record_count": 0,
  "source": "service-id",
  "queried_at": 1789550000,
  "trace_id": "trace-id",
  "mock": false,
  "error": null
}
```

人员、家庭关系、轨迹、涉案和涉警数据优先接入；场所、同行和车辆可在开发环境返回同结构且 `mock=true` 的数据。生产环境未配置正式 Provider 时必须明确不可用，不能静默回退 Mock。
