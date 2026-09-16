from control.final_platform import create_run
from test_control import P, PASSWORD, context, create_user, login_user


def test_department_profile_and_summary(context):
    store, app, admin = context
    department = admin.post(P + "/admin/departments", json={"name": "刑警大队", "code": "320722-XJ"})
    assert department.status_code == 200, department.text
    user = admin.post(P + "/admin/users", json={
        "username": "officer-a", "password": PASSWORD, "display_name": "张三", "police_no": "320722001",
        "department_id": department.json()["id"], "position": "民警",
    })
    assert user.status_code == 202, user.text
    profile = user.json()["user"]
    assert profile["display_name"] == "张三"
    assert profile["department"]["name"] == "刑警大队"
    assert profile["system_role"] == "user"
    summary = admin.get(P + "/admin/users/summary")
    assert summary.status_code == 200
    assert summary.json() == {"users": 1, "departments": 1, "enabled": 1}
    assert admin.delete(P + "/admin/departments/" + department.json()["id"]).status_code == 409


def test_capability_and_skill_draft_lifecycle(context):
    store, app, admin = context
    created = admin.post(P + "/admin/capabilities", json={
        "kind": "skill", "name": "夜间活动分析", "description": "合成测试能力", "version": "1.0",
        "category": "研判分析", "visibility": "all", "dependency_ids": [], "enabled": True,
    })
    assert created.status_code == 200, created.text
    create_user(admin, "officer-b")
    client = login_user(app, "officer-b")
    try:
        capabilities = client.get(P + "/capabilities")
        assert capabilities.status_code == 200
        assert any(item["name"] == "夜间活动分析" for item in capabilities.json()["items"])
        draft = client.post(P + "/skill-drafts/from-requirement", json={"requirement": "分析近30天夜间活动"})
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["id"]
        assert client.patch(P + "/skill-drafts/" + draft_id, json={"name": "个人夜间分析"}).status_code == 200
        assert client.post(P + "/skill-drafts/" + draft_id + "/test", json={}).json()["ok"] is True
        saved = client.post(P + "/skill-drafts/" + draft_id + "/save", json={})
        assert saved.status_code == 200, saved.text
        skills = client.get(P + "/skills").json()["items"]
        assert skills[0]["name"] == "个人夜间分析"
        assert skills[0]["scope"] == "personal"
    finally:
        client.__exit__(None, None, None)


def test_run_and_invocation_share_identity(context):
    store, app, admin = context
    user = create_user(admin, "officer-c")
    run_id = create_run(store, {"uid": user["id"]}, "session-a", None, "合成研判问题", "deep_research", [])
    run = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
    invocation = store.one("SELECT * FROM invocations WHERE run_id=?", (run_id,))
    events = store.rows("SELECT * FROM run_events WHERE run_id=? ORDER BY sequence", (run_id,))
    assert run["mode"] == "deep_research"
    assert invocation["uid"] == user["id"]
    assert [event["step_type"] for event in events] == ["requirement", "skill", "plugin", "analysis", "result"]
