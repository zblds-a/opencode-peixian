from .concurrency import blocking_endpoint
import hmac
import hashlib
import json
from pathlib import Path
import secrets

from fastapi import Request, Depends
from fastapi.responses import FileResponse

from .store import now, ident, encode
from .connections import resolved_bindings, connection_headers


def runtime_spec(s, uid, revision, *, db=None):
    # Claim passes its own transaction so desired, grants and all configuration
    # rows come from exactly the snapshot that is committed with the lease.
    if db is None:
        with s.read(snapshot=True) as snapshot:
            return runtime_spec(s, uid, revision, db=snapshot)

    def rows(query, args=()):
        return [dict(row) for row in db.execute(query, args)]

    runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
    if runtime is None or runtime["desired"] != revision:
        raise ValueError("Runtime revision changed before configuration was captured")
    private = s.decrypt(runtime["spec"])
    models = rows("SELECT m.* FROM models m JOIN grants g ON g.resource=m.id AND g.kind='model' WHERE g.uid=? AND m.enabled=1 ORDER BY m.is_default DESC,m.id", (uid,))
    model_config = {}
    relay = []
    for m in models:
        model_config[m["id"]] = {"name": m["name"], "limit": {"context": 32768, "output": 2048}, "attachment": False}
        if "api.deepseek.com" in m["base_url"]:
            model_config[m["id"]].update({"interleaved": {"field": "reasoning_content"}, "options": {"thinking": {"type": "disabled"}}, "variants": {"low": {"disabled": True}, "medium": {"disabled": True}, "high": {"disabled": True}}})
        relay.append({"id": m["id"], "upstream_model": m["model_id"], "base_url": m["base_url"], "api_key": s.decrypt(m["secret"]), "allowed_user": uid})
    config = {"enabled_providers": ["peixian"] if models else [], "share": "disabled", "autoupdate": False, "formatter": False, "lsp": False, "mcp": {}, "plugin": [], "skills": {"paths": ["/managed/skills"]}, "permission": {"*": "deny", "read": {"*": "allow", "../*": "deny", "../files/*": "allow", "/*": "deny"}, "edit": {"*": "allow", "../*": "deny", "/*": "deny"}, "glob": "allow", "grep": "allow", "skill": "allow", "question": "allow", "external_directory": {"*": "deny", "/files/*": "allow"}}}
    if models:
        selected = "peixian/" + models[0]["id"]
        config.update(model=selected, small_model=selected, provider={"peixian": {"name": "授权模型", "npm": "@ai-sdk/openai-compatible", "options": {"baseURL": "http://model-relay:8081/v1", "apiKey": "relay-injected"}, "models": model_config}})
        config["agent"] = {name: {"model": selected} for name in ("title", "summary", "compaction")}
    plugins = []
    connections = []
    from .data_plugin_policy import installable
    for installed in rows("SELECT i.*,p.manifest,p.digest FROM installs i JOIN plugins p ON p.id=i.plugin AND p.version=i.version JOIN grants g ON g.uid=i.uid AND g.kind='plugin' AND g.resource=i.plugin WHERE i.uid=? AND i.enabled=1 AND p.enabled=1", (uid,)):
        if not installable(installed["plugin"]):
            continue
        manifest = json.loads(installed["manifest"])
        bindings, missing = resolved_bindings(db, installed["plugin"], installed["version"], manifest)
        if missing:
            continue
        platform_connections = {}
        for alias, row in bindings.items():
            binding_id = hashlib.sha256(encode([installed["plugin"], alias, row["id"]]).encode()).hexdigest()[:32]
            token = hmac.new(private["gateway_key"].encode(), encode([uid, installed["plugin"], alias, revision]).encode(), hashlib.sha256).hexdigest()
            value = json.loads(row["config"])
            connections.append({"id": binding_id, "plugin_id": installed["plugin"], "alias": alias,
                                "allowed_user": uid, "token": token, "headers": connection_headers(s, row),
                                **({"request_rules": value["request_rules"]} if "request_rules" in value else {}),
                                **{k: value[k] for k in ("base_url", "allowed_methods", "allowed_paths", "timeout_seconds", "max_response_bytes")}})
            platform_connections[alias] = {"id": binding_id, "token": token}
        plugins.append({"id": installed["plugin"], "version": installed["version"], "manifest": manifest, "digest": installed["digest"], "options": s.decrypt(installed["config"]), "platform_connections": platform_connections})
        config["plugin"].append("file:///managed/loaders/" + installed["plugin"] + ".mjs")
        for tool in manifest.get("tools", []):
            if isinstance(tool, str) and tool.replace("_", "").replace("-", "").isalnum() and tool not in ("bash", "pty", "webfetch", "websearch"):
                config["permission"][tool] = "allow"
    return {"uid": uid, "runtime_id": runtime["id"], "revision": revision, "private": private, "config": config, "models": relay, "connections": connections, "plugins": plugins, "skills": rows("SELECT id,name,description,content,version FROM skills WHERE uid=? AND enabled=1", (uid,))}


