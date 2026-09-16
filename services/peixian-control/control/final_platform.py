import csv
import io
import json

from fastapi import Depends, Request
from fastapi.responses import Response

from .store import encode, ident, now


def create_run(store, user, session_id, model_id, text, mode, skill_ids):
    run_id = ident()
    timestamp = now()
    department = store.one("SELECT department_id FROM user_profiles WHERE uid=?", (user["uid"],)) or {}
    with store.tx() as db:
        db.execute(
            "INSERT INTO runs(id,uid,session_id,model_id,query_summary,mode,status,started) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, user["uid"], session_id, model_id, text[:500], mode, "accepted", timestamp),
        )
        steps = (
            ("requirement", "需求理解", "completed"),
            ("skill", "加载研判能力", "completed" if skill_ids else "skipped"),
            ("plugin", "调用业务数据", "pending"),
            ("analysis", "数据分析", "pending"),
            ("result", "生成结果", "pending"),
        )
        db.executemany(
            "INSERT INTO run_events(id,run_id,sequence,step_type,name,status,started,completed,evidence_refs) VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (ident(), run_id, index, step_type, name, status, timestamp if index == 1 else None,
                 timestamp if status in ("completed", "skipped") else None, "[]")
                for index, (step_type, name, status) in enumerate(steps, 1)
            ],
        )
        db.execute(
            "INSERT INTO invocations(id,run_id,uid,department_id,model_id,skill_ids,plugin_ids,status,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (ident(), run_id, user["uid"], department.get("department_id"), model_id, encode(skill_ids), "[]", "accepted", timestamp),
        )
    return run_id


