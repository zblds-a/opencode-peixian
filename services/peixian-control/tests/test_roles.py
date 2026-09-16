"""Offline role, migration and revoked-stream acceptance using synthetic accounts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest

from control.app import create_app
from control.roles import capabilities
from control.store import Store, digest, now, SCHEMA_VERSION
from test_control import context, create_user, login_user, plugin_zip, P, PASSWORD


def legacy_database(tmp_path):
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-key-for-roles-1234567890"),
                        ("admin", PASSWORD.encode())):
        (tmp_path / name).write_bytes(value)
    root = tmp_path / "db"
    root.mkdir()
    with sqlite3.connect(root / "control.sqlite3") as db:
        db.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,
                role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,must_change INTEGER NOT NULL DEFAULT 1,
                auth_version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL);
            CREATE TABLE auth(hash TEXT PRIMARY KEY,uid TEXT NOT NULL,kind TEXT NOT NULL,name TEXT,csrf TEXT,
                expires INTEGER NOT NULL,version INTEGER NOT NULL,created INTEGER NOT NULL);
            CREATE TABLE audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created INTEGER NOT NULL);
        """)
        for uid, role in (("old-administrator", "admin"), ("existing-user", "user")):
            db.execute("INSERT INTO users VALUES(?,?,?,?,1,0,7,?)", (uid, uid, "unchanged-password-hash", role, now()))
            for kind in ("session", "token"):
                db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)", (digest(uid + kind), uid, kind, "fixture", "csrf", now() + 3600, 7, now()))
        db.execute("INSERT INTO audit VALUES('old-audit','old-administrator','user.update','existing-user',?)", (now(),))
    return root, tmp_path / "key", tmp_path / "worker", tmp_path / "admin"


def test_legacy_migration_revokes_only_old_admin_and_is_once(tmp_path):
    args = legacy_database(tmp_path)
    s = Store(*args)
    assert s.schema_version() == SCHEMA_VERSION
    old = s.one("SELECT * FROM users WHERE id='old-administrator'")
    assert (old["role"], old["auth_version"], old["password"]) == ("super_admin", 8, "unchanged-password-hash")
    assert s.rows("SELECT * FROM auth WHERE uid='old-administrator'") == []
    assert len(s.rows("SELECT * FROM auth WHERE uid='existing-user'")) == 2
    assert s.one("SELECT * FROM users WHERE id='existing-user'")["auth_version"] == 7
    assert s.one("SELECT actor_role FROM audit WHERE id='old-audit'")["actor_role"] == "super_admin"
    with TestClient(create_app(s)) as client:
        client.headers["Authorization"] = "Bearer old-administratortoken"
        assert client.get(P + "/me").status_code == 401
        client.headers.pop("Authorization")
        client.cookies.set("px_session", "old-administratorsession")
        assert client.get(P + "/me").status_code == 401
    manager, job = s.create_user("new-administrator", PASSWORD, role="admin")
    assert job is None and manager["runtime"] is None
    with s.tx() as db:
        db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)", (digest("new-manager-token"), manager["id"], "token", "fixture", None, now()+600, 1, now()))
    reopened = Store(*args)
    assert reopened.user(manager["id"])["role"] == "admin"
    assert reopened.one("SELECT hash FROM auth WHERE uid=?", (manager["id"],))
    assert reopened.one("SELECT auth_version FROM users WHERE id='old-administrator'")["auth_version"] == 8
    assert len(reopened.rows("SELECT * FROM audit WHERE action='schema.migrate' AND target='control.roles.v2'")) == 1


def test_migration_ddl_roles_auth_and_version_rollback_together(tmp_path):
    args = legacy_database(tmp_path)

    class InterruptedStore(Store):
        def migrate_roles(self, db, password_file):
            super().migrate_roles(db, password_file)
            raise RuntimeError("synthetic interruption before commit")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        InterruptedStore(*args)
    with sqlite3.connect(args[0] / "control.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT role,auth_version FROM users WHERE id='old-administrator'").fetchone() == ("admin", 7)
        assert db.execute("SELECT count(*) FROM auth").fetchone()[0] == 4
        assert [r[1] for r in db.execute("PRAGMA table_info(audit)")] == ["id", "actor", "action", "target", "created"]
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='runtimes'").fetchone()
    assert Store(*args).schema_version() == SCHEMA_VERSION


