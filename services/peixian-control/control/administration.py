import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from urllib.parse import urlsplit
import zipfile
import hashlib

import httpx
import jsonschema
from fastapi import Depends, Request, UploadFile, File

from .store import ident, now, encode
from .plugin_schema import validate_form
from .connections import aliases


def register_admin(app):
    from .app import PREFIX, admin, require_capability, body_fields, fail, own_id, password_valid, SLUG

    def target_user(uid, actor):
        target = app.state.store.user(own_id(uid))
        roles = ("user", "admin") if actor["role"] == "super_admin" else ("user",)
        if not target or target["role"] not in roles:
            fail("可管理的账号不存在", 404)
        return target

    def user_fields(data, actor, target_role="user"):
        if actor["role"] != "super_admin" and ("plugin_ids" in data or "role" in data or target_role != "user"):
            fail("无权修改此角色或插件授权", 403)
        if target_role == "admin" and ("model_ids" in data or "plugin_ids" in data):
            fail("管理员账号不接受业务授权", 400)

    def save_profile(db, uid, data, old=None):
        old = old or {}
        display_name = str(data.get("display_name", old.get("display_name", "")))[:100]
        police_no = str(data.get("police_no", old.get("police_no", ""))).strip()[:40] or None
        department_id = data.get("department_id", old.get("department_id"))
        position = str(data.get("position", old.get("position", "")))[:100]
        db.execute(
            "INSERT INTO user_profiles(uid,display_name,police_no,department_id,position) VALUES(?,?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET display_name=excluded.display_name,police_no=excluded.police_no,department_id=excluded.department_id,position=excluded.position",
            (uid, display_name, police_no, department_id, position),
        )

    def public_job(job, actor):
        return {"status": job["status"]} if job is not None and actor["role"] == "admin" else job

    def public_user(target, actor):
        if actor["role"] == "admin" and target.get("runtime") is not None:
            return {**target, "runtime": {"status": target["runtime"]["status"]}}
        return target

    def queue(uid, action="apply"):
        try:
            return app.state.store.queue(uid, action)
        except ValueError as exc:
            fail(str(exc), 409)

    def users_list(actor):
        s = app.state.store
        result = []
        for row in s.rows("SELECT id FROM users ORDER BY created"):
            user = s.user(row["id"])
            if actor["role"] != "super_admin" and user["role"] != "user":
                continue
            user["model_ids"] = [v["resource"] for v in s.rows("SELECT resource FROM grants WHERE uid=? AND kind='model'", (row["id"],))]
            if actor["role"] == "super_admin":
                user["plugin_ids"] = [v["resource"] for v in s.rows("SELECT resource FROM grants WHERE uid=? AND kind='plugin'", (row["id"],))]
            result.append(public_user(user, actor))
        return result

    @app.get(PREFIX + "/admin/users")
    async def users(request: Request, user=Depends(admin)):
        items = users_list(user)
        query = request.query_params
        keyword = query.get("query", "").strip().lower()
        if keyword:
            items = [item for item in items if keyword in " ".join(str(item.get(key) or "") for key in ("username", "display_name", "police_no", "position")).lower()]
        for field in ("department_id", "position", "system_role"):
            if query.get(field):
                items = [item for item in items if str(item.get(field) or "") == query[field]]
        if query.get("status") in ("enabled", "disabled"):
            enabled = query["status"] == "enabled"
            items = [item for item in items if item.get("active") is enabled]
        return {"items": items, "total": len(items), "capacity": {"maximum": int(os.getenv("MAX_RUNTIMES", "4")), "reserved": app.state.store.one("SELECT count(*) AS n FROM runtimes WHERE reserved=1")["n"]}}

    @app.post(PREFIX + "/admin/users", status_code=202)
    async def user_create(request: Request, user=Depends(admin)):
        data = body_fields(await request.json(), ("username", "password", "role", "model_ids", "plugin_ids", "display_name", "police_no", "department_id", "position"))
        role = data.get("role", "user")
        if role not in ("user", "admin"):
            fail("仅可创建普通用户或管理员", 403)
        user_fields(data, user, role)
        username = data.get("username", "")
        if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}", username):
            fail("账号需为 3 至 40 位字母、数字、点、横线或下划线")
        password = password_valid(data.get("password") or secrets.token_urlsafe(20))
        s = app.state.store
        if s.one("SELECT 1 FROM users WHERE username=?", (username,)):
            fail("账号已存在", 409)
        try:
            created, job = s.create_user(username, password, role=role, model_ids=data.get("model_ids"),
                                         plugin_ids=data.get("plugin_ids"))
        except ValueError as exc:
            fail(str(exc), 409)
        with s.tx() as db:
            save_profile(db, created["id"], data)
        created = s.user(created["id"])
        request.state.management_target = created["id"]
        return {"user": public_user(created, user), "job": public_job(job, user), "password": password}

    @app.patch(PREFIX + "/admin/users/{uid}")
    async def user_edit(uid: str, request: Request, user=Depends(admin)):
        raw = await request.json()
        if isinstance(raw, dict) and "role" in raw:
            fail("账号角色不可通过此接口修改", 403)
        data = body_fields(raw, ("active", "model_ids", "plugin_ids", "display_name", "police_no", "department_id", "position"))
        s = app.state.store
        target = target_user(uid, user)
        user_fields(data, user, target["role"])
        if not data:
            fail("请提供需要修改的字段")
        profile_fields = {key: data.pop(key) for key in ("display_name", "police_no", "department_id", "position") if key in data}
        if profile_fields.get("department_id") and not s.one("SELECT 1 FROM departments WHERE id=?", (profile_fields["department_id"],)):
            fail("所属部门不存在")
        try:
            updated, job = s.update_user(uid, data, allow_admin=user["role"] == "super_admin") if data else (target, None)
        except ValueError as exc:
            fail(str(exc), 409)
        if profile_fields:
            with s.tx() as db:
                save_profile(db, uid, profile_fields, target)
            updated = s.user(uid)
        return {"user": public_user(updated, user), "job": public_job(job, user)}

    @app.post(PREFIX + "/admin/users/{uid}/reset-password")
    async def user_reset(uid: str, request: Request, user=Depends(admin)):
        data = body_fields(await request.json(), ("password",))
        s = app.state.store
        target_user(uid, user)
        password = password_valid(data.get("password") or secrets.token_urlsafe(20))
        with s.tx() as db:
            db.execute("UPDATE users SET password=?,must_change=0,auth_version=auth_version+1 WHERE id=?", (s.passwords.hash(password), uid))
            db.execute("DELETE FROM auth WHERE uid=?", (uid,))
        return {"password": password}

    @app.post(PREFIX + "/admin/users/{uid}/runtime/{action}")
    async def runtime_action(uid: str, action: str, request: Request, user=Depends(require_capability("runtimes.manage"))):
        if action not in ("pause", "resume", "retry", "apply"):
            fail("操作不支持", 404)
        target = app.state.store.user(own_id(uid))
        if not target or target["role"] != "user":
            fail("账号不存在", 404)
        if not target["active"] and action != "pause":
            fail("请先启用账号", 409)
        return {"job": queue(uid, "provision" if action == "retry" else action)}

    @app.get(PREFIX + "/admin/jobs")
    async def jobs(request: Request, user=Depends(require_capability("jobs.read"))):
        return {"items": app.state.store.rows("SELECT id,uid,action,status,revision,error,created,updated FROM jobs ORDER BY created DESC LIMIT 200")}

    @app.get(PREFIX + "/admin/audit")
    async def audit(request: Request, actor: str | None = None, action: str | None = None,
                    result: str | None = None, user=Depends(require_capability("audit.read"))):
        from .roles import MANAGEMENT_ACTIONS
        allowed = sorted(set(MANAGEMENT_ACTIONS.values()) | {"management.request", "runtime.pause", "runtime.resume", "runtime.retry", "runtime.apply"})
        clauses, values = ["a.action IN (" + ",".join("?" for _ in allowed) + ")"], list(allowed)
        if actor is not None:
            own_id(actor)
            clauses.append("a.actor=?")
            values.append(actor)
        if action is not None:
            if action not in allowed:
                fail("审计动作筛选无效")
            clauses.append("a.action=?")
            values.append(action)
        if result is not None:
            if result not in ("success", "denied", "failed"):
                fail("审计结果筛选无效")
            clauses.append("a.result=?")
            values.append(result)
        rows = app.state.store.rows("SELECT a.id,a.actor,a.actor_role,a.action,a.target,a.result,a.created,u.username FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE " + " AND ".join(clauses) + " ORDER BY a.created DESC,a.rowid DESC LIMIT 500", values)
        # Old records were not uniformly structured; never expose legacy free-text targets.
        for row in rows:
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}", row["target"]):
                row["target"] = "legacy-target"
        return {"items": rows}

    def model_public(row):
        metadata = app.state.store.one("SELECT * FROM model_metadata WHERE model_id=?", (row["id"],)) or {}
        return {
            **{k: row[k] for k in ("id", "name", "description", "base_url", "model_id", "enabled", "is_default")},
            "api_key_configured": bool(app.state.store.decrypt(row["secret"])),
            "provider": metadata.get("provider", ""),
            "context_length": metadata.get("context_length", 131072),
            "access_mode": metadata.get("access_mode", "api"),
            "supports_tools": bool(metadata.get("supports_tools", 1)),
            "test_status": metadata.get("test_status", "untested"),
            "updated_at": metadata.get("updated"),
        }

    @app.get(PREFIX + "/admin/models")
    async def models(request: Request, user=Depends(require_capability("models.manage"))):
        return {"items": [model_public(row) for row in app.state.store.rows("SELECT * FROM models ORDER BY name")]}

    def model_data(data, old=None):
        body_fields(data, ("name", "description", "base_url", "model_id", "api_key", "enabled", "is_default", "provider", "context_length", "access_mode", "supports_tools"))
        result = {**(old or {}), **data}
        for key in ("name", "base_url", "model_id"):
            if not isinstance(result.get(key), str) or not result[key].strip() or len(result[key]) > 500:
                fail("请填写模型名称、接口地址和模型 ID")
        parsed = urlsplit(result["base_url"])
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            fail("模型地址必须是无认证参数的 HTTP/HTTPS 地址")
        result["base_url"] = result["base_url"].rstrip("/")
        result["description"] = str(result.get("description", ""))[:500]
        result["secret"] = app.state.store.encrypt(data["api_key"]) if data.get("api_key") else (old["secret"] if old else app.state.store.encrypt(""))
        result["enabled"] = bool(result.get("enabled", True))
        result["is_default"] = bool(result.get("is_default", False))
        return result

    @app.post(PREFIX + "/admin/models")
    async def model_create(request: Request, user=Depends(require_capability("models.manage"))):
        s = app.state.store
        data = model_data(await request.json())
        mid = ident()
        with s.tx() as db:
            if data["is_default"]:
                db.execute("UPDATE models SET is_default=0")
            db.execute("INSERT INTO models VALUES(?,?,?,?,?,?,?,?)", (mid, data["name"], data["description"], data["base_url"], data["model_id"], data["secret"], data["enabled"], data["is_default"]))
            db.execute("INSERT INTO model_metadata VALUES(?,?,?,?,?,?,?)", (mid, str(data.get("provider", ""))[:100], int(data.get("context_length", 131072)), str(data.get("access_mode", "api"))[:30], bool(data.get("supports_tools", True)), "untested", now()))
        request.state.management_target = mid
        return model_public(s.one("SELECT * FROM models WHERE id=?", (mid,)))

    @app.patch(PREFIX + "/admin/models/{mid}")
    async def model_edit(mid: str, request: Request, user=Depends(require_capability("models.manage"))):
        s = app.state.store
        old = s.one("SELECT * FROM models WHERE id=?", (own_id(mid),))
        if not old:
            fail("模型不存在", 404)
        data = model_data(await request.json(), old)
        with s.tx() as db:
            if data["is_default"]:
                db.execute("UPDATE models SET is_default=0")
            db.execute("UPDATE models SET name=?,description=?,base_url=?,model_id=?,secret=?,enabled=?,is_default=? WHERE id=?", (data["name"], data["description"], data["base_url"], data["model_id"], data["secret"], data["enabled"], data["is_default"], mid))
            db.execute(
                "INSERT INTO model_metadata VALUES(?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET provider=excluded.provider,context_length=excluded.context_length,access_mode=excluded.access_mode,supports_tools=excluded.supports_tools,updated=excluded.updated",
                (mid, str(data.get("provider", ""))[:100], int(data.get("context_length", 131072)), str(data.get("access_mode", "api"))[:30], bool(data.get("supports_tools", True)), "untested", now()),
            )
        queued = []
        for row in s.rows("SELECT uid FROM grants WHERE kind='model' AND resource=?", (mid,)):
            try:
                queued.append(s.queue(row["uid"]))
            except ValueError:
                pass
        return {"model": model_public(s.one("SELECT * FROM models WHERE id=?", (mid,))), "jobs": [public_job(job, user) for job in queued]}

    @app.post(PREFIX + "/admin/models/{mid}/test")
    async def model_test(mid: str, request: Request, user=Depends(require_capability("models.manage"))):
        s = app.state.store
        m = s.one("SELECT * FROM models WHERE id=?", (own_id(mid),))
        if not m:
            fail("模型不存在", 404)
        try:
            r = await app.state.http.get(m["base_url"] + "/models", headers={"Authorization": "Bearer " + s.decrypt(m["secret"])}, follow_redirects=False, timeout=15)
            found = r.status_code == 200 and any(v.get("id") == m["model_id"] for v in r.json().get("data", []))
        except (httpx.HTTPError, ValueError, AttributeError):
            found = False
        with s.tx() as db:
            db.execute("INSERT INTO model_metadata(model_id,test_status,updated) VALUES(?,?,?) ON CONFLICT(model_id) DO UPDATE SET test_status=excluded.test_status,updated=excluded.updated", (mid, "success" if found else "failed", now()))
        return {"ok": found, "message": "连接成功，模型 ID 已确认" if found else "未能确认模型，请检查地址、凭据和模型 ID"}

    @app.get(PREFIX + "/admin/plugins")
    async def plugins(request: Request, user=Depends(require_capability("plugins.manage"))):
        result = []
        for row in app.state.store.rows("SELECT * FROM plugins ORDER BY rowid DESC"):
            result.append({**{k: row[k] for k in ("id", "version", "name", "description", "digest", "enabled")}, "connections": aliases(json.loads(row["manifest"]))})
        return {"items": result}

    @app.post(PREFIX + "/admin/plugins")
    async def publish(request: Request, file: UploadFile = File(...), user=Depends(require_capability("plugins.manage"))):
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            fail("插件包不能超过 20 MiB", 413)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > 1000 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
                    fail("插件包解压内容超限")
                names = set()
                for member in members:
                    p = PurePosixPath(member.filename)
                    mode = member.external_attr >> 16
                    if member.orig_filename != member.filename or p.is_absolute() or ".." in p.parts or "\\" in member.filename or ":" in member.filename or stat.S_ISLNK(mode) or member.filename in names:
                        fail("插件包包含不安全路径")
                    names.add(member.filename)
                manifest = json.loads(archive.read("manifest.json"))
                if not SLUG.fullmatch(manifest.get("id", "")) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest.get("version", "")):
                    fail("插件 ID 或版本格式不正确")
                entry = manifest.get("entry", "entry.mjs")
                if entry not in names or not entry.endswith(".mjs"):
                    fail("插件入口必须是包内已打包的 .mjs 文件")
                schema = manifest.get("config_schema", {"type": "object", "properties": {}, "additionalProperties": False})
                jsonschema.Draft202012Validator.check_schema(schema)
                validate_form(schema)
                if '"$ref"' in encode(schema):
                    fail("配置表单不支持外部或递归引用")
                if manifest.get("opencode_version", "1.18.30") != "1.18.30":
                    fail("插件需要声明兼容 OpenCode 1.18.30")
                manifest.update(entry=entry, config_schema=schema)
                aliases(manifest)
        except (zipfile.BadZipFile, KeyError, ValueError, jsonschema.SchemaError):
            fail("插件包无效，需要 manifest.json 和打包好的入口文件")
        s = app.state.store
        if s.one("SELECT 1 FROM plugins WHERE id=? AND version=?", (manifest["id"], manifest["version"])):
            fail("该版本已经发布，不能覆盖；请使用新版本号", 409)
        sha = hashlib.sha256(data).hexdigest()
        folder = s.root / "packages"
        folder.mkdir(exist_ok=True)
        path = folder / (sha + ".zip")
        path.write_bytes(data)
        with s.tx() as db:
            db.execute("INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)", (manifest["id"], manifest["version"], str(manifest.get("name", manifest["id"]))[:100], str(manifest.get("description", ""))[:1000], encode(manifest), str(path), sha))
        request.state.management_target = manifest["id"] + "@" + manifest["version"]
        return {"id": manifest["id"], "version": manifest["version"], "digest": sha}

    @app.patch(PREFIX + "/admin/plugins/{pid}/{version}")
    async def plugin_state(pid: str, version: str, request: Request, user=Depends(require_capability("plugins.manage"))):
        data = body_fields(await request.json(), ("enabled",))
        s = app.state.store
        with s.tx() as db:
            if not db.execute("UPDATE plugins SET enabled=? WHERE id=? AND version=?", (bool(data.get("enabled")), own_id(pid), version)).rowcount:
                fail("插件版本不存在", 404)
        jobs = []
        for row in s.rows("SELECT uid FROM installs WHERE plugin=? AND version=?", (pid, version)):
            try:
                jobs.append(s.queue(row["uid"]))
            except ValueError:
                pass
        request.state.management_target = pid + "@" + version
        return {"ok": True, "jobs": jobs}

    @app.get(PREFIX + "/admin/templates")
    async def templates(request: Request, user=Depends(require_capability("templates.manage"))):
        return {"items": app.state.store.rows("SELECT * FROM templates ORDER BY name")}

    @app.post(PREFIX + "/admin/templates")
    async def template_create(request: Request, user=Depends(require_capability("templates.manage"))):
        data = body_fields(await request.json(), ("name", "description", "content"))
        if not str(data.get("name", "")).strip() or not 1 <= len(str(data.get("content", ""))) <= 32000:
            fail("请填写模板名称和指令内容")
        tid = ident()
        with app.state.store.tx() as db:
            db.execute("INSERT INTO templates VALUES(?,?,?,?)", (tid, str(data["name"])[:60], str(data.get("description", ""))[:500], data["content"]))
        request.state.management_target = tid
        return {"id": tid, **data}

    @app.patch(PREFIX + "/admin/templates/{tid}")
    async def template_edit(tid: str, request: Request, user=Depends(require_capability("templates.manage"))):
        data = body_fields(await request.json(), ("name", "description", "content"))
        old = app.state.store.one("SELECT * FROM templates WHERE id=?", (own_id(tid),))
        if not old:
            fail("模板不存在", 404)
        result = {**old, **data}
        if not str(result["name"]).strip() or not 1 <= len(str(result["content"])) <= 32000:
            fail("模板内容无效")
        with app.state.store.tx() as db:
            db.execute("UPDATE templates SET name=?,description=?,content=? WHERE id=?", (str(result["name"])[:60], str(result["description"])[:500], result["content"], tid))
        return result

    @app.delete(PREFIX + "/admin/templates/{tid}")
    async def template_delete(tid: str, request: Request, user=Depends(require_capability("templates.manage"))):
        with app.state.store.tx() as db:
            db.execute("DELETE FROM templates WHERE id=?", (own_id(tid),))
        return {"ok": True}
