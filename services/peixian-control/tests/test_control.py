import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from control.app import create_app
from control.store import Store, now

P = "/api/console/v1"
PASSWORD = "synthetic-password-for-tests-123"


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_ORIGINS", "http://testserver")
    for name, value in (("key", Fernet.generate_key()), ("worker", b"synthetic-worker-key-for-offline-tests-123456789"), ("admin", PASSWORD.encode())):
        (tmp_path / name).write_bytes(value)
    store = Store(tmp_path / "db", tmp_path / "key", tmp_path / "worker", tmp_path / "admin")
    app = create_app(store)
    with TestClient(app) as client:
        r = client.post(P + "/auth/login", json={"username": "admin", "password": PASSWORD})
        assert r.status_code == 200
        client.headers.update({"X-CSRF-Token": r.json()["csrf_token"], "Origin": "http://testserver"})
        yield store, app, client


def create_user(client, name="person-a"):
    r = client.post(P + "/admin/users", json={"username": name, "password": PASSWORD})
    assert r.status_code == 202, r.text
    return r.json()["user"]


def login_user(app, name):
    client = TestClient(app)
    client.__enter__()
    r = client.post(P + "/auth/login", json={"username": name, "password": PASSWORD})
    assert r.status_code == 200
    client.headers.update({"X-CSRF-Token": r.json()["csrf_token"], "Origin": "http://testserver"})
    return client


def test_initial_password_csrf_and_admin_boundary(context):
    s, app, admin = context
    create_user(admin)
    with TestClient(app) as c:
        r = c.post(P + "/auth/login", json={"username": "person-a", "password": PASSWORD})
        assert c.get(P + "/models").status_code == 200
        assert c.post(P + "/me/password", json={"current_password": PASSWORD, "password": PASSWORD + "-changed"}).status_code == 403
    c = login_user(app, "person-a")
    try:
        assert c.get(P + "/admin/users").status_code == 403
        assert c.get(P + "/skills").status_code == 200
        assert c.get(P + "/plugins").status_code == 200
        assert c.post("/internal/worker/claim", json={}).status_code == 403
        assert c.patch("/config", json={"plugin": ["untrusted"]}).status_code in (404, 405)
    finally:
        c.__exit__(None, None, None)


def test_token_revocation_and_disable(context):
    s, app, admin = context
    u = create_user(admin)
    c = login_user(app, "person-a")
    try:
        r = c.post(P + "/tokens", json={"name": "Python"})
        assert r.status_code == 200, r.text
        token = r.json()
        with TestClient(app) as bearer:
            bearer.headers["Authorization"] = "Bearer " + token["token"]
            assert bearer.get(P + "/me").status_code == 200
            assert c.delete(P + "/tokens/" + token["item"]["id"]).status_code == 200
            assert bearer.get(P + "/me").status_code == 401
        admin.patch(P + "/admin/users/" + u["id"], json={"active": False})
        assert c.get(P + "/me").status_code == 401
    finally:
        c.__exit__(None, None, None)


def test_skill_owner_and_history(context):
    s, app, admin = context
    create_user(admin, "person-a")
    create_user(admin, "person-b")
    a, b = login_user(app, "person-a"), login_user(app, "person-b")
    try:
        r = a.post(P + "/skills", json={"name": "test-skill", "description": "synthetic", "content": "first instruction", "enabled": True})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert b.patch(P + "/skills/" + sid, json={"content": "changed"}).status_code == 404
        assert b.delete(P + "/skills/" + sid).status_code == 404
        assert b.get(P + "/skills").json()["items"] == []
        assert a.patch(P + "/skills/" + sid, json={"content": "second instruction"}).status_code == 200
        assert a.post(P + "/skills/" + sid + "/rollback", json={}).status_code == 200
        assert a.get(P + "/skills").json()["items"][0]["content"] == "first instruction"
        assert a.post(P + "/skills", json={"name": "../escape", "content": "x"}).status_code == 400
    finally:
        a.__exit__(None, None, None)
        b.__exit__(None, None, None)