def test_unknown_newer_schema_is_rejected_without_downgrade(tmp_path):
    args = legacy_database(tmp_path)
    with sqlite3.connect(args[0] / "control.sqlite3") as db:
        db.execute("PRAGMA user_version=4")
    with pytest.raises(ValueError, match="newer"):
        Store(*args)
    with sqlite3.connect(args[0] / "control.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT role FROM users WHERE id='old-administrator'").fetchone()[0] == "admin"


@pytest.fixture
def manager(context):
    s, app, superuser = context
    response = superuser.post(P + "/admin/users", json={"username": "manager", "password": PASSWORD, "role": "admin"})
    assert response.status_code == 202, response.text
    assert response.json()["job"] is None and response.json()["user"]["runtime"] is None
    client = login_user(app, "manager")
    try:
        yield response.json()["user"], client
    finally:
        client.__exit__(None, None, None)


def test_bootstrap_capabilities_role_matrix_and_admin_has_no_runtime(context, manager):
    s, app, superuser = context
    managed, administrator = manager
    assert superuser.get("/health").json() == {"status": "ok", "version": "1.2.0", "schema_version": SCHEMA_VERSION}
    assert superuser.get(P + "/me").json()["user"]["role"] == "super_admin"
    assert s.rows("SELECT * FROM runtimes") == [] and s.rows("SELECT * FROM jobs") == []
    assert s.rows("SELECT * FROM grants WHERE uid=?", (managed["id"],)) == []
    created = administrator.post(P + "/admin/users", json={"username": "ordinary-user", "password": PASSWORD})
    assert created.status_code == 202
    assert created.json()["user"]["runtime"] == {"status": "pending"}
    assert created.json()["job"] == {"status": "queued"}
    client = login_user(app, "ordinary-user")
    try:
        for role, actor in (("super_admin", superuser), ("admin", administrator), ("user", client)):
            identity = actor.get(P + "/me").json()
            assert identity["capabilities"] == capabilities(role)
            for route in ("users", "models", "audit", "plugins", "templates", "jobs"):
                expected = 200 if role == "super_admin" or role == "admin" and route in ("users", "models", "audit") else 403
                assert actor.get(P + "/admin/" + route).status_code == expected, (role, route)
        listed = administrator.get(P + "/admin/users").json()["items"]
        assert all(row["role"] == "user" and set(row["runtime"]) == {"status"} and "plugin_ids" not in row for row in listed)
        for actor in (superuser, administrator):
            for route in ("sessions", "files", "results", "skills", "plugins", "events"):
                assert actor.get(P + "/" + route).status_code == 403
        assert client.get(P + "/skills").status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_managers_do_not_use_runtime_capacity(context, manager, monkeypatch):
    s, app, superuser = context
    monkeypatch.setenv("MAX_RUNTIMES", "0")
    response = superuser.post(P + "/admin/users", json={"username": "another-manager", "password": PASSWORD, "role": "admin"})
    assert response.status_code == 202 and response.json()["job"] is None
    assert superuser.post(P + "/admin/users", json={"username": "over-capacity", "password": PASSWORD}).status_code == 409


def snapshot_account(s, uid):
    return {table: s.rows("SELECT * FROM " + table + " WHERE " + ("id" if table == "users" else "uid") + "=?", (uid,))
            for table in ("users", "auth", "grants", "runtimes", "jobs")}