def register_worker(app):
    from .app import fail, own_id, body_fields

    def worker(request: Request):
        if not hmac.compare_digest(request.headers.get("x-worker-key", ""), app.state.store.worker_key):
            fail("无权访问", 403)
        return True

    def protocol_worker(request: Request, authorized=Depends(worker)):
        if request.headers.get("x-peixian-protocol") != "2":
            from .orchestration import reject
            reject("执行器协议不匹配，必须使用内部协议 2", code="worker_protocol_mismatch")
        from shared.runtime_pool_config import CAPABILITY
        from shared.runtime_pool_config import WAIT_CAPABILITY
        if app.state.store.maintenance_status().get('pool_policy_version',1)>=3 and 'idle_activity_v1' not in request.headers.get('x-peixian-capabilities','').split(','):
            from .orchestration import reject
            reject('执行器缺少空闲活动能力', code='worker_capability_mismatch')
        if app.state.store.maintenance_status().get('pool_policy_version', 1) >= 2 and WAIT_CAPABILITY not in request.headers.get('x-peixian-capabilities', '').split(','):
            from .orchestration import reject
            reject('执行器缺少容量等待能力', code='worker_capability_mismatch')
        if app.state.store.on_demand() and CAPABILITY not in request.headers.get("x-peixian-capabilities", "").split(","):
            from .orchestration import reject
            reject("执行器缺少按需环境能力", code="worker_capability_mismatch")
        if app.state.store.on_demand() and request.headers.get("x-peixian-runtime-mode") != "on_demand":
            from .orchestration import reject
            reject("执行器运行模式与控制库不匹配", code="worker_capability_mismatch")
        if app.state.store.on_demand() and request.url.path.startswith("/internal/worker/legacy-") and request.method != "GET":
            from .orchestration import reject
            reject("按需部署不支持旧版接管写入协议", code="worker_capability_mismatch")
        return True

    def orchestration():
        from .orchestration import Orchestration
        return Orchestration(app.state.store)

    @app.get("/internal/worker/busy")
    @blocking_endpoint(app)
    def busy(request: Request, authorized=Depends(worker)):
        return {"busy": bool(app.state.store.one("SELECT 1 FROM jobs WHERE status='running' LIMIT 1")),
                "protocol_version": 2, "maintenance": app.state.store.maintenance_status()}

    @app.get("/internal/worker/pool/inventory")
    @blocking_endpoint(app)
    def pool_inventory(request: Request, authorized=Depends(protocol_worker)):
        from .runtime_pool import inventory_targets
        with app.state.store.read(snapshot=True) as db:
            return inventory_targets(db)

    @app.post("/internal/worker/pool/inventory")
    @blocking_endpoint(app, json_body=True)
    def pool_inventory_result(request: Request, authorized=Depends(protocol_worker)):
        from .runtime_pool import record_inventory
        return record_inventory(app.state.store, request.state.json_body)

    @app.post("/internal/worker/claim")
    @blocking_endpoint(app)
    def claim(request: Request, authorized=Depends(protocol_worker)):
        return orchestration().claim(runtime_spec)

    @app.post("/internal/worker/jobs/{jid}/heartbeat")
    @blocking_endpoint(app, json_body=True)
    def heartbeat(jid: str, request: Request, authorized=Depends(protocol_worker)):
        return orchestration().heartbeat(jid, request.state.json_body)

    @app.post('/internal/worker/scheduler/tick')
    @blocking_endpoint(app)
    def idle_tick(request: Request, authorized=Depends(protocol_worker)):
        from .idle_pool import candidates
        return candidates(app.state.store)

    @app.post('/internal/worker/scheduler/observe')
    @blocking_endpoint(app, json_body=True)
    def idle_observe(request: Request, authorized=Depends(protocol_worker)):
        from .idle_pool import submit
        return submit(app.state.store, request.state.json_body)

    @app.post('/internal/worker/jobs/{jid}/cancel-idle')
    @blocking_endpoint(app, json_body=True)
    def idle_cancel(jid: str, request: Request, authorized=Depends(protocol_worker)):
        return orchestration().cancel_idle(jid, request.state.json_body)

    @app.post("/internal/worker/jobs/{jid}/phase")
    @blocking_endpoint(app, json_body=True)
    def phase(jid: str, request: Request, authorized=Depends(protocol_worker)):
        return orchestration().phase(jid, request.state.json_body)

    @app.post("/internal/worker/jobs/{jid}/boot")
    @blocking_endpoint(app, json_body=True)
    def boot(jid: str, request: Request, authorized=Depends(protocol_worker)):
        return orchestration().boot(jid, request.state.json_body)

    @app.post("/internal/worker/jobs/{jid}/complete")
    @blocking_endpoint(app, json_body=True)
    def complete(jid: str, request: Request, authorized=Depends(protocol_worker)):
        return orchestration().complete(jid, request.state.json_body)

    @app.get("/internal/worker/jobs/{jid}")
    @blocking_endpoint(app)
    def job_query(jid: str, request: Request, attempt: int | None = None, operation_id: str | None = None,
                  authorized=Depends(protocol_worker)):
        return orchestration().query(jid, attempt, operation_id)

    @app.post("/internal/worker/observations")
    @blocking_endpoint(app, json_body=True)
    def observations(request: Request, authorized=Depends(protocol_worker)):
        return orchestration().observe(request.state.json_body)

    @app.get("/internal/worker/maintenance")
    @blocking_endpoint(app)
    def maintenance_status(request: Request, authorized=Depends(protocol_worker)):
        return app.state.store.maintenance_status()

    @app.post("/internal/worker/maintenance")
    @blocking_endpoint(app, json_body=True)
    def maintenance_update(request: Request, authorized=Depends(protocol_worker)):
        data = body_fields(request.state.json_body, ("maintenance_mode", "expected_state_version"))
        return app.state.store.set_maintenance(data.get("maintenance_mode"), data.get("expected_state_version"), "worker")

    @app.get("/internal/worker/reconcile")
    @blocking_endpoint(app)
    def reconcile_candidates(request: Request, limit: int | None = None, authorized=Depends(protocol_worker)):
        return orchestration().reconcile_candidates(limit)

    @app.post("/internal/worker/reconcile")
    @blocking_endpoint(app, json_body=True)
    def reconcile_observation(request: Request, authorized=Depends(protocol_worker)):
        return orchestration().reconcile(request.state.json_body)


    legacy_volumes = {
        "client-a": {"home_volume": "peixian-opencode_client-a-home",
                     "workspace_volume": "peixian-opencode_client-a-workspace"},
        "client-b": {"home_volume": "peixian-opencode_client-b-home",
                     "workspace_volume": "peixian-opencode_client-b-workspace"},
    }

    def legacy_account(db, uid):
        row = db.execute("SELECT u.username,u.role,r.* FROM users u JOIN runtimes r ON r.uid=u.id WHERE u.id=?", (uid,)).fetchone()
        if not row or row["role"] != "user" or row["username"] not in legacy_volumes:
            fail("迁移账号不存在", 404)
        if app.state.store.decrypt(row["spec"]).get("legacy") != legacy_volumes[row["username"]]:
            fail("账号不属于允许的旧环境迁移", 409)
        return row

    def import_record(db, uid, snapshot_id=None):
        for row in db.execute("SELECT target FROM audit WHERE action='legacy.import' ORDER BY created,rowid"):
            value = json.loads(row["target"])
            if value.get("uid") == uid and (snapshot_id is None or value.get("snapshot", {}).get("id") == snapshot_id):
                return value
        fail("迁移快照记录不存在", 404)

    @app.post("/internal/worker/legacy-import", status_code=202)
    @blocking_endpoint(app, json_body=True, hash_password=True)
    def legacy_import(request: Request, authorized=Depends(protocol_worker)):
        import re
        from .app import password_valid
        data = body_fields(request.state.json_body, ("username", "password", "model_ids", "legacy", "snapshot"))
        username = data.get("username")
        if not isinstance(username, str) or username not in legacy_volumes or data.get("legacy") != legacy_volumes[username]:
            fail("仅支持已核实的 client-a/client-b 固定旧卷", 400)
        password = password_valid(data.get("password"))
        models = data.get("model_ids", [])
        if not isinstance(models, list) or len(models) > 100 or any(not isinstance(value, str) for value in models):
            fail("授权模型格式不正确")
        snapshot = data.get("snapshot")
        if (not isinstance(snapshot, dict) or set(snapshot) != {"id", "sha256"}
                or not isinstance(snapshot["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot["id"])
                or not isinstance(snapshot["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot["sha256"])):
            fail("迁移快照标识或校验值无效")
        s = app.state.store
        existing = s.one("SELECT id FROM users WHERE username=?", (username,))
        created = False
        if existing is None:
            try:
                user, _ = s.create_user_prehashed(username, request.state.password_hash, legacy=legacy_volumes[username], model_ids=models)
                uid = user["id"]
                created = True
            except ValueError as exc:
                # A retry can race the first successful import. It may reuse only
                # the identical fixed legacy mapping, never overwrite the account.
                existing = s.one("SELECT id FROM users WHERE username=?", (username,))
                if existing is None:
                    fail(str(exc), 409)
                uid = existing["id"]
        else:
            uid = existing["id"]
        with s.tx() as db:
            runtime = legacy_account(db, uid)
            record = {"uid": uid, "runtime_id": runtime["id"], "username": username, "snapshot": snapshot}
            serialized = encode(record)
            previous = db.execute("SELECT target FROM audit WHERE action='legacy.import' AND target=?", (serialized,)).fetchone()
            if not previous:
                db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')", (ident(), "worker", "legacy.import", serialized, now()))
            result = {"uid": uid, "runtime_id": runtime["id"], "created": created,
                      "status": runtime["status"], "revision": runtime["revision"], "desired": runtime["desired"]}
        return result

    @app.get("/internal/worker/legacy-status/{uid}")
    @blocking_endpoint(app)
    def legacy_status(uid: str, request: Request, authorized=Depends(worker)):
        with app.state.store.read(snapshot=True) as db:
            row = legacy_account(db, own_id(uid))
            import_record(db, uid)
            return {"uid": uid, "runtime_id": row["id"], "status": row["status"],
                    "revision": row["revision"], "desired": row["desired"], "reserved": bool(row["reserved"]),
                    "state_version": row["state_version"], "gate_epoch": row["gate_epoch"]}

    @app.post("/internal/worker/legacy-rollback")
    @blocking_endpoint(app, json_body=True)
    def legacy_rollback(request: Request, authorized=Depends(protocol_worker)):
        data = body_fields(request.state.json_body, ("uid", "snapshot_id", "cleanup_confirmed", "observation_id", "expected_state_version", "operation_id"))
        if data.get("cleanup_confirmed") is not True:
            fail("执行器必须确认新环境已全部停止", 409)
        uid, snapshot_id = data.get("uid"), data.get("snapshot_id")
        if not isinstance(uid, str) or not isinstance(snapshot_id, str):
            fail("迁移标识无效")
        s = app.state.store
        with s.tx() as db:
            row = legacy_account(db, own_id(uid))
            record = import_record(db, uid, snapshot_id)
            if (type(data.get("expected_state_version")) is not int or not data.get("observation_id") or not data.get("operation_id")):
                fail("v4 回退必须提供当前核对证据和幂等操作标识", 409)
            if db.execute("SELECT 1 FROM jobs WHERE uid=? AND (status='running' OR recovery_required=1)", (uid,)).fetchone():
                fail("已有执行或恢复责任尚未结束，不能通过旧迁移接口释放", 409)
            if db.execute("SELECT 1 FROM capacity_release_receipts WHERE operation_id=?", (data["operation_id"],)).fetchone():
                s.release_capacity_and_promote(db, uid, expected_state_version=data["expected_state_version"], job_id=None, attempt=None,
                                              observation_id=data["observation_id"], operation_id=data["operation_id"])
                return {"ok": True, "uid": uid, "runtime_id": row["id"], "status": row["status"]}
            db.execute("UPDATE users SET active=0,auth_version=auth_version+1 WHERE id=?", (uid,))
            db.execute("DELETE FROM auth WHERE uid=?", (uid,))
            db.execute("UPDATE jobs SET status='failed',lease=NULL,heartbeat=NULL,error=?,updated=? WHERE uid=? AND status IN ('queued','running')",
                       ("迁移已由执行器回退", now(), uid))
            s.release_capacity_and_promote(db, uid, expected_state_version=data["expected_state_version"], job_id=None, attempt=None,
                                          observation_id=data["observation_id"], operation_id=data["operation_id"])
            db.execute("UPDATE runtimes SET status='failed',gate_policy='closed',error=?,updated=? WHERE uid=?",
                       ("迁移未完成，旧数据保留，请检查后重试", now(), uid))
            db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')",
                       (ident(), "worker", "legacy.rollback",
                        encode({"uid": uid, "runtime_id": row["id"], "snapshot": record["snapshot"], "cleanup_confirmed": True}), now()))
        return {"ok": True, "uid": uid, "runtime_id": row["id"], "status": "failed"}

    @app.post("/internal/worker/legacy-retry", status_code=202)
    @blocking_endpoint(app, json_body=True)
    def legacy_retry(request: Request, authorized=Depends(protocol_worker)):
        data = body_fields(request.state.json_body, ("uid", "snapshot_id", "legacy_stopped"))
        if data.get("legacy_stopped") is not True:
            fail("执行器必须确认旧服务和所有数据卷写入者均已停止", 409)
        uid, snapshot_id = data.get("uid"), data.get("snapshot_id")
        if not isinstance(uid, str) or not isinstance(snapshot_id, str):
            fail("迁移标识无效")
        s = app.state.store
        with s.tx() as db:
            uid = own_id(uid)
            user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
            if (not user or not runtime or user["role"] != "user" or user["username"] not in legacy_volumes
                    or s.decrypt(runtime["spec"]).get("legacy") != legacy_volumes[user["username"]]):
                fail("迁移账号不存在", 404)
            imported = import_record(db, uid, snapshot_id)
            if imported["runtime_id"] != runtime["id"]:
                fail("迁移记录与运行环境不一致", 409)
            history = []
            for audit in db.execute("SELECT action,target FROM audit WHERE action IN ('legacy.retry','legacy.rollback') ORDER BY created,rowid"):
                value = json.loads(audit["target"])
                if value.get("uid") == uid and value.get("runtime_id") == runtime["id"]:
                    history.append((audit["action"], value))
            repeats = [value for action, value in history
                       if action == "legacy.retry" and value.get("snapshot") == imported["snapshot"]]
            if repeats:
                previous = repeats[-1]
                job = db.execute("SELECT * FROM jobs WHERE id=? AND uid=?", (previous.get("job_id"), uid)).fetchone()
                latest = db.execute("SELECT id FROM jobs WHERE uid=? ORDER BY created DESC,rowid DESC LIMIT 1", (uid,)).fetchone()
                if (not user["active"] or user["auth_version"] != previous.get("auth_version")
                        or not history or history[-1] != ("legacy.retry", previous)
                        or not job or not latest or latest["id"] != job["id"]
                        or job["status"] not in ("queued", "running", "succeeded")
                        or runtime["status"] not in ("provisioning", "ready")):
                    fail("该迁移重试已结束或账号状态已变更，请重新建立快照", 409)
            else:
                if not any(action == "legacy.rollback" and value.get("cleanup_confirmed") is True
                           for action, value in history):
                    fail("该账号没有可重试的迁移回退记录", 409)
                if (user["active"] or runtime["status"] != "failed" or runtime["reserved"]
                        or db.execute("SELECT 1 FROM jobs WHERE uid=? AND status IN ('queued','running')", (uid,)).fetchone()):
                    fail("当前环境状态不允许迁移重试", 409)
                try:
                    job = s.queue_in_transaction(db, uid, "resume")
                except ValueError as exc:
                    fail(str(exc), 409)
                db.execute("UPDATE users SET active=1,auth_version=auth_version+1 WHERE id=?", (uid,))
                db.execute("DELETE FROM auth WHERE uid=?", (uid,))
                db.execute("INSERT INTO audit(id,actor,action,target,created,actor_role) VALUES(?,?,?,?,?,'worker')",
                           (ident(), "worker", "legacy.retry",
                            encode({"uid": uid, "runtime_id": runtime["id"], "snapshot": imported["snapshot"],
                                    "job_id": job["id"], "auth_version": user["auth_version"] + 1,
                                    "legacy_stopped": True}), now()))
            current = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
            return {"uid": uid, "runtime_id": current["id"], "status": current["status"],
                    "revision": current["revision"], "desired": current["desired"], "job_id": job["id"]}

    @app.get("/internal/worker/packages/{sha}")
    @blocking_endpoint(app)
    def package(sha: str, request: Request, authorized=Depends(worker)):
        import re
        if not re.fullmatch("[a-f0-9]{64}", sha):
            fail("包不存在", 404)
        path = app.state.store.root / "packages" / (sha + ".zip")
        if not path.is_file() or path.is_symlink():
            fail("包不存在", 404)
        return FileResponse(path, media_type="application/zip")
