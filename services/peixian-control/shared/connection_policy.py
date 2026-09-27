"""Fixed destinations and bounded JSON exchanges for platform service connections."""
import asyncio
import json
import re
from urllib.parse import urlsplit

import httpx

MAX_REQUEST_BYTES = 1024 * 1024
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
HEADER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
FORBIDDEN_HEADERS = {"host", "connection", "content-length", "transfer-encoding", "content-type", "accept", "accept-encoding", "cookie", "set-cookie", "proxy-authorization", "proxy-authenticate"}


class ConnectionFailure(ValueError):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def safe_path(value, *, pattern=False):
    if not isinstance(value, str) or not 1 <= len(value) <= 1000:
        raise ConnectionFailure("服务路径格式不正确")
    plain = value[:-1] if pattern and value.endswith("/*") else value
    if (not plain.startswith("/") or "//" in plain or not re.fullmatch(r"/[A-Za-z0-9_./~-]*", plain)
            or any(part in (".", "..") for part in plain.split("/"))):
        raise ConnectionFailure("服务路径必须是无转义、查询参数和目录跳转的绝对路径")
    return value


def fixed_base(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1000 or any(ord(c) <= 32 for c in value) or "\\" in value:
        raise ConnectionFailure("服务地址格式不正确")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ConnectionFailure("服务地址格式不正确") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or "?" in value or "#" in value or port == 0
            or "%" in parts.netloc):
        raise ConnectionFailure("服务地址必须为无鉴权参数的 HTTP/HTTPS 地址")
    safe_path(parts.path or "/")
    return value.rstrip("/")


def policy(value):
    result = dict(value)
    result["base_url"] = fixed_base(result.get("base_url"))
    methods, paths = result.get("allowed_methods"), result.get("allowed_paths")
    if (not isinstance(methods, list) or not methods or len(methods) > 5
            or any(not isinstance(v, str) or v not in METHODS for v in methods)):
        raise ConnectionFailure("请选择允许的 HTTP 方法")
    if not isinstance(paths, list) or not paths or len(paths) > 100:
        raise ConnectionFailure("请填写允许的服务路径")
    result["allowed_methods"] = sorted(set(methods))
    result["allowed_paths"] = sorted({safe_path(v, pattern=True) for v in paths})
    timeout, size = result.get("timeout_seconds"), result.get("max_response_bytes")
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ConnectionFailure("连接超时必须为 1 至 60 秒")
    if type(size) is not int or not 1024 <= size <= 10 * 1024 * 1024:
        raise ConnectionFailure("响应上限必须为 1 KiB 至 10 MiB")
    if "request_rules" in result:
        rules = result["request_rules"]
        if not isinstance(rules, list) or not 1 <= len(rules) <= 20:
            raise ConnectionFailure("固定请求规则必须为1至20项；省略字段沿用原策略")
        seen = set()
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) - {"method", "path", "json"}:
                raise ConnectionFailure("固定请求规则包含不支持字段")
            method, path = rule.get("method"), safe_path(rule.get("path"))
            if method not in result["allowed_methods"] or not any(path.startswith(p[:-1]) if p.endswith("/*") else path == p for p in result["allowed_paths"]):
                raise ConnectionFailure("固定规则超出方法或路径许可")
            if (method, path) in seen or method == "GET" and "json" in rule:
                raise ConnectionFailure("固定规则重复或GET包含正文")
            seen.add((method, path))
            try:
                raw = json.dumps(rule, ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                raise ConnectionFailure("固定规则必须是有效JSON") from None
            if len(raw.encode()) > 16384:
                raise ConnectionFailure("固定规则超过大小限制")
    return result


def request_data(connection, value):
    if not isinstance(value, dict) or set(value) - {"method", "path", "query", "json"}:
        raise ConnectionFailure("连接请求包含不支持的字段")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise ConnectionFailure("连接请求必须是有效 JSON") from None
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ConnectionFailure("连接请求超过 1 MiB", 413)
    path, method = safe_path(value.get("path")), value.get("method", "GET")
    if method not in connection["allowed_methods"]:
        raise ConnectionFailure("此连接不允许该请求方法", 403)
    if not any(path.startswith(p[:-1]) if p.endswith("/*") else path == p for p in connection["allowed_paths"]):
        raise ConnectionFailure("此连接不允许该服务路径", 403)
    query = value.get("query", {})
    if (not isinstance(query, dict) or len(query) > 100
            or any(not isinstance(k, str) or not 1 <= len(k) <= 200 for k in query)
            or any(not isinstance(v, (str, int, float, bool)) or len(str(v)) > 4000 for v in query.values())):
        raise ConnectionFailure("查询参数必须为有限的键值对")
    if method == "GET" and "json" in value:
        raise ConnectionFailure("GET 请求不接受 JSON 正文")
    if "request_rules" in connection:
        rule = next((r for r in connection["request_rules"] if r["method"] == method and r["path"] == path), None)
        # Canonical JSON distinguishes booleans/numbers and exact object shape.
        same = rule is not None and ("json" in rule) == ("json" in value)
        if same and "json" in value:
            same = json.dumps(rule["json"], sort_keys=True, allow_nan=False) == json.dumps(value["json"], sort_keys=True, allow_nan=False)
        if not same or query:
            raise ConnectionFailure("请求不符合此连接的固定模块规则", 403)
    return method, connection["base_url"] + path, query


def validate_headers(headers):
    if (not isinstance(headers, dict) or len(headers) > 1
            or any(not isinstance(k, str) or not HEADER.fullmatch(k) or k.lower() in FORBIDDEN_HEADERS for k in headers)
            or any(not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in v) for v in headers.values())):
        raise ConnectionFailure("服务鉴权配置无效")
    return headers