def test_admin_mixed_fields_reject_atomically_and_cannot_manage_management_roles(context, manager):
    s, app, superuser = context
    managed, administrator = manager
    account = create_user(administrator)
    before = snapshot_account(s, account["id"])
    for route in ("/admin/plugins", "/admin/templates"):
        assert administrator.post(P + route, json={}).status_code == 403
    for body in ({"active": False, "plugin_ids": []}, {"model_ids": [], "plugin_ids": []},
                 {"active": False, "role": "admin"}, {"active": False, "department_id": "synthetic"},
                 {"active": False, "runtime": {"action": "pause"}}):
        assert administrator.patch(P + "/admin/users/" + account["id"], json=body).status_code in (400, 403)
        assert snapshot_account(s, account["id"]) == before
    for role in ("user", "admin", "super_admin"):
        assert administrator.post(P + "/admin/users", json={"username": "forbidden-" + role, "password": PASSWORD, "role": role}).status_code == 403
        assert not s.one("SELECT id FROM users WHERE username=?", ("forbidden-" + role,))
    response = administrator.post(P + "/admin/users", json={"username": "mixed-create", "password": PASSWORD, "model_ids": [], "plugin_ids": []})
    assert response.status_code == 403 and not s.one("SELECT id FROM users WHERE username='mixed-create'")
    root_id = superuser.get(P + "/me").json()["user"]["id"]
    for uid in (managed["id"], root_id):
        assert administrator.patch(P + "/admin/users/" + uid, json={"active": False}).status_code == 404
        assert administrator.post(P + "/admin/users/" + uid + "/reset-password", json={}).status_code == 404
    for action in ("pause", "resume", "retry", "apply"):
        assert administrator.post(P + "/admin/users/" + account["id"] + "/runtime/" + action, json={}).status_code == 403
    assert snapshot_account(s, account["id"]) == before
    assert administrator.post("/internal/worker/claim", json={}).status_code == 403
    token = administrator.post(P + "/tokens", json={"name": "synthetic-manager-token"}).json()["token"]
    with TestClient(app) as bearer:
        bearer.headers["Authorization"] = "Bearer " + token
        assert bearer.get(P + "/admin/users").status_code == 200
        assert bearer.get(P + "/admin/plugins").status_code == 403
        assert bearer.patch(P + "/admin/users/" + account["id"], json={"active": False, "role": "user"}).status_code == 403
        assert snapshot_account(s, account["id"]) == before


def test_admin_can_manage_user_models_without_changing_super_plugin_grants(context, manager):
    s, app, superuser = context
    managed, administrator = manager
    account = create_user(administrator)
    model = administrator.post(P + "/admin/models", json={"name": "Synthetic", "base_url": "http://fixture.invalid/v1", "model_id": "fixture", "api_key": "synthetic-never-log-secret"})
    assert model.status_code == 200
    assert superuser.post(P + "/admin/plugins", files={"file": ("plugin.zip", plugin_zip())}).status_code == 200
    assert superuser.patch(P + "/admin/users/" + account["id"], json={"plugin_ids": ["synthetic-echo"]}).status_code == 200
    response = administrator.patch(P + "/admin/users/" + account["id"], json={"model_ids": [model.json()["id"]]})
    assert response.status_code == 200
    assert s.one("SELECT resource FROM grants WHERE uid=? AND kind='plugin'", (account["id"],))["resource"] == "synthetic-echo"
    assert "synthetic-never-log-secret" not in administrator.get(P + "/admin/models").text
    for body in ({"model_ids": []}, {"plugin_ids": []}):
        assert superuser.patch(P + "/admin/users/" + managed["id"], json=body).status_code == 400


def test_super_can_disable_and_reset_admin_and_revoke_cookie_and_token(context, manager):
    s, app, superuser = context
    managed, administrator = manager
    token = administrator.post(P + "/tokens", json={"name": "synthetic"}).json()["token"]
    with TestClient(app) as bearer:
        bearer.headers["Authorization"] = "Bearer " + token
        assert bearer.get(P + "/me").status_code == 200
        response = superuser.patch(P + "/admin/users/" + managed["id"], json={"active": False})
        assert response.status_code == 200 and response.json()["job"] is None
        assert administrator.get(P + "/me").status_code == bearer.get(P + "/me").status_code == 401
        assert superuser.patch(P + "/admin/users/" + managed["id"], json={"active": True}).status_code == 200
        assert bearer.get(P + "/me").status_code == 401
        response = superuser.post(P + "/admin/users/" + managed["id"] + "/reset-password", json={"password": PASSWORD})
        assert response.status_code == 200
        assert not s.user(managed["id"])["must_change_password"]
        assert s.rows("SELECT * FROM jobs WHERE uid=?", (managed["id"],)) == []


