"""One validated, secret-free configuration shared by the server and host worker."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

_spec = importlib.util.spec_from_file_location("peixian_capacity", Path(__file__).with_name("platform-capacity.py"))
capacity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capacity)

_orchestration_path = Path(__file__).resolve().parents[2] / "services/peixian-control/shared/orchestration_config.py"
_orchestration_spec = importlib.util.spec_from_file_location("platform_orchestration_config", _orchestration_path)
orchestration_settings = importlib.util.module_from_spec(_orchestration_spec)
_orchestration_spec.loader.exec_module(orchestration_settings)
_hub_spec = importlib.util.spec_from_file_location("eventhub_config", _orchestration_path.with_name("eventhub_config.py"))
hub_settings = importlib.util.module_from_spec(_hub_spec)
_hub_spec.loader.exec_module(hub_settings)
_pool_spec = importlib.util.spec_from_file_location("runtime_pool_config", _orchestration_path.with_name("runtime_pool_config.py"))
pool_settings = importlib.util.module_from_spec(_pool_spec)
_pool_spec.loader.exec_module(pool_settings)

PROXY_IMAGE = "agent-platform-proxy:nginx-1.28.0"
PROXY_UPSTREAM = "nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284"
IMAGES = {"control": "agent-platform-control:1.0.0", "gateway": "agent-platform-gateway:1.0.0",
          "agent": "peixian-opencode:1.18.30-managed-r1", "proxy": PROXY_IMAGE}
LIMITS = {"agent": {"cpus": 2.0, "memory_mib": 2048}, "gateway": {"cpus": 0.5, "memory_mib": 512},
          "relay": {"cpus": 0.5, "memory_mib": 128}}
PRODUCT = {"name": "Agent 工作台", "short_name": "Agent", "description": "对话、文件、技能与插件，在一个工作台完成。"}

CONCURRENCY = {
    "http_connections": (64, 1, 512), "http_keepalive": (16, 1, 256),
    "sse_viewers": (128, 1, 1024), "sse_per_account": (4, 1, 32), "sse_owners": (64, 1, 256),
    "sse_heartbeat_seconds": (15, 1, 60), "sse_renew_seconds": (5, 1, 30),
    "sse_owner_ttl_seconds": (20, 5, 120), "auth_recheck_seconds": (2, 1, 2),
    "downloads": (8, 1, 64), "db_workers": (8, 1, 32), "db_queue": (32, 1, 256),
    "db_queue_seconds": (1, 1, 10), "db_busy_ms": (1000, 1, 1000),
    "crypto_workers": (2, 1, 8), "crypto_queue": (16, 1, 128), "crypto_queue_seconds": (2, 1, 10),
    "login_capacity": (4096, 64, 65536), "login_ttl_seconds": (300, 10, 3600),
    "login_rate": (10, 1, 1000), "login_burst": (50, 1, 1000),
    "login_source_rate": (5, 1, 100), "login_source_burst": (50, 1, 1000),
}
CONCURRENCY.update(hub_settings.BOUNDS)


def concurrency_config(value):
    if not isinstance(value, dict) or set(value) - set(CONCURRENCY):
        raise ConfigError("invalid_concurrency_configuration")
    result = {key: value.get(key, bounds[0]) for key, bounds in CONCURRENCY.items()}
    for key, item in result.items():
        _, low, high = CONCURRENCY[key]
        if type(item) is not int or not math.isfinite(item) or not low <= item <= high:
            raise ConfigError("invalid_concurrency_configuration")
    if (result["http_keepalive"] > result["http_connections"] or
            result["sse_per_account"] > result["sse_viewers"] or result["sse_owners"] > result["sse_viewers"] or
            result["sse_renew_seconds"] * 2 >= result["sse_owner_ttl_seconds"]):
        raise ConfigError("inconsistent_concurrency_configuration")
    try:
        hub_settings.validate(result)
    except ValueError:
        raise ConfigError("invalid_eventhub_configuration") from None
    return result


class ConfigError(ValueError):
    pass


def image_supports_config(labels, version):
    # Historical images have no configuration capability label and support v1.
    labels = labels or {}
    raw = labels.get("org.peixian.control.config.max", "1")
    if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]{0,2}", raw) or version > int(raw):
        raise ConfigError("control_image_configuration_incompatible")


def image_supports_orchestration(labels, component, version):
    if version < 3 or component == "proxy":
        return
    labels = labels or {}
    if labels.get("org.peixian.runtime.protocol") != "2":
        raise ConfigError("runtime_image_protocol_incompatible")
    if component == "control" and (labels.get("org.peixian.worker.protocol") != "2"
                                     or labels.get("org.peixian.control.schema.max") not in ("4", "5", "6", "7", "8", "9", "10", "11")):
        raise ConfigError("control_image_orchestration_incompatible")
    if version == 4 and component == "control" and (labels.get("org.peixian.control.schema.max") not in ("5", "6", "7", "8", "9", "10", "11")
            or pool_settings.CAPABILITY not in labels.get("org.peixian.worker.capabilities", "").split(",")):
        raise ConfigError("control_image_runtime_pool_incompatible")


def safe_path(value, parent):
    if not isinstance(value, str) or not value or any(c in value for c in "\0\r\n,"):
        raise ConfigError("invalid_platform_path")
    candidate = Path(value).expanduser()
    candidate = candidate if candidate.is_absolute() else parent / candidate
    if any(item.is_symlink() for item in (candidate, *candidate.parents)):
        raise ConfigError("platform_path_must_not_contain_links")
    return candidate.resolve()


@dataclass(frozen=True)
class PlatformConfig:
    source: Path
    deployment_id: str
    product: dict
    public_url: str
    bind_host: str
    https_port: int
    control_port: int
    root: Path
    certificate: Path
    private_key: Path
    network_pool: str
    max_runtimes: int
    resource_limits: dict
    images: dict
    version: int
    profile: str | None
    control_resources: dict
    capacity_policy: dict
    concurrency: dict
    orchestration: dict
    runtime_pool: dict
    feature_scopes: dict

    def verify_control_image(self, labels):
        image_supports_config(labels, self.version)
        if self.runtime_pool.get('idle_pause_enabled') and pool_settings.IDLE_CAPABILITY not in labels.get('org.peixian.worker.capabilities','').split(','):
            raise ConfigError('control_image_idle_activity_incompatible')
        if self.runtime_pool.get('capacity_wait_enabled') and pool_settings.WAIT_CAPABILITY not in labels.get('org.peixian.worker.capabilities', '').split(','):
            raise ConfigError('control_image_capacity_wait_incompatible')

    @property
    def worker_root(self):
        return self.root / "worker"

    @property
    def secrets(self):
        return self.root / "secrets"

    @property
    def control_container(self):
        return self.deployment_id + "-console"

    @property
    def control_volume(self):
        return self.deployment_id + "-control-data"

    @property
    def control_url(self):
        return "http://127.0.0.1:" + str(self.control_port)

    @property
    def compose_path(self):
        return self.root / "generated" / "compose.server.json"

    @property
    def memory_budget_mib(self):
        return self.resource_budget["memory_required_mib"]

    @property
    def cpu_budget(self):
        return self.resource_budget["cpu_required"]

    @property
    def resource_budget(self):
        return capacity.budget(self.version, self.max_runtimes, self.resource_limits,
                               self.control_resources, self.capacity_policy)

    @property
    def concurrency_environment(self):
        return {"PX_" + key.upper(): str(value) for key, value in self.concurrency.items()}

    @property
    def orchestration_environment(self):
        return orchestration_settings.environment(self.orchestration) if self.version >= 3 else {}


def load_config(path):
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ConfigError("platform_configuration_unavailable") from None
    fields = {"version", "deployment_id", "product", "public_url", "bind_host", "https_port", "control_port",
              "data_root", "tls", "network_pool", "max_runtimes", "resource_limits", "images", "feature_scopes"}
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] not in (1, 2, 3, 4):
        raise ConfigError("invalid_platform_configuration_version_or_fields")
    version = raw["version"]
    if version >= 2:
        fields |= {"profile", "control_resources", "capacity_policy", "concurrency"}
    if version >= 3:
        fields.add("orchestration")
    if version == 4:
        fields.add("runtime_pool")
    if (set(raw) - fields or (version == 2 and raw.get("profile") != "single-host-50-io")
            or (version == 3 and raw.get("profile") != "single-host-orchestration")
            or (version == 4 and (raw.get("profile") != "single-host-on-demand" or "runtime_pool" not in raw))):
        raise ConfigError("invalid_platform_configuration_version_or_fields")
    identity = raw.get("deployment_id", "agent-platform")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", identity):
        raise ConfigError("invalid_deployment_id")
    try:
        if not isinstance(raw.get("public_url"), str):
            raise ValueError()
        public = urlsplit(raw["public_url"])
        public_port = public.port if public.port is not None else 443
        if (public.scheme != "https" or not public.hostname or public.username or public.password or public.query
                or public.fragment or public.path not in ("", "/") or any(c.isspace() for c in raw["public_url"])):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ConfigError("public_url_requires_https_origin") from None
    ports = [raw.get("https_port", public_port), raw.get("control_port", 14090)]
    if any(type(p) is not int or not 1 <= p <= 65535 for p in ports) or ports[0] == ports[1] or ports[0] != public_port:
        raise ConfigError("invalid_or_inconsistent_server_ports")
    try:
        host = str(ipaddress.ip_address(raw.get("bind_host", "0.0.0.0")))
        pool = ipaddress.ip_network(raw.get("network_pool", "10.240.0.0/16"), strict=True)
        if pool.version != 4 or not pool.is_private or not 16 <= pool.prefixlen <= 24:
            raise ValueError()
    except (TypeError, ValueError):
        raise ConfigError("invalid_bind_host_or_network_pool") from None
    maximum = raw.get("max_runtimes", 4)
    try:
        capacity.runtime_limit(version, maximum)
    except ValueError as error:
        raise ConfigError(str(error)) from None
    limits = json.loads(json.dumps(LIMITS))
    given = raw.get("resource_limits", {})
    if not isinstance(given, dict) or set(given) - set(limits):
        raise ConfigError("invalid_resource_limits")
    for name, values in given.items():
        if not isinstance(values, dict) or set(values) - {"cpus", "memory_mib"}:
            raise ConfigError("invalid_resource_limits")
        limits[name].update(values)
    for name, values in limits.items():
        if (type(values["cpus"]) not in (float, int) or not 0.1 <= values["cpus"] <= 32
                or type(values["memory_mib"]) is not int or not 128 <= values["memory_mib"] <= 65536):
            raise ConfigError("invalid_resource_limits")
    control = {"cpus": 1.0, "memory_mib": 512} if version == 1 else {"cpus": 2.0, "memory_mib": 2048}
    override = raw.get("control_resources", {})
    if not isinstance(override, dict) or set(override) - set(control):
        raise ConfigError("invalid_control_resources")
    control.update(override)
    if (type(control["cpus"]) not in (int, float) or not 0.5 <= control["cpus"] <= 32 or
            type(control["memory_mib"]) is not int or not 512 <= control["memory_mib"] <= 65536):
        raise ConfigError("invalid_control_resources")
    try:
        policy = capacity.policy(raw.get("capacity_policy", {}), control) if version >= 2 else {}
    except ValueError as error:
        raise ConfigError(str(error)) from None
    concurrency = concurrency_config(raw.get("concurrency", {})) if version >= 2 else {}
    try:
        orchestration = orchestration_settings.validate(raw.get("orchestration", {})) if version >= 3 else {}
        runtime_pool = pool_settings.validate(raw.get("runtime_pool", {})) if version == 4 else {}
    except ValueError as error:
        raise ConfigError(str(error)) from None
    feature_scopes = raw.get("feature_scopes", {})
    if (not isinstance(feature_scopes, dict) or set(feature_scopes) - {"task_spec_v1", "multi_agent_v1", "trusted_result_v2", "theft_provider_v1", "theft_mock_v2", "theft_planner_v1", "theft_native"}
            or any(not isinstance(v, list) or len(v)>10000
                   or any(not isinstance(uid,str) or not re.fullmatch(r"[a-f0-9]{32}",uid) for uid in v) or len(set(v))!=len(v)
                   for v in feature_scopes.values())):
        raise ConfigError("invalid_feature_scopes")
    product = raw.get("product", PRODUCT)
    if (not isinstance(product, dict) or set(product) != set(PRODUCT)
            or any(not isinstance(v, str) or not v.strip() or len(v) > 200 or any(c in v for c in "\0\r\n") for v in product.values())):
        raise ConfigError("invalid_product_identity")
    supplied_images = raw.get("images", {})
    if not isinstance(supplied_images, dict):
        raise ConfigError("invalid_image_configuration")
    images = {**IMAGES, **supplied_images}
    if set(images) != set(IMAGES) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:@_-]+", v)
                                         or v.endswith(":latest") or (":" not in v and "@" not in v) for v in images.values()):
        raise ConfigError("images_require_explicit_versions")
    tls = raw.get("tls", {})
    if not isinstance(tls, dict) or set(tls) != {"certificate", "private_key"}:
        raise ConfigError("tls_certificate_and_private_key_required")
    data_root = safe_path(raw.get("data_root", "./platform-data"), source.parent)
    if data_root == Path(data_root.anchor) or data_root == source.parent:
        raise ConfigError("data_root_requires_dedicated_directory")
    return PlatformConfig(source, identity, product, raw["public_url"].rstrip("/"), host, *ports,
                          data_root,
                          safe_path(tls["certificate"], source.parent), safe_path(tls["private_key"], source.parent),
                          str(pool), maximum, limits, images, version, raw.get("profile"), control, policy, concurrency, orchestration, runtime_pool, feature_scopes)
