#!/usr/bin/env python3
"""Dependency-free development server for the packaged Peixian console fixtures."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
API = ROOT / "api"
PREFIX = "/api/console/v1"


def fixture(name: str):
    return json.loads((API / name).read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "PeixianMock/1.0"

    def send_json(self, value, status=HTTPStatus.OK, headers=None):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, item in (headers or {}).items():
            self.send_header(key, item)
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def role(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie.get("mock_role").value if cookie.get("mock_role") else "user"

    def route(self):
        path = urlparse(self.path).path
        if not path.startswith(PREFIX):
            return None
        return path[len(PREFIX):] or "/"

    def do_GET(self):
        path = self.route()
        if path is None:
            self.send_json({"message": "仅提供 /api/console/v1 下的 Mock 接口"}, HTTPStatus.NOT_FOUND)
            return
        if path == "/events":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        routes = {
            "/platform": "platform.json",
            "/models": "models.json",
            "/sessions": "sessions.json",
            "/capabilities": "capabilities.json",
            "/files": "files-empty.json",
            "/skills": "skills-empty.json",
            "/admin/models": "admin-models.json",
            "/admin/departments/tree": "admin-departments-tree.json",
            "/admin/users": "admin-users.json",
            "/admin/users/summary": "admin-users-summary.json",
            "/admin/invocations": "admin-invocations.json",
        }
        if path == "/me":
            self.send_json(fixture("auth-admin.json" if self.role() == "admin" else "auth-user.json"))
            return
        if path in routes:
            self.send_json(fixture(routes[path]))
            return
        if path.endswith("/messages"):
            self.send_json(fixture("messages-structured.json" if "/mock-night/" in path else "messages-markdown.json"))
            return
        if "/runs/" in path and path.endswith("/events"):
            self.send_json(fixture("run-events.json"))
            return
        if "/runs/" in path and path.endswith("/evidence"):
            self.send_json(fixture("run-evidence.json"))
            return
        self.send_json({"message": "未配置该 Mock 路由", "code": "mock_route_not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = self.route()
        body = self.read_json()
        if path == "/auth/login":
            username = str(body.get("username", ""))
            password = str(body.get("password", ""))
            if not username or not password:
                self.send_json({"message": "账号或密码不正确", "code": "invalid_credentials"}, HTTPStatus.UNAUTHORIZED)
                return
            role = "admin" if username == "admin" else "user"
            self.send_json(fixture("auth-admin.json" if role == "admin" else "auth-user.json"), headers={"Set-Cookie": f"mock_role={role}; HttpOnly; SameSite=Lax; Path=/"})
            return
        if path == "/auth/logout":
            self.send_json({"ok": True}, headers={"Set-Cookie": "mock_role=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/"})
            return
        if path == "/sessions":
            self.send_json({"id": "mock-created-session", "title": body.get("title", "新建研判"), "status": "idle"}, HTTPStatus.CREATED)
            return
        if path and path.endswith("/messages"):
            self.send_json({"accepted": True, "run_id": "mock-run-created", "message_id": "mock-user-message"}, HTTPStatus.ACCEPTED)
            return
        if path and path.endswith("/abort"):
            self.send_json({"ok": True})
            return
        if path and (path.endswith("/test") or path.endswith("/reset-password") or path.endswith("/save")):
            self.send_json({"ok": True, "message": "Mock 操作成功"})
            return
        self.send_json({"ok": True, "mock": True})

    def do_PATCH(self):
        self.read_json()
        self.send_json({"ok": True, "mock": True})

    def do_DELETE(self):
        self.send_json({"ok": True, "mock": True})

    def log_message(self, format, *args):
        print("[peixian-mock] " + format % args)


if __name__ == "__main__":
    address = ("127.0.0.1", 14090)
    print(f"Peixian Mock API: http://{address[0]}:{address[1]}{PREFIX}")
    print("Development only. Login with admin/<any non-empty password> for admin, or any other account for user.")
    ThreadingHTTPServer(address, Handler).serve_forever()