async def exchange(client, connection, value):
    """Never return upstream error bodies, redirects, headers, or authentication values."""
    method, url, query = request_data(connection, value)
    headers = {"Accept": "application/json", "Accept-Encoding": "identity", **validate_headers(connection.get("headers", {}))}
    try:
        async with asyncio.timeout(connection["timeout_seconds"]):
            async with client.stream(method, url, params=query, json=value.get("json") if "json" in value else None,
                                     headers=headers, follow_redirects=False, timeout=connection["timeout_seconds"]) as response:
                if 300 <= response.status_code < 400:
                    raise ConnectionFailure("服务返回了未允许的重定向", 502)
                if response.status_code == 413:
                    raise ConnectionFailure("服务结果超过单次返回上限", 413, "upstream_rows_limit")
                if response.status_code >= 400:
                    raise ConnectionFailure("服务拒绝了本次请求，请检查配置或参数", 502)
                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media != "application/json" and not media.endswith("+json"):
                    raise ConnectionFailure("服务必须返回 JSON 内容", 502)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ConnectionFailure("服务未遵守无压缩响应要求", 502)
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    raw.extend(chunk)
                    if len(raw) > connection["max_response_bytes"]:
                        raise ConnectionFailure("服务响应超过配置的大小限制", 413, "response_too_large")
                try:
                    result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError, RecursionError):
                    raise ConnectionFailure("服务返回了无效 JSON", 502) from None
                # Credentials accidentally reflected by an upstream are not business data.
                text = json.dumps(result, ensure_ascii=False)
                secrets = list(connection.get("headers", {}).values())
                secrets += [v[7:] for v in secrets if v.startswith("Bearer ")]
                if any(secret and secret in text for secret in secrets):
                    raise ConnectionFailure("服务响应包含鉴权信息，已阻止返回", 502)
                return {"status": response.status_code, "data": result}
    except (httpx.HTTPError, TimeoutError):
        raise ConnectionFailure("服务暂时无法连接或响应超时", 502) from None
