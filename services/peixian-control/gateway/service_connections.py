"""Account-scoped plugin service bindings loaded only from the relay mount."""
import hmac
import json
from pathlib import Path
import re

from fastapi import HTTPException

from shared.connection_policy import ConnectionFailure, exchange, policy, validate_headers
from .http_utils import json_body

FIELDS = {"id", "plugin_id", "alias", "allowed_user", "token", "headers", "base_url", "allowed_methods",
          "allowed_paths", "timeout_seconds", "max_response_bytes"}


def load_connections(path, account_id):
    file = Path(path)
    if not file.exists():
        return {}
    try:
        if not account_id or file.is_symlink():
            raise ValueError()
        payload = json.loads(file.read_text(encoding="utf-8"))
        if set(payload) != {"account_id", "connections"} or payload["account_id"] != account_id or not isinstance(payload["connections"], list):
            raise ValueError()
        result = {}
        for item in payload["connections"]:
            if (not isinstance(item, dict) or not FIELDS <= set(item) or set(item) - FIELDS - {"request_rules"} or item["allowed_user"] != account_id
                    or any(not isinstance(item[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item[k]) for k in ("id", "plugin_id", "alias"))
                    or not isinstance(item["token"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["token"])
                    or item["id"] in result):
                raise ValueError()
            result[item["id"]] = {**policy(item), "headers": validate_headers(item["headers"])}
        return result
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("Invalid account service connection configuration") from None


async def invoke(request, cid):
    connection = request.app.state.connections.get(cid)
    credential = request.headers.get("authorization", "")
    if connection is None or not hmac.compare_digest(credential, "Bearer " + connection["token"]):
        raise HTTPException(403, "Service connection is not authorized")
    try:
        payload = await json_body(request, 1024 * 1024)
        gate = getattr(request.app.state, "admission", None)
        if gate:
            gate.require_egress()
        return await exchange(request.app.state.client, connection, payload)
    except ConnectionFailure as exc:
        headers = {"X-Peixian-Failure": exc.code} if exc.code else None
        raise HTTPException(exc.status, str(exc), headers=headers) from None