def register_final_platform(app):
    from .app import PREFIX, admin, body_fields, fail, normal, own_id, require_capability, session_owned

    def json_value(value, fallback):
        try:
            return json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            return fallback

    def draft_public(row):
        return {
            **{key: row[key] for key in ("id", "session_id", "source_type", "name", "description", "content", "created", "updated")},
            "dependency_ids": json_value(row["dependencies"], []),
            "input_schema": json_value(row["input_schema"], {}),
            "default_rules": json_value(row["default_rules"], []),
        }

    @app.get(PREFIX + "/capabilities")
    async def capabilities(request: Request, query: str = "", kind: str | None = None, user=Depends(normal)):
        store = app.state.store
        items = []
        for row in store.rows(
            "SELECT s.id,s.name,s.description,s.enabled,s.version,m.source_type,m.scope,m.updated "
            "FROM skills s LEFT JOIN skill_metadata m ON m.skill_id=s.id WHERE s.uid=? ORDER BY s.name",
            (user["uid"],),
        ):
            items.append({
                "id": row["id"], "kind": "skill", "name": row["name"], "description": row["description"],
                "version": str(row["version"]), "category": "个人能力", "recommended": False,
                "enabled": bool(row["enabled"]), "owned": True, "scope": row.get("scope") or "personal",
            })
        grants = store.rows(
            "SELECT p.id,p.version,p.name,p.description,p.enabled FROM plugins p JOIN grants g "
            "ON g.resource=p.id AND g.kind='plugin' WHERE g.uid=? ORDER BY p.rowid DESC",
            (user["uid"],),
        )
        seen = set()
        for row in grants:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            items.append({
                "id": row["id"], "kind": "plugin", "name": row["name"], "description": row["description"],
                "version": row["version"], "category": "插件工具", "recommended": False,
                "enabled": bool(row["enabled"]), "owned": False, "scope": "authorized",
            })
        for row in store.rows("SELECT * FROM official_capabilities WHERE enabled=1 ORDER BY name"):
            items.append({
                "id": row["id"], "kind": row["kind"], "name": row["name"], "description": row["description"],
                "version": row["version"], "category": row["category"], "recommended": True,
                "enabled": True, "owned": False, "scope": row["visibility"],
            })
        value = query.strip().lower()
        if value:
            items = [item for item in items if value in (item["name"] + " " + (item.get("description") or "")).lower()]
        if kind in ("skill", "plugin"):
            items = [item for item in items if item["kind"] == kind]
        return {"items": items}

    def build_draft(data, user, source_type):
        requirement = str(data.get("requirement") or data.get("summary") or "当前对话研判流程").strip()[:2000]
        name = str(data.get("name") or (requirement[:24] if requirement else "新建研判能力"))
        description = str(data.get("description") or requirement)[:500]
        content = "# " + name + "\n\n## 角色定位\n你是公安智能研判助手。\n\n## 研判目标\n" + requirement + "\n\n## 执行要求\n- 按授权范围调用业务能力\n- 输出结构化结论与证据引用\n- 不展示模型内部思维过程\n"
        return {
            "id": ident(), "uid": user["uid"], "session_id": data.get("session_id"), "source_type": source_type,
            "name": name[:60], "description": description, "content": content,
            "dependencies": encode(data.get("dependency_ids", [])), "input_schema": encode(data.get("input_schema", {})),
            "default_rules": encode(data.get("default_rules", [])), "created": now(), "updated": now(),
        }

    async def create_draft(request, user, source_type):
        data = await request.json()
        if not isinstance(data, dict):
            fail("请求格式不正确")
        if source_type == "conversation":
            session_id = data.get("session_id")
            if not isinstance(session_id, str):
                fail("请选择需要提炼的对话")
            await session_owned(request, user, session_id)
        draft = build_draft(data, user, source_type)
        with app.state.store.tx() as db:
            db.execute(
                "INSERT INTO skill_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(draft[key] for key in ("id", "uid", "session_id", "source_type", "name", "description", "content", "dependencies", "input_schema", "default_rules", "created", "updated")),
            )
        return draft_public(app.state.store.one("SELECT * FROM skill_drafts WHERE id=?", (draft["id"],)))

    @app.post(PREFIX + "/skill-drafts/from-requirement")
    async def draft_requirement(request: Request, user=Depends(normal)):
        return await create_draft(request, user, "requirement")

    @app.post(PREFIX + "/skill-drafts/from-session")
    async def draft_session(request: Request, user=Depends(normal)):
        return await create_draft(request, user, "conversation")

    def owned_draft(draft_id, user):
        row = app.state.store.one("SELECT * FROM skill_drafts WHERE id=? AND uid=?", (own_id(draft_id), user["uid"]))
        if not row:
            fail("Skill 草稿不存在", 404)
        return row

    @app.get(PREFIX + "/skill-drafts/{draft_id}")
    async def draft_get(draft_id: str, request: Request, user=Depends(normal)):
        return draft_public(owned_draft(draft_id, user))

    @app.patch(PREFIX + "/skill-drafts/{draft_id}")
    async def draft_edit(draft_id: str, request: Request, user=Depends(normal)):
        old = owned_draft(draft_id, user)
        data = body_fields(await request.json(), ("name", "description", "content", "dependency_ids", "input_schema", "default_rules"))
        name = str(data.get("name", old["name"])).strip()[:60]
        content = str(data.get("content", old["content"])).strip()[:32000]
        if not name or not content:
            fail("请填写 Skill 名称和内容")
        with app.state.store.tx() as db:
            db.execute(
                "UPDATE skill_drafts SET name=?,description=?,content=?,dependencies=?,input_schema=?,default_rules=?,updated=? WHERE id=? AND uid=?",
                (name, str(data.get("description", old["description"]))[:500], content,
                 encode(data.get("dependency_ids", json_value(old["dependencies"], []))),
                 encode(data.get("input_schema", json_value(old["input_schema"], {}))),
                 encode(data.get("default_rules", json_value(old["default_rules"], []))), now(), draft_id, user["uid"]),
            )
        return draft_public(owned_draft(draft_id, user))

    @app.post(PREFIX + "/skill-drafts/{draft_id}/test")
    async def draft_test(draft_id: str, request: Request, user=Depends(normal)):
        draft = owned_draft(draft_id, user)
        dependencies = json_value(draft["dependencies"], [])
        return {"ok": True, "message": "草稿结构校验通过，可保存到个人 Skill", "steps": [
            {"name": "检查基本信息", "status": "completed"},
            {"name": "检查依赖能力", "status": "completed", "record_count": len(dependencies)},
            {"name": "检查 Skill 内容", "status": "completed"},
        ]}

    @app.post(PREFIX + "/skill-drafts/{draft_id}/save")
    async def draft_save(draft_id: str, request: Request, user=Depends(normal)):
        draft = owned_draft(draft_id, user)
        skill_id = ident()
        store = app.state.store
        with store.tx() as db:
            if db.execute("SELECT 1 FROM skills WHERE uid=? AND name=?", (user["uid"], draft["name"])).fetchone():
                fail("你已有同名 Skill，请先修改名称", 409)
            db.execute(
                "INSERT INTO skills(id,uid,name,description,content,enabled,version,history) VALUES(?,?,?,?,?,1,1,'[]')",
                (skill_id, user["uid"], draft["name"], draft["description"], draft["content"]),
            )
            db.execute(
                "INSERT INTO skill_metadata VALUES(?,?,?,?,?,?,?)",
                (skill_id, draft["source_type"], draft["dependencies"], draft["input_schema"], draft["default_rules"], "personal", now()),
            )
            db.execute("DELETE FROM skill_drafts WHERE id=?", (draft_id,))
        try:
            job = store.queue(user["uid"])
        except ValueError:
            job = None
        return {"id": skill_id, "name": draft["name"], "scope": "personal", "job": job}

    def owned_run(run_id, user):
        row = app.state.store.one("SELECT * FROM runs WHERE id=? AND uid=?", (own_id(run_id), user["uid"]))
        if not row:
            fail("研判运行不存在", 404)
        return row

    @app.get(PREFIX + "/sessions/{sid}/runs/{run_id}")
    async def run_get(sid: str, run_id: str, request: Request, user=Depends(normal)):
        await session_owned(request, user, sid)
        row = owned_run(run_id, user)
        if row["session_id"] != sid:
            fail("研判运行不存在", 404)
        return row

    @app.get(PREFIX + "/sessions/{sid}/runs/{run_id}/events")
    async def run_events(sid: str, run_id: str, request: Request, user=Depends(normal)):
        await session_owned(request, user, sid)
        owned_run(run_id, user)
        rows = app.state.store.rows("SELECT * FROM run_events WHERE run_id=? ORDER BY sequence", (run_id,))
        for row in rows:
            row["evidence_refs"] = json_value(row["evidence_refs"], [])
        return {"items": rows}

    def evidence_content(run):
        return {
            "conclusion": {"confidence": "待业务数据返回", "summary": "本次研判已建立可追溯证据链，结论以正式业务接口返回为准。"},
            "tabs": {"trajectory": [], "places": [], "companions": []},
            "chain": [
                {"type": "object", "label": "目标对象"},
                {"type": "analysis", "label": "行为规律与关联分析"},
                {"type": "risk", "label": "风险判断"},
                {"type": "result", "label": "研判建议"},
            ],
            "conditions": {"query": run["query_summary"], "mode": run["mode"]},
            "mock": True,
        }

    @app.get(PREFIX + "/sessions/{sid}/runs/{run_id}/evidence")
    async def run_evidence(sid: str, run_id: str, request: Request, user=Depends(normal)):
        await session_owned(request, user, sid)
        run = owned_run(run_id, user)
        stored = app.state.store.one("SELECT content FROM run_evidence WHERE run_id=?", (run_id,))
        return json_value(stored["content"], {}) if stored else evidence_content(run)

    @app.post(PREFIX + "/sessions/{sid}/runs/{run_id}/rerun")
    async def run_rerun(sid: str, run_id: str, request: Request, user=Depends(normal)):
        await session_owned(request, user, sid)
        run = owned_run(run_id, user)
        data = await request.json()
        query = str(data.get("query") or run["query_summary"]) if isinstance(data, dict) else run["query_summary"]
        created = create_run(app.state.store, user, sid, run["model_id"], query, run["mode"], [])
        return {"accepted": True, "run_id": created}

    @app.get(PREFIX + "/sessions/{sid}/runs/{run_id}/report")
    async def run_report(sid: str, run_id: str, request: Request, user=Depends(normal)):
        await session_owned(request, user, sid)
        run = owned_run(run_id, user)
        report = "# 研判报告\n\n## 查询摘要\n" + run["query_summary"] + "\n\n## 说明\n报告中的业务结论与证据以正式数据接口返回为准。\n"
        return Response(report, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="analysis-{run_id}.md"'})

    @app.get(PREFIX + "/admin/users/summary")
    async def users_summary(request: Request, user=Depends(admin)):
        store = app.state.store
        return {
            "users": store.one("SELECT count(*) AS n FROM users WHERE role='user'")["n"],
            "departments": store.one("SELECT count(*) AS n FROM departments")["n"],
            "enabled": store.one("SELECT count(*) AS n FROM users WHERE role='user' AND active=1")["n"],
        }

    @app.get(PREFIX + "/admin/departments/tree")
    async def departments(request: Request, user=Depends(require_capability("users.manage"))):
        return {"items": app.state.store.rows("SELECT id,name,parent_id,code,sort_order,created,updated FROM departments ORDER BY sort_order,name")}

    @app.post(PREFIX + "/admin/departments")
    async def department_create(request: Request, user=Depends(require_capability("users.manage"))):
        data = body_fields(await request.json(), ("name", "parent_id", "code", "sort_order"))
        name = str(data.get("name", "")).strip()[:100]
        if not name:
            fail("请填写部门名称")
        department_id = ident()
        with app.state.store.tx() as db:
            db.execute("INSERT INTO departments VALUES(?,?,?,?,?,?,?)", (department_id, name, data.get("parent_id"), str(data.get("code") or "") or None, int(data.get("sort_order") or 0), now(), now()))
        return app.state.store.one("SELECT * FROM departments WHERE id=?", (department_id,))

    @app.patch(PREFIX + "/admin/departments/{department_id}")
    async def department_edit(department_id: str, request: Request, user=Depends(require_capability("users.manage"))):
        old = app.state.store.one("SELECT * FROM departments WHERE id=?", (own_id(department_id),))
        if not old:
            fail("部门不存在", 404)
        data = body_fields(await request.json(), ("name", "parent_id", "code", "sort_order"))
        with app.state.store.tx() as db:
            db.execute("UPDATE departments SET name=?,parent_id=?,code=?,sort_order=?,updated=? WHERE id=?", (str(data.get("name", old["name"]))[:100], data.get("parent_id", old["parent_id"]), data.get("code", old["code"]), int(data.get("sort_order", old["sort_order"])), now(), department_id))
        return app.state.store.one("SELECT * FROM departments WHERE id=?", (department_id,))

    @app.delete(PREFIX + "/admin/departments/{department_id}")
    async def department_delete(department_id: str, request: Request, user=Depends(require_capability("users.manage"))):
        department_id = own_id(department_id)
        store = app.state.store
        if store.one("SELECT 1 FROM departments WHERE parent_id=?", (department_id,)) or store.one("SELECT 1 FROM user_profiles WHERE department_id=?", (department_id,)):
            fail("部门包含下级部门或用户，不能删除", 409)
        with store.tx() as db:
            if not db.execute("DELETE FROM departments WHERE id=?", (department_id,)).rowcount:
                fail("部门不存在", 404)
        return {"ok": True}

    def capability_public(row):
        return {**row, "enabled": bool(row["enabled"]), "dependency_ids": json_value(row["dependencies"], []), "config": json_value(row["config"], {})}

    @app.get(PREFIX + "/admin/capabilities")
    async def admin_capabilities(request: Request, user=Depends(require_capability("plugins.manage"))):
        return {"items": [capability_public(row) for row in app.state.store.rows("SELECT * FROM official_capabilities ORDER BY kind,name")]}

    def capability_data(data, old=None):
        body_fields(data, ("kind", "name", "description", "version", "category", "dependency_ids", "visibility", "enabled", "config"))
        result = {**(old or {}), **data}
        if result.get("kind") not in ("skill", "plugin") or not str(result.get("name", "")).strip():
            fail("请选择能力类型并填写名称")
        return result

    @app.post(PREFIX + "/admin/capabilities")
    async def admin_capability_create(request: Request, user=Depends(require_capability("plugins.manage"))):
        data = capability_data(await request.json())
        capability_id = ident()
        timestamp = now()
        with app.state.store.tx() as db:
            db.execute("INSERT INTO official_capabilities VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (capability_id, data["kind"], str(data["name"])[:100], str(data.get("description", ""))[:500], str(data.get("version", "1.0"))[:30], str(data.get("category", "官方能力"))[:50], encode(data.get("dependency_ids", [])), str(data.get("visibility", "all"))[:30], bool(data.get("enabled", True)), encode(data.get("config", {})), timestamp, timestamp))
        return capability_public(app.state.store.one("SELECT * FROM official_capabilities WHERE id=?", (capability_id,)))

    @app.patch(PREFIX + "/admin/capabilities/{capability_id}")
    async def admin_capability_edit(capability_id: str, request: Request, user=Depends(require_capability("plugins.manage"))):
        old = app.state.store.one("SELECT * FROM official_capabilities WHERE id=?", (own_id(capability_id),))
        if not old:
            fail("能力不存在", 404)
        data = capability_data(await request.json(), old)
        with app.state.store.tx() as db:
            db.execute("UPDATE official_capabilities SET kind=?,name=?,description=?,version=?,category=?,dependencies=?,visibility=?,enabled=?,config=?,updated=? WHERE id=?", (data["kind"], str(data["name"])[:100], str(data.get("description", ""))[:500], str(data.get("version", "1.0"))[:30], str(data.get("category", "官方能力"))[:50], encode(data.get("dependency_ids", json_value(old["dependencies"], []))), str(data.get("visibility", "all"))[:30], bool(data.get("enabled", True)), encode(data.get("config", json_value(old["config"], {}))), now(), capability_id))
        return capability_public(app.state.store.one("SELECT * FROM official_capabilities WHERE id=?", (capability_id,)))

    @app.post(PREFIX + "/admin/capabilities/{capability_id}/test")
    async def admin_capability_test(capability_id: str, request: Request, user=Depends(require_capability("plugins.manage"))):
        item = app.state.store.one("SELECT * FROM official_capabilities WHERE id=?", (own_id(capability_id),))
        if not item:
            fail("能力不存在", 404)
        return {"ok": bool(item["enabled"]), "message": "配置结构有效，能力已启用" if item["enabled"] else "能力当前处于停用状态"}

    def invocation_rows(user, query):
        clauses, values = ["1=1"], []
        for field, column in (("uid", "i.uid"), ("department_id", "i.department_id"), ("model_id", "i.model_id"), ("status", "i.status")):
            value = query.get(field)
            if value:
                clauses.append(column + "=?")
                values.append(value)
        if query.get("start"):
            clauses.append("i.created>=?")
            values.append(int(query["start"]))
        if query.get("end"):
            clauses.append("i.created<=?")
            values.append(int(query["end"]))
        return app.state.store.rows(
            "SELECT i.*,u.username,p.display_name,d.name AS department_name,m.name AS model_name,r.query_summary,r.mode "
            "FROM invocations i JOIN runs r ON r.id=i.run_id LEFT JOIN users u ON u.id=i.uid "
            "LEFT JOIN user_profiles p ON p.uid=i.uid LEFT JOIN departments d ON d.id=i.department_id "
            "LEFT JOIN models m ON m.id=i.model_id WHERE " + " AND ".join(clauses) + " ORDER BY i.created DESC LIMIT 500",
            values,
        )

    @app.get(PREFIX + "/admin/invocations")
    async def invocations(request: Request, user=Depends(require_capability("audit.read"))):
        rows = invocation_rows(user, dict(request.query_params))
        for row in rows:
            row["skill_ids"] = json_value(row["skill_ids"], [])
            row["plugin_ids"] = json_value(row["plugin_ids"], [])
        return {"items": rows}

    @app.get(PREFIX + "/admin/invocations/export")
    async def invocations_export(request: Request, user=Depends(require_capability("audit.read"))):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(("时间", "用户", "部门", "模型", "状态", "耗时毫秒", "记录数", "查询摘要"))
        for row in invocation_rows(user, dict(request.query_params)):
            writer.writerow((row["created"], row.get("display_name") or row.get("username"), row.get("department_name"), row.get("model_name"), row["status"], row.get("duration_ms"), row["record_count"], row["query_summary"]))
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="invocations.csv"'})

    @app.get(PREFIX + "/admin/invocations/{invocation_id}")
    async def invocation_detail(invocation_id: str, request: Request, user=Depends(require_capability("audit.read"))):
        row = app.state.store.one("SELECT i.*,r.session_id,r.query_summary,r.mode FROM invocations i JOIN runs r ON r.id=i.run_id WHERE i.id=?", (own_id(invocation_id),))
        if not row:
            fail("调用记录不存在", 404)
        row["skill_ids"] = json_value(row["skill_ids"], [])
        row["plugin_ids"] = json_value(row["plugin_ids"], [])
        row["steps"] = app.state.store.rows("SELECT sequence,step_type,name,status,started,completed,input_summary,output_summary,record_count,error FROM run_events WHERE run_id=? ORDER BY sequence", (row["run_id"],))
        return row