def plugin_zip(extra=None):
    content = io.BytesIO()
    manifest = {"id": "synthetic-echo", "version": "1.0.0", "name": "Synthetic", "entry": "entry.mjs", "tools": ["synthetic_echo"], "config_schema": {"type": "object", "properties": {"label": {"type": "string"}, "token": {"type": "string", "writeOnly": True}}, "required": ["label", "token"], "additionalProperties": False}}
    with zipfile.ZipFile(content, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("entry.mjs", "export default async () => ({}); export async function test() { return {ok:true} }")
        if extra:
            z.writestr(extra, "unsafe")
    return content.getvalue()


def test_plugin_package_and_secret_redaction(context):
    s, app, admin = context
    u = create_user(admin)
    assert admin.post(P + "/admin/plugins", files={"file": ("plugin.zip", plugin_zip())}).status_code == 200
    assert admin.post(P + "/admin/plugins", files={"file": ("plugin.zip", plugin_zip())}).status_code == 409
    assert admin.post(P + "/admin/plugins", files={"file": ("plugin.zip", plugin_zip("../outside"))}).status_code == 400
    assert admin.patch(P + "/admin/users/" + u["id"], json={"plugin_ids": ["synthetic-echo"]}).status_code == 200
    c = login_user(app, "person-a")
    try:
        private = "synthetic-private-plugin-value"
        r = c.put(P + "/plugins/synthetic-echo", json={"version": "1.0.0", "enabled": True, "config": {"label": "demo", "token": private}})
        assert r.status_code == 200, r.text
        r = c.get(P + "/plugins")
        assert private not in r.text
        assert r.json()["items"][0]["installed"]["credentials_configured"]["token"]
        assert private.encode() not in s.path.read_bytes()
        assert c.put(P + "/plugins/unknown", json={"config": {}}).status_code == 404
    finally:
        c.__exit__(None, None, None)


def test_capacity_atomic(context):
    s, app, admin = context
    def create(i):
        try:
            s.create_user("parallel-" + str(i), PASSWORD)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(create, range(5))) == 4
    assert s.one("SELECT count(*) AS n FROM runtimes WHERE reserved=1")["n"] == 4


def test_worker_lease_takeover(context):
    s, app, admin = context
    create_user(admin)
    headers = {"X-Worker-Key": s.worker_key}
    first = admin.post("/internal/worker/claim", headers=headers, json={})
    assert first.status_code == 200, first.text
    job = first.json()["job"]
    assert admin.post("/internal/worker/claim", headers=headers, json={}).json()["job"] is None
    assert admin.post("/internal/worker/jobs/" + job["id"] + "/complete", headers=headers, json={"lease": "wrong", "ok": True}).status_code == 409
    with s.tx() as db:
        db.execute("UPDATE jobs SET heartbeat=?", (now() - 100,))
    again = admin.post("/internal/worker/claim", headers=headers, json={}).json()["job"]
    assert again["id"] == job["id"] and again["lease"] != job["lease"]
    assert admin.post("/internal/worker/jobs/" + again["id"] + "/complete", headers=headers, json={"lease": again["lease"], "ok": False, "cleanup_confirmed": True}).status_code == 200
    assert s.one("SELECT reserved FROM runtimes")["reserved"] == 0
    assert "gateway_key" not in admin.get(P + "/admin/users").text


def test_model_authorization(context):
    s, app, admin = context
    u = create_user(admin)
    r = admin.post(P + "/admin/models", json={"name": "Fixture", "base_url": "http://fixture:8000/v1", "model_id": "fixture", "api_key": "synthetic-model-secret", "is_default": True})
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert "synthetic-model-secret" not in admin.get(P + "/admin/models").text
    assert admin.post(P + "/admin/models", json={"name": "bad", "base_url": "file:///tmp/file", "model_id": "bad"}).status_code == 400
    c = login_user(app, "person-a")
    try:
        assert c.get(P + "/models").json()["items"] == []
        assert admin.patch(P + "/admin/users/" + u["id"], json={"model_ids": [mid]}).status_code == 200
        assert c.get(P + "/models").json()["items"][0]["id"] == mid
        assert c.post(P + "/sessions", json={"directory": "/other"}).status_code == 400
    finally:
        c.__exit__(None, None, None)
