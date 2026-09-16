"""Offline OpenAPI contract for the console's deliberately restricted API.

The route table remains the authority. This module only documents routes; it
never initializes the database, reads deployment secrets, or contacts runtimes.
"""
from copy import deepcopy

from fastapi.openapi.utils import get_openapi

P = "/api/console/v1"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
ID = {"type": "string", "minLength": 1, "maxLength": 100, "pattern": "^[A-Za-z0-9_-]+$"}
STRING = {"type": "string"}
BOOL = {"type": "boolean"}
INTEGER = {"type": "integer"}
FLAG = {"anyOf": [BOOL, {"type": "integer", "enum": [0, 1]}]}
PASSWORD = {"type": "string", "minLength": 12, "maxLength": 256, "format": "password", "writeOnly": True}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def array(item, **kwargs):
    return {"type": "array", "items": item, **kwargs}


def obj(properties, required=(), *, extra=False, **kwargs):
    result = {"type": "object", "properties": properties, "additionalProperties": extra, **kwargs}
    if required:
        result["required"] = list(required)
    return result


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def items(schema):
    return obj({"items": array(schema)}, ("items",), extra=True)


def schemas():
    ids = array(ID, maxItems=100)
    skill_fields = {
        "name": {"type": "string", "minLength": 1, "maxLength": 60,
                 "pattern": r"^[^/\\\r\n\u0000]+$"},
        "description": {"type": "string", "maxLength": 500},
        "content": {"type": "string", "minLength": 1, "maxLength": 32000},
        "enabled": BOOL,
        "source_type": {"type": "string", "enum": ["manual", "requirement", "conversation"]},
        "dependency_ids": array(ID, maxItems=100),
        "input_schema": {"type": "object", "additionalProperties": True},
        "default_rules": array(STRING),
        "scope": {"type": "string", "enum": ["personal"]},
    }
    model_fields = {
        "name": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": "string", "maxLength": 500},
        "base_url": {"type": "string", "format": "uri", "maxLength": 500,
                     "description": "管理员配置的 HTTP/HTTPS OpenAI 兼容接口基地址；不得包含 URL 用户信息、查询或片段。"},
        "model_id": {"type": "string", "minLength": 1, "maxLength": 500,
                     "description": "上游服务实际模型 ID；与普通用户选择的平台模型 ID 不同。"},
        "api_key": {"type": "string", "format": "password", "writeOnly": True,
                    "description": "仅写入；更新时省略或空字符串保留原凭据。允许无鉴权的内网模型。"},
        "enabled": BOOL, "is_default": BOOL, "provider": STRING,
        "context_length": {"type": "integer", "minimum": 1},
        "access_mode": {"type": "string", "enum": ["api", "local"]},
        "supports_tools": BOOL,
    }
    template_fields = {k: skill_fields[k] for k in ("name", "description", "content")}
    file_states = {"type": "string", "enum": ["uploading", "queued", "parsing", "ready", "partial", "no_text", "unsupported", "failed"]}
    result = {
        "Error": obj({"message": STRING, "code": STRING, "request_id": STRING}, ("message", "code")),
        "Ok": obj({"ok": BOOL}, ("ok",), extra=True),
        "Health": obj({"status": STRING, "version": STRING, "schema_version": {"type": "integer", "const": 3}}, ("status", "version", "schema_version")),
        "LoginBody": obj({"username": STRING, "password": {"type": "string", "format": "password", "writeOnly": True}}, ("username", "password")),
        "PasswordBody": obj({"current_password": {"type": "string", "format": "password", "writeOnly": True}, "password": PASSWORD}, ("current_password", "password")),
        "TokenBody": obj({"name": {"type": "string", "maxLength": 80}}),
        "SessionBody": obj({"title": {"type": "string", "maxLength": 200}}),
        "MessageBody": obj({
            "text": {"type": "string", "minLength": 1, "maxLength": 32000, "pattern": r"\S",
                     "description": "非空白问题。文字、选中技能内容与文件文本合计还受 18000 UTF-8 字节预算限制。"},
            "model_id": {**ID, "description": "GET /models 返回的已授权平台模型 ID；省略时选择授权列表中的默认模型。"},
            "skill_ids": array(ID, maxItems=5),
            "file_ids": {**array(ID, maxItems=5), "description": "本账号已解析为 ready 且未截断的上传文件 ID；partial 或 truncated=true 返回 413，要求拆分后重新上传；不接受文件路径或 URL。"},
        }, ("text",)),
        "SkillCreateBody": obj(skill_fields, ("name", "content")),
        "SkillUpdateBody": obj(skill_fields),
        "PluginInstallBody": obj({
            "version": {"type": "string", "description": "管理员发布的可用版本；省略时选择最新发布的可用版本。"},
            "enabled": BOOL,
            "config": {"type": "object", "additionalProperties": True,
                       "description": "必须满足该发布版本的 config_schema；密码字段留空或省略可保留原值。"},
        }),
        "UserCreateBody": obj({
            "username": {"type": "string", "minLength": 3, "maxLength": 40, "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$"},
            "password": {**PASSWORD, "description": "省略时生成初始密码，仅在本次响应返回；首次登录必须修改。"},
            "role": {"type": "string", "enum": ["user", "admin"], "default": "user", "description": "仅超管可提交此字段；admin 操作者即使提交 role=user 也返回403。创建的管理员账号不创建业务环境且不得携带任何授权字段。"},
            "model_ids": ids, "plugin_ids": ids,
            "display_name": STRING, "police_no": STRING,
            "department_id": nullable(ID), "position": STRING,
        }, ("username",)),
        "UserUpdateBody": obj({"active": BOOL, "model_ids": ids, "plugin_ids": ids,
                               "display_name": STRING, "police_no": STRING,
                               "department_id": nullable(ID), "position": STRING}),
        "PasswordResetBody": obj({"password": {**PASSWORD, "description": "省略时生成新初始密码。撤销旧认证并要求修改。"}}),
        "ModelCreateBody": obj(model_fields, ("name", "base_url", "model_id")),
        "ModelUpdateBody": obj(model_fields),
        "PluginStateBody": obj({"enabled": BOOL}, ("enabled",)),
        "TemplateCreateBody": obj(template_fields, ("name", "content")),
        "TemplateUpdateBody": obj(template_fields),
        "PermissionReplyBody": obj({
            "reply": {"type": "string", "enum": ["once", "reject"]},
            "answers": array(array(STRING)),
            "message": STRING,
        }, ("reply",)),
        "QuestionReplyBody": obj({
            "reply": STRING, "answers": array(array(STRING)), "message": STRING,
        }, ("answers",)),
        "QuestionRejectBody": obj({"reply": STRING, "answers": array(array(STRING)), "message": STRING}),
        "FileUploadBody": obj({"file": {"type": "string", "format": "binary",
                                      "description": "一个原始文件，最大 20 MiB。"}}, ("file",)),
        "PluginUploadBody": obj({"file": {"type": "string", "format": "binary",
                                        "description": "管理员审核的 ZIP 包，含 manifest.json 与打包好的 .mjs 入口；最大 20 MiB。"}}, ("file",)),
        "Runtime": obj({"id": ID, "status": {"type": "string", "enum": ["pending", "provisioning", "updating", "ready", "paused", "failed"]},
                        "revision": INTEGER, "desired": INTEGER, "error": nullable(STRING)},
                       ("status",), extra=True, description="普通管理员查看他人环境只返回 status；不返回内部运行环境 ID、配置修订或错误详情。"),
        "User": obj({"id": ID, "username": STRING, "role": {"type": "string", "enum": ["user", "admin", "super_admin"]},
                     "active": BOOL, "must_change_password": BOOL, "runtime": nullable(ref("Runtime")),
                     "model_ids": ids, "plugin_ids": ids, "display_name": STRING, "police_no": nullable(STRING),
                     "department_id": nullable(ID), "department": nullable(obj({"id": ID, "name": STRING, "code": nullable(STRING)}, ("id", "name"))),
                     "position": STRING, "system_role": {"type": "string", "enum": ["user", "admin", "super_admin"]},
                     "last_login_at": nullable(INTEGER)},
                    ("id", "username", "role", "active", "must_change_password", "runtime"), extra=True),
        "Identity": obj({"user": ref("User"), "csrf_token": nullable(STRING),
                         "capabilities": array({"type": "string", "enum": ["users.manage", "admins.manage", "models.manage", "audit.read", "plugins.manage", "templates.manage", "runtimes.manage", "jobs.read", "business.use"]})},
                        ("user", "csrf_token", "capabilities")),
        "Token": obj({"id": ID, "name": STRING, "created": INTEGER, "expires": INTEGER}, ("id", "name", "created", "expires")),
        "TokenCreated": obj({"token": {"type": "string", "description": "只在创建响应返回一次；作为 Bearer 使用，不得写入日志。"},
                             "item": ref("Token")}, ("token", "item")),
        "Job": obj({"id": nullable(ID), "uid": ID, "action": STRING, "status": STRING,
                    "revision": INTEGER, "error": nullable(STRING), "created": INTEGER, "updated": INTEGER},
                   ("status",), extra=True, description="普通管理员由账号或模型变更触发的后台任务仅返回 status，不授予独立任务管理权限。"),
        "Queued": obj({"ok": BOOL, "id": ID, "job": nullable(ref("Job"))}, ("job",), extra=True),
        "UserChanged": obj({"user": ref("User"), "job": nullable(ref("Job")),
                            "password": {"type": "string", "description": "仅创建响应提供的初始密码；不持久化到客户端日志。"}},
                           ("user", "job")),
        "PasswordReset": obj({"password": {"type": "string", "description": "新初始密码；仅本次响应返回。"}}, ("password",)),
        "Model": obj({"id": ID, "name": STRING, "description": STRING, "is_default": FLAG}, ("id", "name", "description", "is_default")),
        "AdminModel": obj({**{k: v for k, v in model_fields.items() if k != "api_key"},
                           "id": ID, "enabled": FLAG, "is_default": FLAG, "api_key_configured": BOOL,
                           "test_status": STRING, "updated_at": nullable(INTEGER)},
                          ("id", "name", "description", "base_url", "model_id", "enabled", "is_default", "api_key_configured")),
        "ModelChanged": obj({"model": ref("AdminModel"), "jobs": array(ref("Job"))}, ("model", "jobs")),
        "Session": obj({"id": ID, "title": STRING, "time": {"type": "object", "additionalProperties": True},
                        "parentID": ID, "status": STRING}, ("id",), extra=True),
        "ScalarMap": {"type": "object", "maxProperties": 20,
                      "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_]{0,59}$"},
                      "additionalProperties": {"anyOf": [{"type": "string", "maxLength": 300},
                                                          {"type": "number"}, BOOL]},
                      "description": "管理员批准展示且经过过滤的标量字段；值仅为文字、数字、布尔，不含数组、对象或 null。"},
        "CredentialState": {"type": "object",
                            "additionalProperties": {"anyOf": [BOOL, ref("CredentialState")]},
                            "description": "按嵌套配置字段组织的布尔状态树；只表明是否已配置，不含凭据值。"},
        "Message": obj({
            "info": obj({"id": ID, "role": STRING, "time": {"type": "object", "additionalProperties": True},
                         "sessionID": ID, "finish": STRING, "error": obj({"message": STRING}, ("message",))}, extra=True),
            "parts": array(obj({"id": ID, "type": {"type": "string", "enum": ["text", "tool"]},
                                "sessionID": ID, "messageID": ID, "text": STRING, "tool": STRING,
                                "state": obj({"status": STRING, "title": STRING}, extra=True),
                                "details": obj({"inputs": ref("ScalarMap"), "outputs": ref("ScalarMap")}, ("inputs", "outputs"))}, extra=True)),
        }, ("info", "parts")),
        "MessageAccepted": obj({"accepted": {"type": "boolean", "const": True}, "run_id": ID}, ("accepted", "run_id")),
        "Skill": obj({**skill_fields, "id": ID, "enabled": FLAG, "version": INTEGER, "job": ref("Job")},
                     ("id", "name", "description", "content", "enabled", "version")),
        "Template": obj({**template_fields, "id": ID}, ("id", "name", "content")),
        "Plugin": obj({
            "id": ID, "version": STRING, "name": STRING, "description": STRING, "versions": array(STRING),
            "config_schema": {"type": "object", "additionalProperties": True,
                              "description": "最新可用发布版本的表单 schema。"},
            "schemas": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": True},
                        "description": "可用版本号到该版本表单 schema 的映射；编辑时选择对应版本，不能一律使用最新 schema。"},
            "installed": nullable(obj({"version": STRING, "enabled": BOOL, "config": {"type": "object"},
                                       "credentials_configured": ref("CredentialState"),
                                       "state": {"type": "string", "enum": ["active", "pending", "unavailable"]}},
                                      ("version", "enabled", "config", "credentials_configured", "state"))),
        }, ("id", "version", "name", "description", "versions", "config_schema", "schemas", "installed")),
        "AdminPlugin": obj({"id": ID, "version": STRING, "name": STRING, "description": STRING, "digest": STRING, "enabled": FLAG},
                           ("id", "version"), extra=True),
        "ConnectionTest": obj({"ok": BOOL, "message": STRING, "supported": BOOL, "connection_tested": BOOL},
                              ("ok", "message")),
        "File": obj({"id": ID, "name": STRING, "extension": STRING, "size": {"type": "integer", "minimum": 0},
                     "status": file_states, "created_at": {"type": "string", "format": "date-time"},
                     "updated_at": {"type": "string", "format": "date-time"}, "truncated": BOOL,
                     "error": nullable(STRING), "warnings": array(STRING)},
                    ("id", "name", "size", "status", "truncated"), extra=True),
        "TextChunk": obj({"text": STRING, "source": {"type": "object", "additionalProperties": True,
                          "description": "解析器来源标注，例如行号、工作表/表格及行号、PDF 页码或 DOCX 段落号；不是绝对路径。"}},
                         ("text", "source")),
        "FileText": obj({"text": STRING, "chunks": array(ref("TextChunk")), "truncated": BOOL, "status": file_states, "name": STRING},
                        ("text", "chunks", "truncated", "status", "name")),
        "Result": obj({"id": ID, "name": STRING, "relative_path": STRING, "size": INTEGER,
                       "modified_at": {"type": "string", "format": "date-time"}},
                      ("id", "name", "relative_path", "size", "modified_at")),
        "Confirmation": obj({"id": ID, "sessionID": ID, "questions": array({"type": "object", "additionalProperties": True}),
                             "description": STRING}, ("id", "sessionID", "questions", "description")),
        "Audit": obj({"id": ID, "actor": STRING, "actor_role": STRING, "action": STRING, "target": STRING,
                      "result": {"type": "string", "enum": ["success", "denied", "failed"]},
                      "created": INTEGER, "username": nullable(STRING)},
                     ("id", "actor", "actor_role", "action", "target", "result", "created", "username")),
        "LeaseBody": obj({"lease": {"type": "string", "writeOnly": True}}, ("lease",)),
        "CompleteBody": obj({"lease": {"type": "string", "writeOnly": True}, "ok": BOOL, "deferred": BOOL,
                             "error": STRING, "rolled_back": BOOL, "cleanup_confirmed": BOOL}, ("lease",)),
        "LegacyImportBody": obj({
            "username": STRING, "password": PASSWORD, "model_ids": ids,
            "legacy": obj({"home_volume": STRING, "workspace_volume": STRING}, ("home_volume", "workspace_volume"),
                          description="仅允许执行器预登记并实际核验的固定旧卷组合；禁止任意路径或卷。"),
            "snapshot": obj({"id": ID, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, ("id", "sha256")),
        }, ("username", "password", "legacy", "snapshot")),
        "LegacyRollbackBody": obj({"uid": ID, "snapshot_id": ID, "cleanup_confirmed": {"type": "boolean", "const": True}},
                                  ("uid", "snapshot_id", "cleanup_confirmed")),
        "LegacyRetryBody": obj({
            "uid": ID, "snapshot_id": ID,
            "legacy_stopped": {"type": "boolean", "const": True,
                               "description": "可信执行器已实际核验对应旧环境停止；不是普通用户可声明的生命周期操作。"},
        }, ("uid", "snapshot_id", "legacy_stopped")),
        "LegacyRetryResult": obj({"uid": ID, "runtime_id": ID,
                                  "status": {"type": "string", "enum": ["provisioning", "ready"]},
                                  "revision": INTEGER, "desired": INTEGER, "job_id": ID},
                                 ("uid", "runtime_id", "status", "revision", "desired", "job_id")),
        "WorkerClaim": obj({
            "job": nullable(obj({"id": ID, "uid": ID, "action": STRING, "lease": STRING, "revision": INTEGER},
                                ("id", "uid", "action", "lease", "revision"))),
            "spec": {"type": "object", "additionalProperties": True,
                     "description": "敏感执行器配置快照，可能含运行凭据；仅可信宿主 Worker 接收，不得交给业务客户端或日志。"},
        }, ("job",)),
        "LegacyStatus": obj({"uid": ID, "runtime_id": ID, "created": BOOL, "status": STRING,
                             "revision": INTEGER, "desired": INTEGER, "reserved": BOOL}, ("uid", "runtime_id", "status"), extra=True),
    }
    result["UserList"] = obj({"items": array(ref("User")), "total": INTEGER, "capacity": obj({"maximum": INTEGER, "reserved": INTEGER}, ("maximum", "reserved"))}, ("items", "capacity"))
    result["ResultList"] = obj({"items": array(ref("Result")), "truncated": BOOL}, ("items", "truncated"))
    connection_fields = {
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "base_url": {"type": "string", "format": "uri", "maxLength": 1000},
        "auth_type": {"type": "string", "enum": ["none", "bearer", "api_key"], "default": "none"},
        "secret": {"type": "string", "format": "password", "writeOnly": True, "maxLength": 4096,
                   "description": "不回显；鉴权方式及头名未变时，省略或空串保留旧值。修改鉴权方式须重新填写，none 清除旧值。"},
        "header_name": STRING, "enabled": BOOL,
        "allowed_methods": array({"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, minItems=1, maxItems=5),
        "allowed_paths": array({"type": "string", "description": "精确路径或末尾 /* 前缀匹配；不接受转义、查询、片段和目录跳转。"}, minItems=1, maxItems=100),
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60, "default": 15},
        "max_response_bytes": {"type": "integer", "minimum": 1024, "maximum": 10485760, "default": 1048576},
    }
    result["Platform"] = obj({"name": STRING, "short_name": STRING, "description": STRING}, ("name", "short_name", "description"))
    result["ServiceConnectionCreate"] = obj(connection_fields, ("name", "base_url"))
    result["ServiceConnectionUpdate"] = obj(connection_fields)
    result["ServiceConnection"] = obj({**{k: v for k, v in connection_fields.items() if k != "secret"}, "id": ID, "secret_configured": BOOL, "revision": INTEGER}, ("id", "name", "base_url", "secret_configured", "revision"))
    result["ServiceConnectionChanged"] = obj({"connection": ref("ServiceConnection"), "jobs": array(ref("Job"))}, ("connection", "jobs"))
    result["ServiceRequest"] = obj({"method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                                    "path": STRING, "query": {"type": "object", "additionalProperties": {"type": ["string", "number", "boolean"]}}, "json": {}}, ("path",))
    result["ServiceTest"] = obj({"ok": BOOL, "message": STRING, "status": INTEGER}, ("ok", "message"))
    binding_map = {"type": "object", "additionalProperties": ID}
    alias_map = {"type": "object", "additionalProperties": obj({"description": STRING})}
    result["PluginBindingBody"] = obj({"bindings": binding_map}, ("bindings",))
    result["PluginBindings"] = obj({"bindings": binding_map, "aliases": alias_map, "jobs": array(ref("Job"))}, ("bindings", "aliases"))
    result["AdminPlugin"]["properties"]["connections"] = alias_map
    result["Plugin"]["properties"]["connection_status"] = {"type": "object", "additionalProperties": obj({"ready": BOOL, "missing": array(STRING)}, ("ready", "missing"))}
    installed = result["Plugin"]["properties"]["installed"]["anyOf"][0]["properties"]
    installed["missing_connections"] = array(STRING)
    installed["state"]["enum"].append("unconfigured")
    result["Capability"] = obj({"id": ID, "kind": {"type": "string", "enum": ["skill", "plugin"]},
                                "name": STRING, "description": STRING, "version": STRING, "category": STRING,
                                "recommended": BOOL, "enabled": BOOL, "owned": BOOL, "scope": STRING},
                               ("id", "kind", "name", "version", "category", "enabled", "owned", "scope"))
    result["SkillDraftCreate"] = obj({"session_id": ID, "requirement": STRING, "summary": STRING,
                                      "name": STRING, "description": STRING, "dependency_ids": ids,
                                      "input_schema": {"type": "object", "additionalProperties": True},
                                      "default_rules": array(STRING)})
    result["SkillDraftUpdate"] = obj({"name": STRING, "description": STRING, "content": STRING,
                                      "dependency_ids": ids, "input_schema": {"type": "object", "additionalProperties": True},
                                      "default_rules": array(STRING)})
    result["SkillDraft"] = obj({"id": ID, "session_id": nullable(ID), "source_type": STRING, "name": STRING,
                                "description": STRING, "content": STRING, "dependency_ids": ids,
                                "input_schema": {"type": "object", "additionalProperties": True},
                                "default_rules": array(STRING)}, ("id", "source_type", "name", "content"), extra=True)
    result["Run"] = obj({"id": ID, "session_id": ID, "model_id": nullable(ID), "query_summary": STRING,
                         "mode": STRING, "status": STRING, "started": INTEGER, "completed": nullable(INTEGER),
                         "error": nullable(STRING)}, ("id", "session_id", "status", "started"), extra=True)
    result["RunEvent"] = obj({"id": ID, "sequence": INTEGER, "step_type": STRING, "name": STRING,
                              "status": STRING, "started": nullable(INTEGER), "completed": nullable(INTEGER),
                              "input_summary": STRING, "output_summary": STRING, "record_count": nullable(INTEGER),
                              "error": nullable(STRING), "capability_id": nullable(ID), "evidence_refs": array(ID)},
                             ("id", "sequence", "step_type", "name", "status"), extra=True)
    result["Evidence"] = obj({"conclusion": {"type": "object", "additionalProperties": True},
                              "tabs": {"type": "object", "additionalProperties": True},
                              "chain": array({"type": "object", "additionalProperties": True}),
                              "conditions": {"type": "object", "additionalProperties": True}, "mock": BOOL},
                             ("conclusion", "tabs", "chain", "conditions"))
    result["RerunBody"] = obj({"query": STRING})
    result["DepartmentBody"] = obj({"name": STRING, "parent_id": nullable(ID), "code": nullable(STRING), "sort_order": INTEGER})
    result["Department"] = obj({"id": ID, "name": STRING, "parent_id": nullable(ID), "code": nullable(STRING),
                                "sort_order": INTEGER, "created": INTEGER, "updated": INTEGER}, ("id", "name"), extra=True)
    result["UsersSummary"] = obj({"users": INTEGER, "departments": INTEGER, "enabled": INTEGER}, ("users", "departments", "enabled"))
    result["AdminCapabilityBody"] = obj({"kind": {"type": "string", "enum": ["skill", "plugin"]},
                                         "name": STRING, "description": STRING, "version": STRING, "category": STRING,
                                         "dependency_ids": ids, "visibility": STRING, "enabled": BOOL,
                                         "config": {"type": "object", "additionalProperties": True}})
    result["AdminCapability"] = obj({"id": ID, "kind": STRING, "name": STRING, "description": STRING,
                                     "version": STRING, "category": STRING, "dependency_ids": ids,
                                     "visibility": STRING, "enabled": BOOL,
                                     "config": {"type": "object", "additionalProperties": True}},
                                    ("id", "kind", "name", "version", "enabled"), extra=True)
    result["Invocation"] = obj({"id": ID, "run_id": ID, "uid": ID, "status": STRING, "created": INTEGER,
                                "skill_ids": ids, "plugin_ids": ids, "query_summary": STRING},
                               ("id", "run_id", "uid", "status", "created"), extra=True)
    return result


# Keys are actual route suffixes (or the explicit expansion of an actual route).
# Response status comes from FastAPI's registered route, not a duplicate table.
CONTRACTS = {
    ("get", "/platform"): (None, ref("Platform"), "获取公开产品信息", "平台", "仅产品名称、简称与介绍，不包含部署标识、内部地址或任何凭据。"),
    ("get", "/admin/connections"): (None, items(ref("ServiceConnection")), "列出服务连接", "管理：连接", "仅超级管理员；凭据只返回 secret_configured。"),
    ("post", "/admin/connections"): ("ServiceConnectionCreate", ref("ServiceConnection"), "创建固定服务连接", "管理：连接", "配置鉴权、固定地址、方法及路径范围。"),
    ("patch", "/admin/connections/{cid}"): ("ServiceConnectionUpdate", ref("ServiceConnectionChanged"), "更新服务连接", "管理：连接", "新版本配置与受影响安装账号的应用任务在同一事务保存；不影响其他账号。"),
    ("delete", "/admin/connections/{cid}"): (None, ref("Ok"), "删除未绑定的服务连接", "管理：连接", "仍被插件版本引用时返回409；可先停用或解除绑定。"),
    ("post", "/admin/connections/{cid}/test"): ("ServiceRequest", ref("ServiceTest"), "测试固定服务连接", "管理：连接", "沿用出口相同的范围、超时与大小校验。只返回状态，不返回业务正文；默认使用已允许的GET路径，写方法测试由超级管理员明确提交。"),
    ("get", "/admin/plugins/{pid}/{version}/connections"): (None, ref("PluginBindings"), "查看插件版本连接绑定", "管理：连接", "别名由不可变发布清单声明，不能由普通用户配置。"),
    ("put", "/admin/plugins/{pid}/{version}/connections"): ("PluginBindingBody", ref("PluginBindings"), "保存插件版本连接绑定", "管理：连接", "完整替换此版本绑定并原子排队应用。未绑定或停用的必需连接使插件处于 unconfigured，停止在新配置中加载。"),
    ("post", "/auth/login"): ("LoginBody", ref("Identity"), "登录并获取 Cookie 与 CSRF", "登录", "校验允许的 Origin，成功设置 HttpOnly 的 px_session Cookie。初始密码用户只能查询自己、改密或退出。"),
    ("get", "/me"): (None, ref("Identity"), "获取当前身份及环境状态", "登录", "账号由有效认证绑定；Bearer 身份的 csrf_token 为 null。"),
    ("post", "/auth/logout"): (None, ref("Ok"), "撤销当前认证", "登录", "删除当前 Cookie 或 Bearer 认证记录；已建立的本身份事件连接也会关闭。"),
    ("post", "/me/password"): ("PasswordBody", ref("Ok"), "修改自己的密码", "登录", "撤销其他登录与令牌，保留本次认证。"),
    ("get", "/tokens"): (None, items(ref("Token")), "列出自己的访问令牌", "访问令牌", "只返回元数据，不返回原始令牌。"),
    ("post", "/tokens"): ("TokenBody", ref("TokenCreated"), "创建访问令牌", "访问令牌", "令牌有效期 30 天，原始值仅本次返回；权限与账号身份一致。"),
    ("delete", "/tokens/{tid}"): (None, ref("Ok"), "撤销自己的访问令牌", "访问令牌", "撤销后新请求被拒绝，使用该令牌的事件流关闭。"),
    ("get", "/models"): (None, items(ref("Model")), "列出本账号获授权模型", "模型", "不公开上游地址或模型密钥。"),
    ("get", "/capabilities"): (None, items(ref("Capability")), "列出当前用户可用能力", "能力", "聚合个人 Skill、已授权插件工具和管理员配置的官方能力。"),
    ("get", "/sessions"): (None, items(ref("Session")), "列出自己的会话", "会话", "仅固定工作区内的会话；同时返回 idle/busy 等状态。"),
    ("post", "/sessions"): ("SessionBody", ref("Session"), "创建空会话", "会话", "创建空会话本身不发起模型生成。"),
    ("patch", "/sessions/{sid}"): ("SessionBody", ref("Session"), "重命名自己的会话", "会话", ""),
    ("delete", "/sessions/{sid}"): (None, ref("Ok"), "删除自己的会话", "会话", ""),
    ("get", "/sessions/{sid}/messages"): (None, items(ref("Message")), "读取会话的已保存消息", "会话", "工具展示经过过滤，不返回原始内部配置或工具秘密。"),
    ("post", "/sessions/{sid}/messages"): ("MessageBody", ref("MessageAccepted"), "提交异步模型消息", "会话", "202 只表示已接受，run_id 不是结果查询资源。先订阅 events，收到变更后重新读取会话消息及状态。每次最多五个技能和五个文件；文件引用总计另限 24000 字符，合并文字/技能/文件另限 18000 UTF-8 字节。同一会话请串行提交。"),
    ("post", "/sessions/{sid}/abort"): (None, ref("Ok"), "终止自己的会话生成", "会话", ""),
    ("get", "/sessions/{sid}/runs/{run_id}"): (None, ref("Run"), "读取研判运行", "研判运行", "仅当前用户及所属会话。"),
    ("get", "/sessions/{sid}/runs/{run_id}/events"): (None, items(ref("RunEvent")), "读取结构化执行步骤", "研判运行", "不包含模型内部思维过程。"),
    ("get", "/sessions/{sid}/runs/{run_id}/evidence"): (None, ref("Evidence"), "读取研判依据与证据链", "研判运行", "业务接口未接通的标签明确返回 mock=true。"),
    ("post", "/sessions/{sid}/runs/{run_id}/rerun"): ("RerunBody", ref("MessageAccepted"), "按修改条件重新研判", "研判运行", "创建新的关联运行。"),
    ("get", "/sessions/{sid}/runs/{run_id}/report"): (None, None, "导出研判报告", "研判运行", "下载 Markdown 报告。"),
    ("get", "/events"): (None, None, "订阅本账号变更事件", "会话", "SSE 仅发送 event: change 与 data 中 type=connected/updated，另有 heartbeat 注释。不是模型文字增量；收到事件后查询 messages。连接持续检查认证，注销/撤销后关闭。"),
    ("get", "/files"): (None, items(ref("File")), "列出自己的上传文件", "文件", ""),
    ("post", "/files"): ("FileUploadBody", ref("File"), "上传文件并自动排队解析", "文件", "multipart/form-data 中唯一文件字段 file；单文件最大 20 MiB，每账号原始上传累计 1 GiB，实际字节计量。解析 TXT/MD/CSV/XLSX/文本 PDF/DOCX，无 OCR。202 后轮询 files 或 text；queued/parsing 尚未完成。"),
    ("get", "/files/{fid}/text"): (None, ref("FileText"), "读取文件解析文本及来源", "文件", "仅 ready 且未截断可用于模型引用；partial 或 truncated=true 的模型引用会返回 413，可在我的文件查看已提取范围并拆分后重新上传。no_text 表示无可提取文本，扫描件不会执行 OCR。"),
    ("get", "/files/{fid}/preview"): (None, ref("FileText"), "预览文件解析文本", "文件", "最多 20000 字符及 100 个来源块；截断由 truncated 标示。"),
    ("get", "/files/{fid}/download"): (None, None, "下载原始上传文件", "文件", "原始二进制内容；通过文件 ID 定位，不接受路径。"),
    ("delete", "/files/{fid}"): (None, ref("Ok"), "删除自己的上传文件", "文件", "上传或解析期间返回 409；删除成功释放原始上传配额。"),
    ("get", "/results"): (None, ref("ResultList"), "列出自己的可下载结果文件", "文件", "固定工作区内的显式非隐藏文件；relative_path 仅作展示，下载仍使用 id。"),
    ("get", "/results/{fid}/download"): (None, None, "下载自己的结果文件", "文件", ""),
    ("get", "/skills"): (None, items(ref("Skill")), "列出自己的技能", "技能", ""),
    ("post", "/skills"): ("SkillCreateBody", ref("Skill"), "创建自己的技能", "技能", "保存后返回配置应用任务；任务完成前不能假定技能已加载。"),
    ("patch", "/skills/{sid}"): ("SkillUpdateBody", ref("Queued"), "修改自己的技能", "技能", "保存历史并排队应用。"),
    ("delete", "/skills/{sid}"): (None, ref("Queued"), "删除自己的技能", "技能", "排队应用运行环境配置。"),
    ("post", "/skills/{sid}/rollback"): (None, ref("Queued"), "恢复自己的上一版技能", "技能", ""),
    ("post", "/skills/{sid}/test"): (None, ref("ConnectionTest"), "检查技能是否已经加载", "技能", "只核对当前环境是否加载技能，不发起模型效果评测。"),
    ("post", "/skill-drafts/from-requirement"): ("SkillDraftCreate", ref("SkillDraft"), "从需求创建 Skill 草稿", "Skill Creator", "创建当前用户私有草稿。"),
    ("post", "/skill-drafts/from-session"): ("SkillDraftCreate", ref("SkillDraft"), "从当前对话创建 Skill 草稿", "Skill Creator", "校验会话归属。"),
    ("get", "/skill-drafts/{draft_id}"): (None, ref("SkillDraft"), "读取 Skill 草稿", "Skill Creator", "仅草稿所有者。"),
    ("patch", "/skill-drafts/{draft_id}"): ("SkillDraftUpdate", ref("SkillDraft"), "编辑 Skill 草稿", "Skill Creator", ""),
    ("post", "/skill-drafts/{draft_id}/test"): (None, ref("ConnectionTest"), "测试 Skill 草稿", "Skill Creator", "返回结构和依赖校验结果。"),
    ("post", "/skill-drafts/{draft_id}/save"): (None, ref("Queued"), "保存为个人 Skill", "Skill Creator", "固定保存为 personal 范围。"),
    ("get", "/templates"): (None, items(ref("Template")), "列出管理员提供的技能模板", "技能", ""),
    ("post", "/templates/{tid}/copy"): (None, ref("Queued"), "复制模板为自己的技能", "技能", "返回新技能 id 与配置应用任务。"),
    ("get", "/plugins"): (None, items(ref("Plugin")), "列出已授权插件及自己的配置状态", "插件", "仅管理员发布且授权的插件；私密字段仅返回配置状态，不回显值。"),
    ("put", "/plugins/{pid}"): ("PluginInstallBody", ref("Queued"), "安装或配置已授权插件", "插件", "用户无法提交任意包或加载路径；参数校验依赖版本 config_schema。保存后排队应用。"),
    ("post", "/plugins/{pid}/rollback"): (None, ref("Queued"), "恢复自己上一版插件配置", "插件", "目标版本必须仍获授权且启用。"),
    ("post", "/plugins/{pid}/test"): (None, ref("ConnectionTest"), "执行插件提供的连接测试", "插件", "配置尚未应用时 connection_tested=false。已应用时调用管理员包的 test 导出；supported=false 表示不提供连接测试，不代表连接成功。"),
    ("get", "/permissions"): (None, items(ref("Confirmation")), "列出自己的待确认权限", "确认", ""),
    ("get", "/questions"): (None, items(ref("Confirmation")), "列出自己的待回答问题", "确认", ""),
    ("post", "/permissions/{rid}/reply"): ("PermissionReplyBody", BOOL, "允许本次操作或拒绝权限请求", "确认", "只允许 once/reject；拒绝也使用本 reply 路径。"),
    ("post", "/questions/{rid}/reply"): ("QuestionReplyBody", BOOL, "回答模型问题", "确认", "answers 按问题顺序排列，每题为选项字符串数组。"),
    ("post", "/questions/{rid}/reject"): ("QuestionRejectBody", BOOL, "拒绝回答模型问题", "确认", "仍需 JSON 对象请求体，可传空对象。"),
    ("get", "/admin/users"): (None, ref("UserList"), "列出账号与环境名额", "管理：账号", ""),
    ("get", "/admin/users/summary"): (None, ref("UsersSummary"), "读取用户与部门汇总", "管理：账号", ""),
    ("get", "/admin/departments/tree"): (None, items(ref("Department")), "读取部门树", "管理：部门", ""),
    ("post", "/admin/departments"): ("DepartmentBody", ref("Department"), "新增部门", "管理：部门", ""),
    ("patch", "/admin/departments/{department_id}"): ("DepartmentBody", ref("Department"), "编辑部门", "管理：部门", ""),
    ("delete", "/admin/departments/{department_id}"): (None, ref("Ok"), "删除空部门", "管理：部门", "存在用户或下级部门时返回409。"),
    ("post", "/admin/users"): ("UserCreateBody", ref("UserChanged"), "创建普通用户或管理员", "管理：账号", "super_admin 可创建 user/admin；admin 只能创建 user，且不得提交 role 或 plugin_ids，即使值为 user 或空数组。角色默认 user。创建 user 时账号、初始授权与开通任务在同一事务保存；202 不代表环境已就绪。创建 admin 不接受 model_ids/plugin_ids，不创建环境，runtime 与 job 均为 null。未知字段或混合越权字段整笔拒绝。"),
    ("patch", "/admin/users/{uid}"): ("UserUpdateBody", ref("UserChanged"), "修改账号启用状态或授权", "管理：账号", "admin 只能管理全部 user 的 active/model_ids，不得携带 plugin_ids。super_admin 另可管理 user 的插件授权及 admin 的 active；admin 账号不接受模型/插件授权。角色不可更改，super_admin 账号不能作为此接口目标。停用立即撤销认证；user 同事务排队停止环境，admin 无环境任务。原已停用 user 重新启用会同事务预留容量并排队 resume；容量不足或暂停任务仍在途返回409，账号仍停用。已启用但被超管手动暂停的账号不会因重复启用或修改授权自动恢复。混合越权字段整笔拒绝。"),
    ("post", "/admin/users/{uid}/reset-password"): ("PasswordResetBody", ref("PasswordReset"), "重设账号初始密码", "管理：账号", ""),
    ("post", "/admin/users/{uid}/runtime/{action}"): (None, ref("Queued"), "排队执行环境操作", "管理：账号", "pause 保留数据并停止环境；resume 恢复；retry 重试开通；apply 应用当前授权配置。"),
    ("get", "/admin/jobs"): (None, items(ref("Job")), "查看最近环境任务", "管理：审计", "最多最近 200 项。"),
    ("get", "/admin/audit"): (None, items(ref("Audit")), "查看最近管理审计", "管理：审计", "最多最近 500 项。actor 为账号 ID 精确筛选，action 为管理动作精确筛选，result 为 success/denied/failed。仅管理操作元数据；不包含业务调用、迁移负载、密钥、正文或文件路径。"),
    ("get", "/admin/invocations"): (None, items(ref("Invocation")), "查询业务调用审计", "管理：调用审计", "可按用户、部门、模型、状态和时间筛选。"),
    ("get", "/admin/invocations/export"): (None, None, "导出调用审计", "管理：调用审计", "按当前筛选条件导出 CSV。"),
    ("get", "/admin/invocations/{invocation_id}"): (None, ref("Invocation"), "查看调用审计详情", "管理：调用审计", "包含可审计步骤，不包含内部思维过程和敏感原文。"),
    ("get", "/admin/models"): (None, items(ref("AdminModel")), "列出模型配置", "管理：模型", "返回 api_key_configured，不返回密钥值。"),
    ("post", "/admin/models"): ("ModelCreateBody", ref("AdminModel"), "新增可授权模型", "管理：模型", ""),
    ("patch", "/admin/models/{mid}"): ("ModelUpdateBody", ref("ModelChanged"), "修改模型并排队应用", "管理：模型", ""),
    ("post", "/admin/models/{mid}/test"): (None, ref("ConnectionTest"), "检查模型列表接口与模型 ID", "管理：模型", "读取上游 models，不生成聊天回复；不等同于工具调用能力验收。"),
    ("get", "/admin/capabilities"): (None, items(ref("AdminCapability")), "列出官方能力配置", "管理：能力", "仅超级管理员隐藏入口。"),
    ("post", "/admin/capabilities"): ("AdminCapabilityBody", ref("AdminCapability"), "新增官方能力", "管理：能力", ""),
    ("patch", "/admin/capabilities/{capability_id}"): ("AdminCapabilityBody", ref("AdminCapability"), "编辑官方能力", "管理：能力", ""),
    ("post", "/admin/capabilities/{capability_id}/test"): (None, ref("ConnectionTest"), "测试官方能力配置", "管理：能力", "不返回业务正文或凭据。"),
    ("get", "/admin/plugins"): (None, items(ref("AdminPlugin")), "列出已发布插件版本", "管理：插件", ""),
    ("post", "/admin/plugins"): ("PluginUploadBody", ref("AdminPlugin"), "发布经过管理员审核的插件包", "管理：插件", "版本不可覆盖。ZIP 需安全路径、最多 1000 项、解压最多 100 MiB；加载的代码具有该账号环境内代码执行能力，Skill 指令本身不是安全隔离边界。"),
    ("patch", "/admin/plugins/{pid}/{version}"): ("PluginStateBody", ref("Ok"), "启用或停用插件版本", "管理：插件", "相关账号会排队应用配置。"),
    ("get", "/admin/templates"): (None, items(ref("Template")), "列出技能模板", "管理：模板", ""),
    ("post", "/admin/templates"): ("TemplateCreateBody", ref("Template"), "新增技能模板", "管理：模板", ""),
    ("patch", "/admin/templates/{tid}"): ("TemplateUpdateBody", ref("Template"), "修改技能模板", "管理：模板", ""),
    ("delete", "/admin/templates/{tid}"): (None, ref("Ok"), "删除技能模板", "管理：模板", ""),
}

WORKER_CONTRACTS = {
    ("get", "/internal/worker/busy"): (None, obj({"busy": BOOL}, ("busy",))),
    ("post", "/internal/worker/claim"): (None, ref("WorkerClaim")),
    ("post", "/internal/worker/jobs/{jid}/heartbeat"): ("LeaseBody", ref("Ok")),
    ("post", "/internal/worker/jobs/{jid}/complete"): ("CompleteBody", ref("Ok")),
    ("post", "/internal/worker/legacy-import"): ("LegacyImportBody", ref("LegacyStatus")),
    ("get", "/internal/worker/legacy-status/{uid}"): (None, ref("LegacyStatus")),
    ("post", "/internal/worker/legacy-rollback"): ("LegacyRollbackBody", ref("LegacyStatus")),
    ("post", "/internal/worker/legacy-retry"): ("LegacyRetryBody", ref("LegacyRetryResult")),
    ("get", "/internal/worker/packages/{sha}"): (None, None),
}


def expand_routes(document):
    expansions = {
        P + "/files/{fid}/{action}": [
            (P + "/files/{fid}/" + action, {"action": action}) for action in ("preview", "text", "download")],
        P + "/{kind}": [(P + "/" + kind, {"kind": kind}) for kind in ("permissions", "questions")],
        P + "/{kind}/{rid}/{action}": [
            (P + "/" + kind + "/{rid}/" + action, {"kind": kind, "action": action})
            for kind, action in (("permissions", "reply"), ("questions", "reply"), ("questions", "reject"))],
    }
    for source, variants in expansions.items():
        original = document["paths"].pop(source, None)
        if original is None:
            continue
        for path, fixed in variants:
            item = deepcopy(original)
            for method, operation in item.items():
                if method not in HTTP_METHODS:
                    continue
                operation["parameters"] = [p for p in operation.get("parameters", [])
                                           if not (p.get("in") == "path" and p["name"] in fixed)]
                operation["operationId"] += "_" + "_".join(fixed.values())
                operation["x-runtime-route"] = source
            document["paths"][path] = item


def response(schema, description="成功", content_type="application/json"):
    return {"description": description, "content": {content_type: {"schema": schema}}}


def annotate_body(operation, name):
    if name is None:
        operation.pop("requestBody", None)
        return
    content_type = "multipart/form-data" if name in ("FileUploadBody", "PluginUploadBody") else "application/json"
    operation["requestBody"] = {"required": True, "content": {content_type: {"schema": ref(name)}}}


def annotate_response(operation, schema):
    successes = [code for code in operation["responses"] if code.startswith("2")]
    code = successes[0] if successes else "200"
    operation["responses"] = {code: response(schema if schema is not None else {"type": "string", "format": "binary"},
                                           content_type="application/json" if schema is not None else "application/octet-stream")}
    if schema is None:
        operation["responses"][code]["headers"] = {
            "Content-Disposition": {"schema": STRING, "description": "attachment；文件名由服务端安全编码。"},
            "X-Content-Type-Options": {"schema": STRING, "description": "nosniff"},
        }


def build_openapi(app):
    """Build a fresh, sanitized contract without entering the app lifespan."""
    routes = [route for route in app.routes if getattr(route, "path", "") == "/health"
              or getattr(route, "path", "").startswith((P + "/", "/internal/worker/"))]
    document = get_openapi(title=app.title, version=app.version, routes=routes, openapi_version="3.1.0",
        description="账号绑定的分析控制台 API。普通用户只访问自己的独立环境、会话和文件；管理员管理账号与已发布资源，不获得用户业务数据访问权限。"
                    "浏览器登录使用 HttpOnly Cookie；Cookie 写请求同时携带 X-CSRF-Token，并通过 Origin 校验。"
                    "Python 可使用用户自己创建的 Bearer Token。请仅使用同一种认证方式；不要把 Cookie 值复制到 Bearer。"
                    "内部 Worker API 使用独立宿主密钥，禁止业务客户端调用。")
    document.pop("servers", None)
    document.pop("security", None)
    document.setdefault("components", {})["schemas"] = schemas()
    document["components"]["securitySchemes"] = {
        "SessionCookie": {"type": "apiKey", "in": "cookie", "name": "px_session",
                          "description": "auth/login 设置的 HttpOnly Cookie；不是可放入请求体的账号选择参数。"},
        "BearerToken": {"type": "http", "scheme": "bearer", "bearerFormat": "opaque",
                        "description": "tokens 创建的个人令牌。已撤销、过期、被停用账号的令牌不可用。"},
        "CsrfToken": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token",
                      "description": "Cookie 写操作需要 login/me 返回的 csrf_token；与 SessionCookie 一起使用，不是独立认证。"},
        "WorkerKey": {"type": "apiKey", "in": "header", "name": "X-Worker-Key",
                      "description": "仅可信宿主执行器使用；不是普通 Bearer Token，不提供给浏览器或 Agent。"},
    }
    expand_routes(document)
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation.setdefault("x-runtime-route", path)
            public = path.startswith(P + "/")
            internal = path.startswith("/internal/worker/")
            if path == "/health":
                operation.update(summary="服务健康检查", tags=["健康"], security=[], **{"x-role": "anonymous"})
                annotate_response(operation, ref("Health"))
                continue
            if internal:
                contract = WORKER_CONTRACTS.get((method, path))
                if contract is None:
                    raise ValueError("Undocumented internal API route: " + method + " " + path)
                operation.update(tags=["内部：Worker"], security=[{"WorkerKey": []}], **{"x-internal": True, "x-role": "worker"})
                operation["description"] = "仅可信宿主 Worker 使用 X-Worker-Key；普通 Cookie/Bearer 不能调用。不得向业务客户端公开响应中的租约或部署配置。"
                if path == "/internal/worker/legacy-retry":
                    operation["summary"] = "重试已回退的固定旧环境迁移"
                    operation["description"] += (
                        "仅支持预登记的两个旧账号及精确旧卷组合，必须匹配导入快照和同账号、同环境的回退审计。"
                        "首次重试要求账号停用、环境 failed 且未占用名额、没有排队或运行任务。"
                        "在一个事务内重新启用账号、撤销旧认证并预留容量、创建 resume 任务。202 仅表示任务已接受。"
                        "同一快照重试仅在账号仍启用、认证版本未变、原任务仍为最新任务且处于 queued/running/succeeded、环境为 ready/provisioning，"
                        "并且该账号环境最新的重试/回退审计仍为本次重试时返回同一 job_id。"
                        "再次停用后不得以旧请求重新激活。执行器负责验证旧环境确实停止；此接口不直接停止容器或修改旧卷。")
                annotate_body(operation, contract[0])
                annotate_response(operation, contract[1])
                if path.endswith("/packages/{sha}"):
                    operation["responses"]["200"]["content"] = {"application/zip": {"schema": {"type": "string", "format": "binary"}}}
            elif public:
                contract = CONTRACTS.get((method, path[len(P):]))
                if contract is None:
                    raise ValueError("Undocumented public API route: " + method + " " + path)
                body, output, summary, tag, description = contract
                operation.update(summary=summary, tags=[tag], description=description)
                anonymous = path in (P + "/auth/login", P + "/platform")
                common = path in (P + "/me", P + "/me/password", P + "/auth/logout") or path.startswith(P + "/tokens")
                management = path.startswith(P + "/admin/")
                super_only = management and (path.startswith((P + "/admin/plugins", P + "/admin/templates", P + "/admin/jobs", P + "/admin/connections")) or "/runtime/" in path)
                operation["x-role"] = "anonymous" if anonymous else "super_admin" if super_only else "super_admin|admin" if management else "authenticated" if common else "user"
                if management:
                    operation["x-roles"] = ["super_admin"] if super_only else ["super_admin", "admin"]
                    capability = ("connections.manage" if "/admin/connections" in path or path.endswith("/connections") else "plugins.manage" if "/admin/plugins" in path else "templates.manage" if "/admin/templates" in path
                                  else "jobs.read" if "/admin/jobs" in path else "runtimes.manage" if "/runtime/" in path
                                  else "models.manage" if "/admin/models" in path else "audit.read" if "/admin/audit" in path else "users.manage")
                    operation["x-capability"] = capability
                operation["security"] = [] if anonymous else [{"BearerToken": []}, {"SessionCookie": [], **({"CsrfToken": []} if method not in ("get", "head", "options") else {})}]
                annotate_body(operation, body)
                annotate_response(operation, output)
                if path == P + "/events":
                    operation["responses"] = {"200": response(STRING, "持续的 SSE 变更通知流", "text/event-stream")}
                    operation["x-sse-event"] = {"event": "change", "data": obj({"type": {"type": "string", "enum": ["connected", "updated"]}}, ("type",))}
                if path == P + "/auth/login":
                    operation["responses"]["200"]["headers"] = {"Set-Cookie": {"schema": STRING, "description": "px_session 的 HttpOnly/SameSite=Strict Cookie，最长 8 小时；部署启用 TLS 时配置 Secure。"}}
                if not anonymous and method not in ("get", "head", "options"):
                    operation["x-csrf"] = "Cookie sessions require X-CSRF-Token; personal Bearer tokens do not."
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "path":
                    continue
                if parameter["name"] == "action":
                    parameter["schema"] = {"type": "string", "enum": ["pause", "resume", "retry", "apply"]}
                elif parameter["name"] == "sha":
                    parameter["schema"] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                elif parameter["name"] != "version":
                    parameter["schema"] = deepcopy(ID)
                    parameter["description"] = "资源标识；普通业务资源必须属于当前认证账号。"
            for status, description in {
                "400": "输入不合法或包含不支持的字段", "401": "登录或令牌无效",
                "403": "权限、CSRF、Origin 或初始改密要求未满足",
                "404": "资源不存在或不属于当前账号", "409": "环境未就绪、配置待应用或状态冲突",
                "413": "请求、上传配额或消息引用预算超限", "415": "不支持的文件类型",
                "422": "请求格式不正确", "429": "请求频率或并发超过限制",
                "500": "服务内部错误", "502": "账号环境返回异常", "503": "账号环境暂时不可达",
            }.items():
                operation["responses"][status] = response(ref("Error"), description)
            if path == "/internal/worker/legacy-retry":
                operation["responses"]["403"] = response(ref("Error"), "独立 WorkerKey 无效；普通 Cookie/Bearer 无权调用")
                operation["responses"]["404"] = response(ref("Error"), "允许的旧账号、旧卷绑定或导入快照不存在")
                operation["responses"]["409"] = response(ref("Error"), "未严格确认旧环境停止、缺少匹配回退记录、状态或任务冲突、已再次停用，或运行环境名额已满")
    document["tags"] = [{"name": name} for name in sorted({
        operation["tags"][0] for item in document["paths"].values()
        for method, operation in item.items() if method in HTTP_METHODS})]
    return document


def install_openapi(app):
    """Call at the end of create_app, after every API route is registered."""
    app.openapi_schema = None

    def openapi():
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app)
        return app.openapi_schema

    app.openapi = openapi