def test_management_audit_filters_only_safe_metadata_and_captures_denied(context, manager):
    s, app, superuser = context
    managed, administrator = manager
    marker = "synthetic-secret-should-never-be-an-audit-field"
    denied = administrator.post(P + "/admin/users", json={"username": "mixed-audit", "password": marker, "plugin_ids": []})
    assert denied.status_code == 403
    create_user(administrator, "allowed-audit")
    s.audit("worker", "legacy.import", json.dumps({"volume": "/private/synthetic-volume", "secret": marker}))
    s.audit(managed["id"], "plugin.configure", marker)
    response = administrator.get(P + "/admin/audit", params={"actor": managed["id"], "action": "user.create", "result": "denied"})
    assert response.status_code == 200
    rows = response.json()["items"]
    assert len(rows) == 1 and rows[0]["actor_role"] == "admin" and rows[0]["result"] == "denied"
    all_rows = administrator.get(P + "/admin/audit").json()["items"]
    assert {r["result"] for r in all_rows} >= {"success", "denied"}
    assert marker not in json.dumps(all_rows) and "/private/" not in json.dumps(all_rows)
    assert all(r["action"] not in ("legacy.import", "plugin.configure") for r in all_rows)
    assert all(set(r) == {"id", "actor", "actor_role", "username", "action", "target", "result", "created"} for r in all_rows)
    assert administrator.get(P + "/admin/audit", params={"result": "anything"}).status_code == 400


@pytest.mark.parametrize("revoke", ["disable", "reset", "token", "logout"])
def test_old_sse_connection_closes_after_auth_revocation(context, monkeypatch, revoke):
    s, app, superuser = context
    account = create_user(superuser)
    client = login_user(app, "person-a")
    started = threading.Event()

    class QuietStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            yield b": synthetic\n\n"
            await asyncio.Event().wait()

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=QuietStream())))
    monkeypatch.setattr(app.state, "http", mock_http)
    with s.tx() as db:
        db.execute("UPDATE runtimes SET status='ready',revision=desired WHERE uid=?", (account["id"],))
    token = client.post(P + "/tokens", json={"name": "synthetic-stream"}).json()
    if revoke == "token":
        client.headers["Authorization"] = "Bearer " + token["token"]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, P + "/events")
            assert started.wait(3), "SSE did not subscribe to the synthetic upstream"
            if revoke == "disable":
                response = superuser.patch(P + "/admin/users/" + account["id"], json={"active": False})
            elif revoke == "reset":
                response = superuser.post(P + "/admin/users/" + account["id"] + "/reset-password", json={"password": PASSWORD})
            elif revoke == "token":
                response = client.delete(P + "/tokens/" + token["item"]["id"])
            else:
                response = client.post(P + "/auth/logout", json={})
            assert response.status_code == 200
            finished = pending.result(timeout=5)
            assert finished.status_code == 200 and '"type":"connected"' in finished.text
            assert "synthetic" not in finished.text
        assert client.get(P + "/me").status_code == 401
    finally:
        client.__exit__(None, None, None)


def test_schema_contract_describes_three_roles_and_scoped_management(context):
    s, app, superuser = context
    document = app.openapi()
    schemas = document["components"]["schemas"]
    assert schemas["User"]["properties"]["role"]["enum"] == ["user", "admin", "super_admin"]
    assert "capabilities" in schemas["Identity"]["required"]
    assert schemas["Health"]["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    for path in ("/admin/plugins", "/admin/templates", "/admin/jobs"):
        assert document["paths"][P + path]["get"]["x-roles"] == ["super_admin"]
    assert document["paths"][P + "/admin/models"]["post"]["x-roles"] == ["super_admin", "admin"]
    assert "role" not in schemas["UserUpdateBody"]["properties"]
