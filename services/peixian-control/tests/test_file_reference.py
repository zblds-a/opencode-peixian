"""Incomplete extracted files must never become model input."""
import httpx
import pytest

from test_control import context, create_user, login_user, P

NOTICE = "所选文件仅完成部分解析，请拆分文件后重新上传；可在我的文件查看已提取范围"


@pytest.mark.parametrize(("status", "truncated", "expected"), [
    ("partial", True, 413),
    ("partial", False, 413),
    ("ready", True, 413),
    ("ready", False, 202),
])
def test_incomplete_file_is_rejected_before_model_submission(context, monkeypatch, status, truncated, expected):
    store, app, administrator = context
    account = create_user(administrator)
    model_response = administrator.post(P + "/admin/models", json={
        "name": "Synthetic reference model", "base_url": "http://synthetic-model.invalid/v1",
        "model_id": "synthetic", "api_key": "", "is_default": True,
    })
    assert model_response.status_code == 200
    mid = model_response.json()["id"]
    assert administrator.patch(P + "/admin/users/" + account["id"], json={"model_ids": [mid]}).status_code == 200
    from control.worker_api import runtime_spec
    with store.tx() as database:
        desired = database.execute("SELECT desired FROM runtimes WHERE uid=?", (account["id"],)).fetchone()[0]
        applied = runtime_spec(store, account["id"], desired, db=database)
        database.execute("UPDATE runtimes SET status='ready',revision=desired,gate_policy='open',applied_spec_ciphertext=? WHERE uid=?", (store.encrypt(applied), account["id"]))
    prompt_requests = []
    monkeypatch.setenv('PX_THEFT_NATIVE_UIDS',account['id'])
    monkeypatch.setenv('PX_MULTI_AGENT_V1_UIDS',account['id'])

    async def fake_upstream(request, user, method, path, **kwargs):
        assert user["uid"] == account["id"]
        if method == "GET" and path == "/session/synthetic-session":
            return httpx.Response(200, json={"id": "synthetic-session", "directory": "/workspace"})
        if method == 'GET' and path == '/session/synthetic-session/message':
            return httpx.Response(200,json=[])
        if method == 'GET' and path.startswith('/internal/runtime/runs/'):
            return httpx.Response(200,json={'protocol':'durable_run_v1'})
        if method == "GET" and path == "/files/synthetic-file/text":
            return httpx.Response(200, json={
                "status": status, "truncated": truncated, "name": "synthetic.txt",
                "text": "Synthetic extracted text",
                "chunks": [{"text": "Synthetic extracted text", "source": {"type": "text", "line_start": 1, "line_end": 1}}],
            })
        if method == "POST" and path == "/session/synthetic-session/prompt_async":
            prompt_requests.append(kwargs["json"])
            return httpx.Response(204)
        raise AssertionError("Unexpected upstream route in isolated test")

    monkeypatch.setattr("control.app.upstream", fake_upstream)
    client = login_user(app, "person-a")
    try:
        response = client.post(P + "/sessions/synthetic-session/messages", json={
            "text": "Describe the supplied fixture", "model_id": mid, "agent_id":"theft-assistant", "file_ids": ["synthetic-file"],
        })
        assert response.status_code == expected
        if expected == 413:
            assert response.json()["message"] == NOTICE
            assert prompt_requests == []
        else:
            assert response.json()["accepted"] is True
            assert prompt_requests == []
            row=store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(response.json()['run_id'],))
            snapshot=store.decrypt(row['request_ciphertext'])
            assert snapshot['attachments'][0]['parse_status']=='ready'
            assert snapshot['attachments'][0]['verified_source'] is False
            submitted = snapshot['payload']['parts']
            assert "Synthetic extracted text" in submitted[0]["text"]
            assert "[来源 " in submitted[0]["text"]
    finally:
        client.__exit__(None, None, None)
