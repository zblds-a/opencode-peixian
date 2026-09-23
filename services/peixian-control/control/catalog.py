from .concurrency import blocking_endpoint
import json
import re

import jsonschema
from fastapi import Depends, Request

from .store import ident, encode
from .plugin_schema import redact, merge_secrets
from .connections import resolved_bindings


def register_catalog(app):
    from .app import PREFIX, normal, body_fields, fail, own_id, upstream

    def changed(uid):
        try:
            return app.state.store.queue(uid)
        except ValueError as exc:
            fail(str(exc), 409)

    def skill_data(data, old=None):
        body_fields(data, ("name", "description", "content", "enabled", "dependency_ids"))
        result = {**(old or {}), **data}
        if not isinstance(result.get("name"), str) or not re.fullmatch(r"[^/\\\r\n\x00]{1,60}", result["name"]):
            fail("技能名称应为 1 至 60 个字符，不能包含路径或换行")
        if not isinstance(result.get("content"), str) or not 1 <= len(result["content"]) <= 32000:
            fail("技能指令应为 1 至 32000 个字符")
        result["description"] = str(result.get("description", ""))[:500]
        result["enabled"] = bool(result.get("enabled", True))
        return result

    @app.get(PREFIX + "/skills")
    @blocking_endpoint(app)
    def skills(request: Request, user=Depends(normal)):
        s=app.state.store
        values=s.rows("SELECT id,name,description,content,enabled,version FROM skills WHERE uid=? ORDER BY name", (user["uid"],))
        if s.schema_version()>=6:
            from .capabilities import dependencies
            with s.read() as db:
                for value in values:value['dependency_ids']=dependencies(db,value['id'])
        return {"items":values}

    @app.post(PREFIX + "/skills")
    @blocking_endpoint(app, json_body=True)
    def skill_create(request: Request, user=Depends(normal)):
        data = skill_data(request.state.json_body)
        sid = ident()
        s = app.state.store
        with s.tx() as db:
            if db.execute("SELECT 1 FROM skills WHERE uid=? AND name=?", (user["uid"], data["name"])).fetchone():
                fail("你已有同名技能，请修改名称", 409)
            db.execute("INSERT INTO skills VALUES(?,?,?,?,?,?,1,'[]')", (sid, user["uid"], data["name"], data["description"], data["content"], data["enabled"]))
            if 'dependency_ids' in data:
                from .capabilities import save_dependencies
                from .backend_contract import require_v6
                require_v6(s);save_dependencies(db,user['uid'],sid,data)
        return {"id": sid, **data, "version": 1, "job": changed(user["uid"])}

    @app.patch(PREFIX + "/skills/{sid}")
    @blocking_endpoint(app, json_body=True)
    def skill_edit(sid: str, request: Request, user=Depends(normal)):
        s = app.state.store
        with s.tx() as db:
            row = db.execute("SELECT * FROM skills WHERE id=? AND uid=?", (own_id(sid), user["uid"])).fetchone()
            old = dict(row) if row else None
            if not old:
                fail("技能不存在", 404)
            data = skill_data(request.state.json_body, old)
            history = json.loads(old["history"])
            if s.schema_version()>=6:
                from .capabilities import dependencies
                old['dependency_ids']=dependencies(db,sid)
            history.append({k: old[k] for k in ("name", "description", "content", "enabled", "version", "dependency_ids") if k in old})
            if db.execute("SELECT 1 FROM skills WHERE uid=? AND name=? AND id<>?", (user["uid"], data["name"], sid)).fetchone():
                fail("你已有同名技能", 409)
            db.execute("UPDATE skills SET name=?,description=?,content=?,enabled=?,version=version+1,history=? WHERE id=? AND uid=?", (data["name"], data["description"], data["content"], data["enabled"], encode(history[-20:]), sid, user["uid"]))
            if 'dependency_ids' in data:
                from .capabilities import save_dependencies
                from .backend_contract import require_v6
                require_v6(s);save_dependencies(db,user['uid'],sid,data)
        return {"ok": True, "job": changed(user["uid"])}

    @app.delete(PREFIX + "/skills/{sid}")
    @blocking_endpoint(app)
    def skill_delete(sid: str, request: Request, user=Depends(normal)):
        with app.state.store.tx() as db:
            count = db.execute("DELETE FROM skills WHERE id=? AND uid=?", (own_id(sid), user["uid"])).rowcount
            if not count:
                fail("技能不存在", 404)
        return {"ok": True, "job": changed(user["uid"])}

    @app.post(PREFIX + "/skills/{sid}/rollback")
    @blocking_endpoint(app)
    def skill_rollback(sid: str, request: Request, user=Depends(normal)):
        s = app.state.store
        with s.tx() as db:
            row = db.execute("SELECT * FROM skills WHERE id=? AND uid=?", (own_id(sid), user["uid"])).fetchone()
            old = dict(row) if row else None
            if not old:
                fail("技能不存在", 404)
            history = json.loads(old["history"])
            if not history:
                fail("暂无可恢复的历史版本", 409)
            previous = history.pop()
            if s.schema_version()>=6:
                from .capabilities import save_dependencies
                save_dependencies(db,user['uid'],sid,{'dependency_ids':previous.get('dependency_ids',[])})
            if db.execute("SELECT 1 FROM skills WHERE uid=? AND name=? AND id<>?", (user["uid"], previous["name"], sid)).fetchone():
                fail("原技能名称已被使用，请先修改同名技能后再恢复", 409)
            db.execute("UPDATE skills SET name=?,description=?,content=?,enabled=?,version=version+1,history=? WHERE id=?", (previous["name"], previous["description"], previous["content"], previous["enabled"], encode(history), sid))
        return {"ok": True, "job": changed(user["uid"])}

    @app.post(PREFIX + "/skills/{sid}/test")
    async def skill_test(sid: str, request: Request, user=Depends(normal)):
        skill = await app.state.db_work.run(app.state.store.one, "SELECT * FROM skills WHERE id=? AND uid=?", (own_id(sid), user["uid"]))
        if not skill:
            fail("技能不存在", 404)
        values = (await upstream(request, user, "GET", "/skill")).json()
        loaded = any(v.get("name") == skill["name"] for v in values)
        return {"ok": loaded, "message": "技能已加载，可在新对话中选择使用" if loaded else "技能尚未生效，请等待配置应用完成"}

    @app.get(PREFIX + "/templates")
    @blocking_endpoint(app)
    def templates(request: Request, user=Depends(normal)):
        return {"items": app.state.store.rows("SELECT * FROM templates ORDER BY name")}

    @app.post(PREFIX + "/templates/{tid}/copy")
    @blocking_endpoint(app)
    def template_copy(tid: str, request: Request, user=Depends(normal)):
        s = app.state.store
        template = s.one("SELECT * FROM templates WHERE id=?", (own_id(tid),))
        if not template:
            fail("模板不存在", 404)
        sid = ident()
        name = template["name"]
        with s.tx() as db:
            if db.execute("SELECT 1 FROM skills WHERE uid=? AND name=?", (user["uid"], name)).fetchone():
                name = name[:50] + "-" + sid[:6]
            from .official_methods import identify
            from .capabilities import save_dependencies
            method=identify(template['content'])
            if method and method['state']!='published':fail('该官方方法尚未发布或已停用',409)
            db.execute("INSERT INTO skills VALUES(?,?,?,?,?,1,1,'[]')", (sid, user["uid"], name, template["description"], template["content"]))
            if method:save_dependencies(db,user['uid'],sid,{'dependency_ids':method['dependency_ids']})
        return {"id": sid, "job": changed(user["uid"])}

    def published(uid, pid, version=None, db=None):
        from .data_plugin_policy import installable
        if not installable(pid):
            fail("该资料插件已归档，不可安装或调用", 404)
        s = app.state.store
        def one(query, params):
            if db is None:
                return s.one(query, params)
            row = db.execute(query, params).fetchone()
            return dict(row) if row else None
        if not one("SELECT 1 FROM grants WHERE uid=? AND kind='plugin' AND resource=?", (uid, pid)):
            fail("插件不存在或未获授权", 404)
        if version:
            item = one("SELECT * FROM plugins WHERE id=? AND version=? AND enabled=1", (pid, version))
        else:
            item = one("SELECT * FROM plugins WHERE id=? AND enabled=1 ORDER BY rowid DESC LIMIT 1", (pid,))
        if not item:
            fail("插件版本不可用", 404)
        return item

    @app.get(PREFIX + "/plugins")
    @blocking_endpoint(app)
    def plugins(request: Request, user=Depends(normal)):
        s = app.state.store
        grants = s.rows("SELECT resource FROM grants WHERE uid=? AND kind='plugin'", (user["uid"],))
        items = []
        from .data_plugin_policy import installable
        for grant in grants:
            if not installable(grant["resource"]):
                continue
            versions = s.rows("SELECT * FROM plugins WHERE id=? AND enabled=1 ORDER BY rowid DESC", (grant["resource"],))
            if not versions:
                continue
            p = versions[0]
            manifest = json.loads(p["manifest"])
            item = {k: p[k] for k in ("id", "version", "name", "description")}
            item.update(schemas={v["version"]: json.loads(v["manifest"]).get("config_schema", {}) for v in versions}, versions=[v["version"] for v in versions], config_schema=manifest.get("config_schema", {"type": "object", "properties": {}}), installed=None)
            with s.read(snapshot=True) as db:
                item["connection_status"] = {}
                for version in versions:
                    _, missing = resolved_bindings(db, p["id"], version["version"], json.loads(version["manifest"]))
                    item["connection_status"][version["version"]] = {"ready": not missing, "missing": missing}
            install = s.one("SELECT * FROM installs WHERE uid=? AND plugin=?", (user["uid"], p["id"]))
            if install:
                config = s.decrypt(install["config"])
                definition = s.one("SELECT manifest,enabled FROM plugins WHERE id=? AND version=?", (install["plugin"], install["version"])) or {"manifest": "{}", "enabled": 0}
                properties = json.loads(definition["manifest"]).get("config_schema", {}).get("properties", {})
                safe, confidential = redact(json.loads(definition["manifest"]).get("config_schema", {}), config)
                confidential = confidential or {}
                state = s.one("SELECT status,revision,desired FROM runtimes WHERE uid=?", (user["uid"],))
                item["installed"] = {"version": install["version"], "enabled": bool(install["enabled"]), "config": safe, "credentials_configured": confidential, "state": "unavailable" if not definition["enabled"] else ("active" if state and state["revision"] == state["desired"] and state["status"] == "ready" else "pending")}
                missing = item["connection_status"].get(install["version"], {}).get("missing", [])
                item["installed"]["missing_connections"] = missing
                if missing and definition["enabled"]:
                    item["installed"]["state"] = "unconfigured"
            items.append(item)
        return {"items": items}

    @app.put(PREFIX + "/plugins/{pid}")
    @blocking_endpoint(app, json_body=True)
    def install(pid: str, request: Request, user=Depends(normal)):
        data = body_fields(request.state.json_body, ("version", "enabled", "config"))
        s = app.state.store
        with s.tx() as db:
            p = published(user["uid"], own_id(pid), data.get("version"), db=db)
            manifest = json.loads(p["manifest"])
            old = db.execute("SELECT * FROM installs WHERE uid=? AND plugin=?", (user["uid"], pid)).fetchone()
            config = data.get("config", {})
            if not isinstance(config, dict):
                fail("插件参数格式不正确")
            if old:
                config = merge_secrets(manifest.get("config_schema", {}), config, s.decrypt(old["config"]))
            try:
                jsonschema.validate(config, manifest.get("config_schema", {"type": "object"}))
            except jsonschema.ValidationError:
                fail("插件参数不完整或格式不正确，请按表单提示填写")
            previous = s.encrypt({"version": old["version"], "enabled": old["enabled"], "config": s.decrypt(old["config"])}) if old else None
            db.execute("INSERT OR REPLACE INTO installs VALUES(?,?,?,?,?,?)", (user["uid"], pid, p["version"], bool(data.get("enabled", True)), s.encrypt(config), previous))
        s.audit(user["uid"], "plugin.configure", pid)
        return {"ok": True, "job": changed(user["uid"])}

    @app.post(PREFIX + "/plugins/{pid}/rollback")
    @blocking_endpoint(app)
    def plugin_rollback(pid: str, request: Request, user=Depends(normal)):
        s = app.state.store
        with s.tx() as db:
            old = db.execute("SELECT * FROM installs WHERE uid=? AND plugin=?", (user["uid"], own_id(pid))).fetchone()
            if not old or not old["previous"]:
                fail("暂无可恢复的插件版本", 409)
            previous = s.decrypt(old["previous"])
            published(user["uid"], pid, previous["version"], db=db)
            db.execute("UPDATE installs SET version=?,enabled=?,config=?,previous=NULL WHERE uid=? AND plugin=?", (previous["version"], previous["enabled"], s.encrypt(previous["config"]), user["uid"], pid))
        return {"ok": True, "job": changed(user["uid"])}

    @app.post(PREFIX + "/plugins/{pid}/test")
    async def plugin_test(pid: str, request: Request, user=Depends(normal)):
        def prepare():
            s = app.state.store
            item = s.one("SELECT * FROM installs WHERE uid=? AND plugin=?", (user["uid"], own_id(pid)))
            if not item:
                fail("请先安装并保存插件配置", 409)
            published(user["uid"], pid, item["version"])
            with s.read(snapshot=True) as db:
                manifest = db.execute("SELECT manifest FROM plugins WHERE id=? AND version=?", (pid, item["version"])).fetchone()
                _, missing = resolved_bindings(db, pid, item["version"], json.loads(manifest["manifest"]))
            if missing:
                return {"ok": False, "message": "平台服务连接尚未配置或已停用，请联系超级管理员", "connection_tested": False}
            r = s.one("SELECT status,revision,desired FROM runtimes WHERE uid=?", (user["uid"],))
            applied = r and r["revision"] == r["desired"] and r["status"] == "ready"
            if not applied:
                return {"ok": False, "message": "配置已保存，等待运行环境应用", "connection_tested": False}
            return None
        pending = await app.state.db_work.run(prepare)
        if pending is not None:
            return pending
        return (await upstream(request, user, "POST", f"/plugins/{pid}/test", json={})).json()
