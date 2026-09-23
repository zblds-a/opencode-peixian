from .concurrency import blocking_endpoint
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import time
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
from .backend_contract import PROFILE_FIELDS, MODEL_FIELDS, save_profile, save_model_profile, model_profile, require_v6, error


def register_admin(app):
    from .app import PREFIX, admin, require_capability, body_fields, fail, own_id, password_valid, SLUG, current_authority

    def target_user(uid, actor):
        target = app.state.store.user(own_id(uid))
        roles = ("user", "admin") if actor["role"] == "super_admin" else ("user",)
        if not target or target["role"] not in roles:
            fail("可管理的账号不存在", 404)
        return target

    def user_fields(data, actor, target_role="user"):
        if actor["role"] != "super_admin" and ("department_id" in data or "plugin_ids" in data or "role" in data or target_role != "user"):
            fail("无权修改此角色或插件授权", 403)
        if target_role == "admin" and ("model_ids" in data or "plugin_ids" in data):
            fail("管理员账号不接受业务授权", 400)

    def public_job(job, actor):
        return {"status": job["status"]} if job is not None and actor["role"] == "admin" else job

    def public_user(target, actor):
        if actor["role"] == "admin" and target.get("runtime") is not None:
            return {**target, "runtime": {"status": target["runtime"]["status"]}}
        return target

    def queue(uid, action="apply"):
        try:
            return app.state.store.queue(uid, action, bump_desired=False,
                                         reason="admin" if action == "pause" else "normal")
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
    @blocking_endpoint(app)
    def users(request: Request, user=Depends(admin)):
        return {"items": users_list(user), "capacity": {"maximum": int(os.getenv("MAX_RUNTIMES", "4")), "reserved": app.state.store.one("SELECT count(*) AS n FROM runtimes WHERE reserved=1")["n"]}}

    @app.post(PREFIX + "/admin/users", status_code=202)
    async def user_create(request: Request, user=Depends(admin)):
        from .idempotency import key, execute
        key(request)
        request.state.json_body = await request.json()
        data = body_fields(request.state.json_body, ("username", "password", "role", "model_ids", "plugin_ids", *PROFILE_FIELDS))
        role = data.get("role", "user")
        if role not in ("user", "admin"):
            fail("仅可创建普通用户或管理员", 403)
        user_fields(data, user, role)
        username = data.get("username", "")
        if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}", username):
            fail("账号需为 3 至 40 位字母、数字、点、横线或下划线")
        password = password_valid(data.get("password") or secrets.token_urlsafe(20))
        s = app.state.store
        hashed = await app.state.crypto_work.run(s.passwords.hash, password)
        def create():
            if s.one("SELECT 1 FROM users WHERE username=?", (username,)):
                fail("账号已存在", 409)
            try:
                created, job = s.create_user_prehashed(username, hashed, role=role, model_ids=data.get("model_ids"),
                                             plugin_ids=data.get("plugin_ids"), authorize=lambda db: current_authority(db, user))
            except ValueError as exc:
                fail(str(exc), 409)
            if any(k in data for k in PROFILE_FIELDS):
                require_v6(s)
                with s.tx() as db: save_profile(db,created["id"],data,user)
                created=s.user(created["id"])
            request.state.management_target = created["id"]
            return {"user": public_user(created, user), "job": public_job(job, user), "password": password}
        return await app.state.db_work.run(execute, request, user, create)

    @app.patch(PREFIX + "/admin/users/{uid}")
    @blocking_endpoint(app, json_body=True)
    def user_edit(uid: str, request: Request, user=Depends(admin)):
        raw = request.state.json_body
        if isinstance(raw, dict) and "role" in raw:
            fail("账号角色不可通过此接口修改", 403)
        data = body_fields(raw, ("active", "model_ids", "plugin_ids", *PROFILE_FIELDS))
        s = app.state.store
        target = target_user(uid, user)
        user_fields(data, user, target["role"])
        if not data:
            fail("请提供需要修改的字段")
        try:
            with s.tx() as db:
                if any(k in data for k in PROFILE_FIELDS):
                    require_v6(s); save_profile(db,uid,data,user)
                base={k:v for k,v in data.items() if k not in PROFILE_FIELDS}
                updated, job = s.update_user(uid, base, allow_admin=user["role"] == "super_admin") if base else (s.user(uid),None)
        except ValueError as exc:
            fail(str(exc), 409)
        return {"user": public_user(updated, user), "job": public_job(job, user)}

    @app.post(PREFIX + "/admin/users/{uid}/reset-password")
    async def user_reset(uid: str, request: Request, user=Depends(admin)):
        from .idempotency import key, execute
        key(request)
        request.state.json_body = await request.json()
        data = body_fields(request.state.json_body, ("password",))
        s = app.state.store
        await app.state.db_work.run(target_user, uid, user)
        password = password_valid(data.get("password") or secrets.token_urlsafe(20))
        hashed = await app.state.crypto_work.run(s.passwords.hash, password)
        def reset():
            with s.tx() as db:
                current_authority(db, user)
                target = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
                roles = ("user", "admin") if user["role"] == "super_admin" else ("user",)
                if target is None or target["role"] not in roles:
                    fail("可管理的账号不存在", 404)
                db.execute("UPDATE users SET password=?,must_change=1,auth_version=auth_version+1 WHERE id=?", (hashed, uid))
                db.execute("DELETE FROM auth WHERE uid=?", (uid,))
            return {"password": password}
        return await app.state.db_work.run(execute, request, user, reset)

    @app.post(PREFIX + "/admin/users/{uid}/runtime/{action}")
    @blocking_endpoint(app)
    def runtime_action(uid: str, action: str, request: Request, user=Depends(require_capability("runtimes.manage"))):
        if action not in ("pause", "resume", "retry", "apply"):
            fail("操作不支持", 404)
        target = app.state.store.user(own_id(uid))
        if not target or target["role"] != "user":
            fail("账号不存在", 404)
        if not target["active"] and action != "pause":
            fail("请先启用账号", 409)
        if app.state.store.on_demand() and action in ("resume", "retry"):
            with app.state.store.tx() as db:
                from .runtime_pool import start
                return start(app.state.store, db, uid, admin=True)
        return {"job": queue(uid, "provision" if action == "retry" else action)}

    @app.get(PREFIX + "/admin/jobs")
    @blocking_endpoint(app)
    def jobs(request: Request, user=Depends(require_capability("jobs.read"))):
        return {"items": app.state.store.rows("SELECT id,uid,action,status,revision,error,created,updated,phase,not_before,defer_count,recovery_required FROM jobs ORDER BY enqueue_seq DESC LIMIT 200")}

    @app.get(PREFIX + "/admin/maintenance")
    @blocking_endpoint(app)
    def maintenance_state(request: Request, user=Depends(require_capability("runtimes.manage"))):
        s = app.state.store
        state = s.maintenance_status()
        return {"mode": state["maintenance_mode"], "state_version": state["state_version"],
                "capacity_healthy": bool(state["capacity_healthy"]),
                "recovery_required": s.one("SELECT COUNT(*) AS n FROM runtimes WHERE recovery_required=1")["n"],
                "security_pending": s.one("SELECT COUNT(*) AS n FROM runtimes WHERE security_blocked=1 AND cancellation_confirmed=0")["n"],
                "safety_sync_failures": app.state.safety.failures}

    @app.get(PREFIX + "/admin/diagnostics/events")
    async def event_diagnostics(request: Request, user=Depends(require_capability("runtimes.manage"))):
        # Loop-owned counters must not be read by a database worker thread.
        return {"hub": app.state.event_hubs.stats(), "streams": app.state.stream_registry.stats(),
                "runtime_pool": {"retryable_failures": getattr(app.state, 'pool_failures', 0)},
                "cache": app.state.live_text.stats(),
                "work": {"database": app.state.db_work.stats(), "password": app.state.crypto_work.stats()}}

    @app.post(PREFIX + "/admin/maintenance")
    @blocking_endpoint(app, json_body=True)
    def maintenance_set(request: Request, user=Depends(require_capability("runtimes.manage"))):
        data = body_fields(request.state.json_body, ("mode", "state_version"))
        state = app.state.store.set_maintenance(data.get("mode"), data.get("state_version"), user["uid"])
        return {"mode": state["maintenance_mode"], "state_version": state["state_version"]}

    @app.post(PREFIX + "/admin/recovery/{uid}")
    @blocking_endpoint(app, json_body=True)
    def recovery_action(uid: str, request: Request, user=Depends(require_capability("runtimes.manage"))):
        data = body_fields(request.state.json_body, ("action", "state_version"))
        from .orchestration import Orchestration
        if data.get("action") == "retry":
            return Orchestration(app.state.store).retry_recovery(own_id(uid),data.get("state_version"),user["uid"])
        if data.get("action") not in ("continue", "cancel"):
            fail("请选择恢复重试、继续等待或取消活动后更新")
        return Orchestration(app.state.store).resolve_drain(own_id(uid), data["action"], user["uid"])

    @app.get(PREFIX + "/admin/audit")
    @blocking_endpoint(app)
    def audit(request: Request, actor: str | None = None, action: str | None = None,
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
        return {**{k: row[k] for k in ("id", "name", "description", "base_url", "model_id", "enabled", "is_default")}, "api_key_configured": bool(app.state.store.decrypt(row["secret"]))}

    @app.get(PREFIX + "/admin/models")
    @blocking_endpoint(app)
    def models(request: Request, user=Depends(require_capability("models.manage"))):
        return {"items": [{**model_public(row), **model_profile(app.state.store,row["id"])} for row in app.state.store.rows("SELECT * FROM models ORDER BY name")]}

    def model_data(data, old=None):
        body_fields(data, ("name", "description", "base_url", "model_id", "api_key", "enabled", "is_default", *MODEL_FIELDS))
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
        if result['is_default'] and not result['enabled']:
            result['is_default']=False
        return result

    async def test_connection(data):
        started=time.monotonic();found=False
        try:
            async with app.state.http.stream('GET',data['base_url']+'/models',headers={'Authorization':'Bearer '+app.state.store.decrypt(data['secret'])},follow_redirects=False,timeout=15) as response:
                content=bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content)>1048576:break
                if response.status_code==200 and len(content)<=1048576:
                    payload=json.loads(content)
                    found=isinstance(payload,dict) and isinstance(payload.get('data'),list) and any(isinstance(v,dict) and v.get('id')==data['model_id'] for v in payload['data'])
        except (httpx.HTTPError,ValueError,TypeError):pass
        return {'ok':found,'message':'连接成功，模型 ID 已确认' if found else '未能确认模型，请检查地址、凭据和模型 ID','elapsed_ms':round((time.monotonic()-started)*1000)}

    @app.post(PREFIX+'/admin/models/test')
    async def model_test_unsaved(request:Request,user=Depends(require_capability('models.manage'))):
        data=model_data(await request.json())
        result=await test_connection(data)
        await app.state.db_work.run(app.state.store.audit,user['uid'],'model.test.unsaved','unsaved',actor_role=user['role'])
        return result

    @app.post(PREFIX + "/admin/models")
    @blocking_endpoint(app, json_body=True)
    def model_create(request: Request, user=Depends(require_capability("models.manage"))):
        s = app.state.store
        data = model_data(request.state.json_body)
        mid = ident()
        with s.tx() as db:
            if data["is_default"]:
                db.execute("UPDATE models SET is_default=0")
            db.execute("INSERT INTO models VALUES(?,?,?,?,?,?,?,?)", (mid, data["name"], data["description"], data["base_url"], data["model_id"], data["secret"], data["enabled"], data["is_default"]))
            if s.schema_version()>=6:save_model_profile(db,mid,data,now())
            elif any(k in data for k in MODEL_FIELDS):require_v6(s)
        request.state.management_target = mid
        return {**model_public(s.one("SELECT * FROM models WHERE id=?", (mid,))),**model_profile(s,mid)}

    @app.patch(PREFIX + "/admin/models/{mid}")
    @blocking_endpoint(app, json_body=True)
    def model_edit(mid: str, request: Request, user=Depends(require_capability("models.manage"))):
        from .runtime_security import block_runtime
        s = app.state.store
        with s.tx() as db:
            row = db.execute("SELECT * FROM models WHERE id=?", (own_id(mid),)).fetchone()
            old = dict(row) if row else None
            if not old:
                fail("模型不存在", 404)
            data = model_data(request.state.json_body, old)
            if data["is_default"]:
                db.execute("UPDATE models SET is_default=0")
            db.execute("UPDATE models SET name=?,description=?,base_url=?,model_id=?,secret=?,enabled=?,is_default=? WHERE id=?", (data["name"], data["description"], data["base_url"], data["model_id"], data["secret"], data["enabled"], data["is_default"], mid))
            if s.schema_version()>=6:save_model_profile(db,mid,data,now())
            elif any(k in data for k in MODEL_FIELDS):require_v6(s)
            if old["enabled"] and not data["enabled"]:
                for row in db.execute("SELECT uid FROM grants WHERE kind='model' AND resource=?", (mid,)).fetchall():
                    block_runtime(s, db, row["uid"], reason="model_disabled")
        queued = []
        for row in s.rows("SELECT uid FROM grants WHERE kind='model' AND resource=?", (mid,)):
            try:
                queued.append(s.queue(row["uid"]))
            except ValueError:
                pass
        return {"model": {**model_public(s.one("SELECT * FROM models WHERE id=?", (mid,))), **model_profile(s,mid)}, "jobs": [public_job(job, user) for job in queued]}

    @app.post(PREFIX + "/admin/models/{mid}/test")
    async def model_test(mid: str, request: Request, user=Depends(require_capability("models.manage"))):
        s = app.state.store
        m = await app.state.db_work.run(s.one, "SELECT * FROM models WHERE id=?", (own_id(mid),))
        if not m:
            fail("模型不存在", 404)
        result=await test_connection(m)
        def recorded():
            if s.schema_version()<6:return
            with s.tx() as db:
                # Do not attach a stale test to an edited endpoint or credential.
                current=db.execute('SELECT base_url,model_id,secret FROM models WHERE id=?',(mid,)).fetchone()
                if current and all(current[k]==m[k] for k in ('base_url','model_id','secret')):
                    db.execute("INSERT INTO model_profiles(mid,updated,test_status) VALUES(?,?,?) ON CONFLICT(mid) DO UPDATE SET test_status=excluded.test_status",(mid,now(),'passed' if result['ok'] else 'failed'))
        await app.state.db_work.run(recorded)
        return result

    @app.get(PREFIX + "/admin/plugins")
    @blocking_endpoint(app)
    def plugins(request: Request, user=Depends(require_capability("plugins.manage"))):
        result = []
        for row in app.state.store.rows("SELECT * FROM plugins ORDER BY rowid DESC"):
            result.append({**{k: row[k] for k in ("id", "version", "name", "description", "digest", "enabled")}, "connections": aliases(json.loads(row["manifest"]))})
        return {"items": result}

    @app.post(PREFIX + "/admin/plugins")
    @blocking_endpoint(app, upload=True)
    def publish(request: Request, file: UploadFile = File(...), user=Depends(require_capability("plugins.manage"))):
        data = request.state.upload_body
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
                from .data_plugin_policy import valid_bundle
                if not valid_bundle(manifest):
                    fail("仅允许发布八项固定资料插件，且每项只能注册对应的查询工具", 409)
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
        sha = hashlib.sha256(data).hexdigest()
        folder = s.root / "packages"
        folder.mkdir(exist_ok=True)
        path = folder / (sha + ".zip")
        if not path.exists():
            path.write_bytes(data)
        def publish_prepared():
            with s.tx() as db:
                if db.execute("SELECT 1 FROM plugins WHERE id=? AND version=?", (manifest["id"], manifest["version"])).fetchone():
                    fail("该版本已经发布，不能覆盖；请使用新版本号", 409)
                db.execute("INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)", (manifest["id"], manifest["version"], str(manifest.get("name", manifest["id"]))[:100], str(manifest.get("description", ""))[:1000], encode(manifest), str(path), sha))
            request.state.management_target = manifest["id"] + "@" + manifest["version"]
            return {"id": manifest["id"], "version": manifest["version"], "digest": sha}
        from .idempotency import execute
        return execute(request, user, publish_prepared)

    @app.patch(PREFIX + "/admin/plugins/{pid}/{version}")
    @blocking_endpoint(app, json_body=True)
    def plugin_state(pid: str, version: str, request: Request, user=Depends(require_capability("plugins.manage"))):
        from .runtime_security import block_runtime
        from .data_plugin_policy import ACTIVE_VERSION, installable
        data = body_fields(request.state.json_body, ("enabled",))
        if data.get("enabled") and (not installable(pid) or version != ACTIVE_VERSION):
            fail("该资料插件已归档，不可重新启用", 409)
        s = app.state.store
        with s.tx() as db:
            old = db.execute("SELECT enabled FROM plugins WHERE id=? AND version=?", (own_id(pid), version)).fetchone()
            if not db.execute("UPDATE plugins SET enabled=? WHERE id=? AND version=?", (bool(data.get("enabled")), own_id(pid), version)).rowcount:
                fail("插件版本不存在", 404)
            if old and old["enabled"] and not bool(data.get("enabled")):
                for row in db.execute("SELECT uid FROM installs WHERE plugin=? AND version=?", (pid, version)).fetchall():
                    block_runtime(s, db, row["uid"], reason="plugin_disabled")
        jobs = []
        for row in s.rows("SELECT uid FROM installs WHERE plugin=? AND version=?", (pid, version)):
            try:
                jobs.append(s.queue(row["uid"]))
            except ValueError:
                pass
        request.state.management_target = pid + "@" + version
        return {"ok": True, "jobs": jobs}

    @app.get(PREFIX + "/admin/templates")
    @blocking_endpoint(app)
    def templates(request: Request, user=Depends(require_capability("templates.manage"))):
        return {"items": app.state.store.rows("SELECT * FROM templates ORDER BY name")}

    @app.post(PREFIX + "/admin/templates")
    @blocking_endpoint(app, json_body=True)
    def template_create(request: Request, user=Depends(require_capability("templates.manage"))):
        data = body_fields(request.state.json_body, ("name", "description", "content"))
        if not str(data.get("name", "")).strip() or not 1 <= len(str(data.get("content", ""))) <= 32000:
            fail("请填写模板名称和指令内容")
        tid = ident()
        with app.state.store.tx() as db:
            db.execute("INSERT INTO templates VALUES(?,?,?,?)", (tid, str(data["name"])[:60], str(data.get("description", ""))[:500], data["content"]))
        request.state.management_target = tid
        return {"id": tid, **data}

    @app.patch(PREFIX + "/admin/templates/{tid}")
    @blocking_endpoint(app, json_body=True)
    def template_edit(tid: str, request: Request, user=Depends(require_capability("templates.manage"))):
        data = body_fields(request.state.json_body, ("name", "description", "content"))
        with app.state.store.tx() as db:
            row = db.execute("SELECT * FROM templates WHERE id=?", (own_id(tid),)).fetchone()
            old = dict(row) if row else None
            if not old:
                fail("模板不存在", 404)
            result = {**old, **data}
            if not str(result["name"]).strip() or not 1 <= len(str(result["content"])) <= 32000:
                fail("模板内容无效")
            db.execute("UPDATE templates SET name=?,description=?,content=? WHERE id=?", (str(result["name"])[:60], str(result["description"])[:500], result["content"], tid))
        return result

    @app.delete(PREFIX + "/admin/templates/{tid}")
    @blocking_endpoint(app)
    def template_delete(tid: str, request: Request, user=Depends(require_capability("templates.manage"))):
        with app.state.store.tx() as db:
            db.execute("DELETE FROM templates WHERE id=?", (own_id(tid),))
        return {"ok": True}
