"""Host-only lifecycle operations for isolated Peixian account runtimes.

No Docker socket is mounted into application containers. All commands are argv
arrays and every durable path is beneath the explicitly configured state root.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import ipaddress
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import time
import uuid


_capacity_spec = importlib.util.spec_from_file_location("runtime_capacity_contract", Path(__file__).with_name("platform-capacity.py"))
capacity_contract = importlib.util.module_from_spec(_capacity_spec)
_capacity_spec.loader.exec_module(capacity_contract)

MANAGED = "peixian.console.managed"
ID = re.compile(r"[a-f0-9]{32}")
SLUG = re.compile(r"[a-z][a-z0-9_-]{0,63}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_PACKAGE = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
DEFAULT_LIMITS = {"agent": {"cpus": 2.0, "memory_mib": 2048},
                  "gateway": {"cpus": 0.5, "memory_mib": 512},
                  "relay": {"cpus": 0.5, "memory_mib": 128}}


def normalize_limits(value=None):
    value = DEFAULT_LIMITS if value is None else value
    if not isinstance(value, dict) or set(value) != set(DEFAULT_LIMITS):
        raise RuntimeFailure("invalid_resource_limits")
    for name, item in value.items():
        if (not isinstance(item, dict) or set(item) != {"cpus", "memory_mib"} or
                type(item["cpus"]) not in (int, float) or not 0.1 <= item["cpus"] <= 64 or
                type(item["memory_mib"]) is not int or not 64 <= item["memory_mib"] <= 65536):
            raise RuntimeFailure("invalid_resource_limits")
    return json.loads(json.dumps(value))


class RuntimeFailure(Exception):
    def __init__(self, code, *, rolled_back=False, cleanup_confirmed=False):
        self.code, self.rolled_back = code, rolled_back
        self.cleanup_confirmed = cleanup_confirmed
        super().__init__(code)


class Deferred(Exception):
    pass


def check_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RuntimeFailure("invalid_runtime_identity")
    return value


def inside(root, candidate):
    root, candidate = Path(root).resolve(), Path(candidate).resolve()
    if not candidate.is_relative_to(root):
        raise RuntimeFailure("path_outside_worker_root")
    return candidate


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("xb") as handle:
        if os.name == "posix":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_secret(path, value):
    if not isinstance(value, str) or len(value) < 16 or any(c in value for c in "\r\n\0"):
        raise RuntimeFailure("invalid_private_credential")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        if os.name == "posix":
            os.fchmod(handle.fileno(), 0o600)
        handle.write(value)


def command(args, *, data=None, timeout=240, allowed=(0,)):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeFailure("host_command_unavailable") from None
    if result.returncode not in allowed:
        # Docker errors can contain mount paths or app logs: do not persist or print them.
        raise RuntimeFailure("host_command_failed")
    return result.stdout.decode("utf-8", errors="replace")


def protect_root(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise RuntimeFailure("worker_root_must_not_be_symlink")
    if os.name == "posix":
        os.chmod(root, 0o700)
        if shutil.which("setfacl") is None:
            raise RuntimeFailure("linux_acl_required_install_acl_package")
        return
    import csv
    rows = list(csv.reader(io.StringIO(command(["whoami", "/user", "/fo", "csv", "/nh"]))))
    sid = rows[0][-1] if rows else ""
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise RuntimeFailure("host_acl_identity_unavailable")
    command(["icacls", str(root), "/inheritance:r", "/grant:r",
             f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], timeout=30)


def grant_container_read(root):
    if os.name == "posix":
        for directory, directories, files in os.walk(root):
            os.chmod(directory, 0o700)
            for name in files:
                os.chmod(Path(directory) / name, 0o600)
        command(["setfacl", "-R", "-m", "u:10001:rX,m::rX", str(root)], timeout=30)


def unpack_plugin(data, expected, target):
    import zipfile
    if len(data) > MAX_PACKAGE or hashlib.sha256(data).hexdigest() != expected["digest"]:
        raise RuntimeFailure("plugin_digest_mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(item.file_size for item in members) > MAX_EXPANDED:
                raise RuntimeFailure("plugin_package_limit")
            names = set()
            for item in members:
                name = item.orig_filename
                relative = PurePosixPath(name)
                mode = item.external_attr >> 16
                if (name != item.filename or not name or relative.is_absolute() or ".." in relative.parts or
                        "\\" in name or ":" in name or "\0" in name or
                        stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or
                        name.casefold().rstrip("/") in names):
                    raise RuntimeFailure("unsafe_plugin_archive")
                names.add(name.casefold().rstrip("/"))
            manifest = json.loads(archive.read("manifest.json"))
            entry = manifest.get("entry", "entry.mjs")
            if (manifest.get("id") != expected["id"] or manifest.get("version") != expected["version"] or
                    entry != expected["manifest"].get("entry", "entry.mjs") or
                    not entry.endswith(".mjs") or entry.casefold() not in names or
                    manifest.get("opencode_version", "1.18.30") != "1.18.30"):
                raise RuntimeFailure("plugin_manifest_mismatch")
            target = Path(target)
            target.mkdir(parents=True, exist_ok=False)
            for item in members:
                destination = inside(target, target.joinpath(*PurePosixPath(item.filename).parts))
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
                    handle.write(archive.read(item))
            # The gateway probes a stable entry.mjs, including optional named test.
            if entry != "entry.mjs":
                if (target / "entry.mjs").exists():
                    raise RuntimeFailure("plugin_entry_collision")
                (target / "entry.mjs").write_text(
                    "export { default } from " + json.dumps("./" + entry) + ";\n"
                    "export * from " + json.dumps("./" + entry) + ";\n", encoding="utf-8")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise RuntimeFailure("invalid_plugin_archive") from None


AGENT_HEALTH = (
    "import base64,json,urllib.request;"
    "p=open('/run/secrets/opencode-password').read().rstrip('\\r\\n');"
    "h={'Authorization':'Basic '+base64.b64encode(('opencode:'+p).encode()).decode()};"
    "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:4096/global/health',headers=h),timeout=3);"
    "d=json.load(r);assert d.get('healthy') and d.get('version')=='1.18.30'"
)
GATEWAY_HEALTH = (
    "import json,urllib.request;"
    "p=open('/run/secrets/gateway-token').read().rstrip('\\r\\n');"
    "r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/health',headers={'X-Peixian-Key':p}),timeout=3);"
    "assert json.load(r).get('ok')"
)
RELAY_HEALTH = "import json,urllib.request;assert json.load(urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3)).get('ok')"

# Executed only in the control container, with secret values supplied on stdin.
CONTROL_GET = """import json,sys,urllib.request
v=json.load(sys.stdin)
try:
 r=urllib.request.urlopen(urllib.request.Request(v['url'],headers={'X-Peixian-Key':v['key']}),timeout=8)
 b=r.read(2097153)
 if len(b)>2097152: raise ValueError()
 print(json.dumps(json.loads(b)))
except Exception:
 print('{"error":"private_gateway_unavailable"}')
 sys.exit(2)
"""

CONTROL_RUNTIME = """import json,sys,urllib.request
v=json.load(sys.stdin)
try:
 body=json.dumps(v['body']).encode() if v.get('body') is not None else None
 req=urllib.request.Request(v['url'],data=body,method=v['method'],headers={'X-Peixian-Key':v['key'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=v['timeout']) as r:
  b=r.read(262145)
  if len(b)>262144: raise ValueError()
  print(json.dumps(json.loads(b)))
except Exception:
 print('{"error":"runtime_probe_unavailable"}')
 sys.exit(2)
"""


def compose_spec(spec, release, *, agent_image, gateway_image, limits=None, deployment_id=None,
                 control_container="peixian-console", orchestration=None):
    runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
    project = "px-" + runtime_id
    release = Path(release).resolve()
    revision = spec["revision"]
    if type(revision) is not int or revision < 1:
        raise RuntimeFailure("invalid_revision")
    labels = {MANAGED: "true", "peixian.runtime_id": runtime_id, "peixian.uid": uid, "peixian.revision": str(revision)}
    if deployment_id:
        labels["peixian.deployment"] = deployment_id
    common = {
        "user": "10001:10001", "init": True, "restart": "unless-stopped", "read_only": True,
        "pull_policy": "never",
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "pids_limit": 128,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=128m,mode=1777"], "stop_grace_period": "30s",
        "labels": labels, "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }

    def bind(source, target):
        return {"type": "bind", "source": str(release / source), "target": target, "read_only": True,
                "bind": {"create_host_path": False}}

    def health(code, period="60s"):
        return {"test": ["CMD", "python3", "-c", code], "interval": "10s", "timeout": "5s",
                "start_period": period, "retries": 12}

    def volume(source, target, readonly=False):
        return {"type": "volume", "source": source, "target": target, "read_only": readonly}

    legacy = spec["private"].get("legacy") or {}
    if not isinstance(legacy, dict) or set(legacy) - {"home_volume", "workspace_volume", "files_volume"}:
        raise RuntimeFailure("invalid_legacy_volume_mapping")
    volumes = {}
    for name in ("home", "workspace", "files"):
        external = legacy.get(name + "_volume")
        if external is not None:
            if not isinstance(external, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", external):
                raise RuntimeFailure("invalid_legacy_volume_name")
            volumes[name] = {"name": external, "external": True}
        else:
            volumes[name] = {"name": project + "-" + name, "labels": labels}

    services = {
        "agent": {
            **common, "image": agent_image, "platform": "linux/amd64", "working_dir": "/workspace",
            "cpus": 2.0, "mem_limit": "2g", "pids_limit": 256,
            "environment": {"PEIXIAN_MANAGED_ROOT": "/managed"},
            "volumes": [volume("home", "/home/opencode"), volume("workspace", "/workspace"),
                        volume("files", "/files", True), bind("agent", "/managed"),
                        bind("private/opencode-password", "/run/secrets/opencode-password")],
            "networks": ["internal"], "healthcheck": health(AGENT_HEALTH),
        },
        "gateway": {
            **common, "image": gateway_image, "platform": "linux/amd64", "cpus": 0.5, "mem_limit": "512m",
            "entrypoint": ["python3", "-m", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"],
            "environment": {"MANAGED_ROOT": "/managed", "ACCOUNT_ID": uid, "WORKSPACE": "/workspace",
                            "FILES_ROOT": "/files", "OPENCODE_URL": "http://agent:4096",
                            "INTERNAL_TOKEN_FILE": "/run/secrets/gateway-token",
                            "OPENCODE_PASSWORD_FILE": "/run/secrets/opencode-password"},
            "volumes": [volume("workspace", "/workspace"), volume("files", "/files"),
                        bind("gateway", "/managed"), bind("private/gateway-token", "/run/secrets/gateway-token"),
                        bind("private/opencode-password", "/run/secrets/opencode-password")],
            "networks": {"internal": {}, "management": {"aliases": [project + "-gateway"]}},
            "depends_on": {"agent": {"condition": "service_healthy"}},
            "healthcheck": health(GATEWAY_HEALTH), "sysctls": {"net.ipv4.ip_forward": "0"},
        },
        "model-relay": {
            **common, "image": gateway_image, "platform": "linux/amd64", "cpus": 0.5, "mem_limit": "128m",
            "entrypoint": ["python3", "-m", "uvicorn", "gateway.model_relay:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"],
            "environment": {"MANAGED_ROOT": "/managed", "ACCOUNT_ID": uid},
            "volumes": [bind("relay", "/managed")],
            "networks": ["internal", "egress"], "healthcheck": health(RELAY_HEALTH, "10s"),
            "sysctls": {"net.ipv4.ip_forward": "0"},
        },
    }
    if "runtime_key" in spec["private"]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", control_container):
            raise RuntimeFailure("invalid_control_container")
        shared_env = {"PX_RUNTIME_PROTOCOL": "2", "PX_RUNTIME_ID": runtime_id}
        shared_env.update({"PX_R2_" + key.upper(): str(value) for key, value in (orchestration or {}).items()})
        services["gateway"]["environment"].update(shared_env)
        services["gateway"]["environment"].update({
            "PX_CONTROL_URL": "http://" + control_container + ":8080",
            "PX_RUNTIME_KEY_FILE": "/run/secrets/runtime-key",
            "PX_RELAY_MANAGEMENT_KEY_FILE": "/run/secrets/relay-management-key",
            "PX_RELAY_URL": "http://model-relay:8081",
        })
        services["gateway"]["volumes"].extend([
            bind("private/runtime-key", "/run/secrets/runtime-key"),
            bind("private/relay-management-key", "/run/secrets/relay-management-key"),
        ])
        services["model-relay"]["environment"].update(shared_env)
        services["model-relay"]["environment"].update({
            "PX_GATEWAY_URL": "http://gateway:8080",
            "PX_RELAY_MANAGEMENT_KEY_FILE": "/run/secrets/relay-management-key",
        })
        services["model-relay"]["volumes"].append(bind("private/relay-management-key", "/run/secrets/relay-management-key"))
    limits = normalize_limits(limits)
    for name, key in (("agent", "agent"), ("gateway", "gateway"), ("model-relay", "relay")):
        services[name].update(cpus=limits[key]["cpus"], mem_limit=str(limits[key]["memory_mib"]) + "m")
    return {
        "name": project, "services": services, "volumes": volumes,
        "networks": {
            "internal": {"name": project + "-internal", "internal": True, "labels": labels},
            "management": {"name": project + "-management", "internal": True, "labels": labels},
            "egress": {"name": project + "-egress", "internal": False, "labels": labels},
        },
    }


class RuntimeManager:
    def __init__(self, root, *, control_container="peixian-console",
                 agent_image="peixian-opencode:1.18.30-managed-r1",
                 gateway_image="peixian-gateway:console-r1", maximum=4,
                 resource_limits=None, network_pool=None, deployment_id=None, config_version=1,
                 control_resources=None, capacity_policy=None, orchestration=None):
        self.root = Path(root).absolute()
        protect_root(self.root)
        self.root = self.root.resolve()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", control_container):
            raise RuntimeFailure("invalid_control_container")
        try:
            capacity_contract.runtime_limit(config_version, maximum)
        except ValueError as error:
            raise RuntimeFailure(str(error)) from None
        self.config_version = config_version
        self.control_resources = control_resources or ({"cpus": 2.0, "memory_mib": 2048} if config_version >= 2 else {"cpus": 1.0, "memory_mib": 512})
        self.capacity_policy = capacity_policy or {}
        self.orchestration = orchestration or {}
        self.reconcile_cursor = 0
        self.control_container, self.agent_image, self.gateway_image = control_container, agent_image, gateway_image
        self.maximum = maximum
        self.limits = normalize_limits(resource_limits)
        if deployment_id is not None and not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", deployment_id):
            raise RuntimeFailure("invalid_deployment_identity")
        self.deployment_id = deployment_id
        try:
            self.network_pool = ipaddress.ip_network(network_pool) if network_pool else None
            if self.network_pool and (self.network_pool.version != 4 or not self.network_pool.is_private or self.network_pool.prefixlen > 24):
                raise ValueError()
        except ValueError:
            raise RuntimeFailure("invalid_network_pool") from None
        self.docker = shutil.which("docker")
        if not self.docker:
            raise RuntimeFailure("docker_required")
        if os.getenv("DOCKER_HOST", "").startswith(("tcp:", "ssh:")):
            raise RuntimeFailure("local_docker_required")
        context = json.loads(self.docker_run("context", "inspect"))[0]
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not endpoint.startswith(("npipe://", "unix://")):
            raise RuntimeFailure("local_docker_required")

    def docker_run(self, *args, data=None, timeout=240, allowed=(0,)):
        return command([self.docker, *args], data=data, timeout=timeout, allowed=allowed)

    def directory(self, runtime_id):
        return inside(self.root, self.root / "runtimes" / check_id(runtime_id))

    def compose(self, file, *args, timeout=240):
        # Infrastructure outlives every release. Compose must not recreate a network
        # to update revision labels while the control container is attached to it.
        source = json.loads(Path(file).read_text(encoding="utf-8"))
        identity = check_id(source["name"].removeprefix("px-"))
        directory = self.directory(identity)
        inside(directory, file)
        for group in ("networks", "volumes"):
            source[group] = {key: {"name": item["name"], "external": True} for key, item in source[group].items()}
        limits = getattr(self, "limits", DEFAULT_LIMITS)
        for name, key in (("agent", "agent"), ("gateway", "gateway"), ("model-relay", "relay")):
            source["services"][name].update(cpus=limits[key]["cpus"], mem_limit=str(limits[key]["memory_mib"]) + "m")
            if getattr(self, "config_version", 1) >= 2:
                source["services"][name]["memswap_limit"] = source["services"][name]["mem_limit"]
        target = directory / "operations" / (Path(file).parent.name + "-compose.json")
        write_json(target, source)
        return self.docker_run("compose", "-f", str(target), *args, timeout=timeout)

    def ensure_networks(self, spec):
        identity, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        if getattr(self, "config_version", 1) >= 2:
            identifiers = self.docker_run("network", "ls", "--format", "{{.ID}}").split()
            records = json.loads(self.docker_run("network", "inspect", *identifiers)) if identifiers else []
            try:
                retained = capacity_contract.retained_ids(self.root) | {identity}
                network = capacity_contract.network_capacity(self.network_pool, records, self.deployment_id, self.maximum, retained)
            except ValueError as error:
                raise RuntimeFailure(str(error)) from None
            if network["status"] != "passed":
                raise RuntimeFailure("configured_network_pool_capacity_insufficient")
        existing = set(self.docker_run("network", "ls", "--format", "{{.Name}}").split())
        for suffix in ("internal", "management", "egress"):
            name = "px-" + identity + "-" + suffix
            internal = suffix != "egress"
            if name not in existing:
                args = ["network", "create", "--driver", "bridge", "--label", MANAGED + "=true",
                        "--label", "peixian.runtime_id=" + identity, "--label", "peixian.uid=" + uid]
                if getattr(self, "deployment_id", None):
                    args.extend(["--label", "peixian.deployment=" + self.deployment_id])
                if getattr(self, "network_pool", None):
                    args.extend(["--subnet", self.available_subnet()])
                if internal:
                    args.append("--internal")
                self.docker_run(*args, name)
            record = json.loads(self.docker_run("network", "inspect", name))[0]
            labels = record.get("Labels") or {}
            if (record.get("Name") != name or record.get("Internal") is not internal or
                    labels.get(MANAGED) != "true" or labels.get("peixian.runtime_id") != identity or
                    labels.get("peixian.uid") != uid):
                raise RuntimeFailure("runtime_network_owner_mismatch")
            if getattr(self, "deployment_id", None) and labels.get("peixian.deployment") != self.deployment_id:
                raise RuntimeFailure("runtime_network_deployment_mismatch")

    def available_subnet(self):
        identifiers = self.docker_run("network", "ls", "--format", "{{.ID}}").split()
        records = json.loads(self.docker_run("network", "inspect", *identifiers)) if identifiers else []
        used = [ipaddress.ip_network(item["Subnet"], strict=False) for record in records
                for item in (record.get("IPAM", {}).get("Config") or []) if item.get("Subnet")]
        for subnet in self.network_pool.subnets(new_prefix=28):
            if not any(other.version == 4 and subnet.overlaps(other) for other in used):
                return str(subnet)
        raise RuntimeFailure("configured_network_pool_exhausted")

    def state(self, runtime_id):
        file = self.directory(runtime_id) / "state.json"
        if not file.exists():
            return None
        data = json.loads(file.read_text(encoding="utf-8"))
        if data["runtime_id"] != runtime_id or data["uid"] is None:
            raise RuntimeFailure("invalid_local_runtime_state")
        return data

    def private_get(self, spec, endpoint):
        if endpoint not in ("/health", "/session/status", "/global/health", "/skill", "/internal/facts/status"):
            raise RuntimeFailure("invalid_private_probe")
        url = "http://px-" + check_id(spec["runtime_id"]) + "-gateway:8080" + endpoint
        text = self.docker_run("exec", "-i", self.control_container, "python3", "-c", CONTROL_GET,
                               data=json_bytes({"url": url, "key": spec["private"]["gateway_key"]}), timeout=15)
        result = json.loads(text)
        if not isinstance(result, list if endpoint == "/skill" else dict):
            raise RuntimeFailure("invalid_private_probe_response")
        return result

    def runtime_request(self, spec, method, endpoint, body=None):
        if (method, endpoint) not in {("GET", "/internal/runtime/state"),
                                     ("POST", "/internal/runtime/gate"),
                                     ("POST", "/internal/runtime/cancel")}:
            raise RuntimeFailure("invalid_runtime_probe")
        timeout = getattr(self, "orchestration", {}).get("gate_probe_seconds", 2)
        url = "http://px-" + check_id(spec["runtime_id"]) + "-gateway:8080" + endpoint
        raw = self.docker_run("exec", "-i", self.control_container, "python3", "-c", CONTROL_RUNTIME,
                              data=json_bytes({"url": url, "key": spec["private"]["gateway_key"],
                                               "method": method, "body": body, "timeout": timeout}),
                              timeout=timeout + 1)
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get("protocol_version") != 2
                or value.get("runtime_id") != spec["runtime_id"]):
            raise RuntimeFailure("invalid_runtime_probe_response")
        return value

    def components(self, spec):
        """A complete three-service inventory; missing/foreign evidence stays unknown."""
        runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        states = {"agent": "stopped", "gateway": "stopped", "relay": "stopped"}
        try:
            ids = self.docker_run("ps", "-a", "--filter", "label=com.docker.compose.project=px-" + runtime_id,
                                  "--format", "{{.ID}}", timeout=2).split()
            records = json.loads(self.docker_run("inspect", *ids, timeout=2)) if ids else []
            seen = set()
            for record in records:
                labels = record.get("Config", {}).get("Labels") or {}
                name = {"agent": "agent", "gateway": "gateway", "model-relay": "relay"}.get(labels.get("com.docker.compose.service"))
                if (name is None or name in seen or labels.get(MANAGED) != "true"
                        or labels.get("peixian.runtime_id") != runtime_id or labels.get("peixian.uid") != uid
                        or (getattr(self, "deployment_id", None) and labels.get("peixian.deployment") != self.deployment_id)):
                    raise ValueError()
                seen.add(name)
                state = record.get("State", {})
                if type(state.get("Running")) is not bool or state.get("Restarting") or state.get("Paused"):
                    raise ValueError()
                states[name] = "running" if state["Running"] else "stopped"
            return states, True
        except (RuntimeFailure, ValueError, KeyError, TypeError):
            return {name: "unknown" for name in states}, False

    def pool_inventory(self, targets):
        """Read-only, bounded host inventory including unreserved retained resources."""
        known = {item["runtime_id"]: item["uid"] for item in targets}
        resources = {}
        deadline = time.monotonic() + 12
        try:
            if not self.deployment_id:
                raise ValueError()
            filters = ["--filter", "label=peixian.runtime_id", "--filter", "label=peixian.deployment=" + self.deployment_id]
            for kind, listing in (("container", ("ps", "-a")), ("volume", ("volume", "ls")), ("network", ("network", "ls"))):
                # Older owned volumes predate deployment/uid labels. Include them
                # by registered runtime identity; never attribute another deployment.
                selected = ["--filter", "label=" + MANAGED + "=true"] if kind == "volume" else filters
                names = self.docker_run(*listing, *selected, "--format", "{{.Name}}" if kind == "volume" else "{{.ID}}", timeout=2).split()
                if len(names) > 10000:
                    raise ValueError()
                for offset in range(0, len(names), 40):
                    if time.monotonic() >= deadline:
                        raise ValueError()
                    prefix = () if kind == "container" else (kind,)
                    for record in json.loads(self.docker_run(*prefix, "inspect", *names[offset:offset+40], timeout=2)):
                        labels = (record.get("Config", {}).get("Labels") if kind == "container" else record.get("Labels")) or {}
                        rid, uid = labels.get("peixian.runtime_id"), labels.get("peixian.uid")
                        if kind == "volume":
                            owner = labels.get("peixian.deployment")
                            if owner not in (None, self.deployment_id):
                                continue
                            if owner is None:
                                if rid not in known:
                                    continue
                                labels = {**labels, "peixian.deployment": self.deployment_id}
                            uid = uid or known.get(rid)
                        if rid not in known or uid != known[rid] or labels.get(MANAGED) != "true" or labels.get("peixian.deployment") != self.deployment_id:
                            raise ValueError()
                        item = resources.setdefault(rid, {"runtime_id": rid, "uid": uid, "running": False, "mutation_state": "idle"})
                        if kind == "container":
                            state = record.get("State", {})
                            if type(state.get("Running")) is not bool:
                                raise ValueError()
                            item["running"] |= state["Running"] or bool(state.get("Restarting")) or bool(state.get("Paused"))
            root = self.root / "runtimes"
            for directory in root.iterdir() if root.exists() else []:
                if time.monotonic() >= deadline or directory.is_symlink() or not directory.is_dir() or directory.name not in known:
                    raise ValueError()
                rid = directory.name
                item = resources.setdefault(rid, {"runtime_id": rid, "uid": known[rid], "running": False, "mutation_state": "idle"})
                item["mutation_state"] = self.mutation_state(rid)
            return list(resources.values()), True
        except (RuntimeFailure, ValueError, KeyError, TypeError, OSError):
            return list(resources.values()), False

    def mutation_record(self, job, state):
        write_json(self.directory(job["runtime_id"]) / "mutation.json", {
            "job_id": job["id"], "attempt": job["attempt"], "runtime_id": job["runtime_id"],
            "revision": job["revision"], "spec_digest": job["spec_digest"],
            "state": state, "recorded_at": int(time.time()),
        })

    def mutation_state(self, runtime_id):
        path = self.directory(runtime_id) / "mutation.json"
        if not path.exists():
            return "idle"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("runtime_id") != runtime_id or value.get("state") not in ("idle", "running", "unknown"):
                return "unknown"
            # A prior process dying with an in-flight Docker operation is not proof of exit.
            return "unknown" if value["state"] == "running" else value["state"]
        except (ValueError, OSError):
            return "unknown"

    def observe(self, job, spec, host_boot_id):
        states, complete = self.components(spec)
        stopped = complete and all(value == "stopped" for value in states.values())
        mutation = self.mutation_state(spec["runtime_id"])
        gate = None
        if states["gateway"] == "running":
            try:
                gate = self.runtime_request(spec, "GET", "/internal/runtime/state")
            except (RuntimeFailure, ValueError):
                complete = False
        activity = gate.get("activity", {}) if gate else {}
        if not stopped and (not gate or activity.get("complete") is not True or activity.get("unknown") is not False):
            complete = False
        if gate:
            total = activity.get("total")
            owner = job.get("gate_owner") or "job:" + job["id"] + ":" + str(job["attempt"])
            if (type(total) is not int or total < 0 or activity.get("idle") is not (total == 0)
                    or gate.get("gate_epoch") != job["gate_epoch"] or gate.get("owner") != owner
                    or not isinstance(gate.get("boot_id"), str) or not gate["boot_id"]
                    or gate.get("gate") not in ("open", "draining", "closed")):
                complete = False
        revision = gate.get("revision", 0) if gate else 0
        value = {"observation_id": uuid.uuid4().hex, "runtime_id": spec["runtime_id"],
                 "job_id": job["id"], "attempt": job["attempt"], "lease": job["lease"],
                 "state_version": job["state_version"], "host_boot_id": host_boot_id,
                 "gateway_boot_id": gate.get("boot_id", "unknown") if gate else ("absent" if stopped else "unknown"),
                 "gate_epoch": gate.get("gate_epoch", job["gate_epoch"]) if gate else job["gate_epoch"],
                 "observed_at": int(time.time()), "components": states, "mutation_state": mutation,
                 "complete": complete, "accepting": gate.get("gate") == "open" if gate else False,
                 "egress_closed": bool(stopped or (gate and isinstance(gate.get("relay"), dict)
                                                      and gate["relay"].get("gate") == "closed")),
                 "activity_count": activity.get("total") if gate else (0 if stopped else None),
                 "applied_revision": revision, "spec_digest": None, "evidence_ref": uuid.uuid4().hex}
        if job.get('reason')=='idle_timeout':
            value['idle_proof']=gate.get('idle_proof') if gate else None
            if gate and (gate.get('needs_reconcile') is not False or (gate.get('relay') or {}).get('needs_reconcile') is not False):
                value['complete']=False
        local = self.state(spec["runtime_id"])
        if local and local.get("revision") == revision:
            try:
                publication = json.loads((Path(local["compose"]).parent / "publication.json").read_text(encoding="utf-8"))
                value["spec_digest"] = publication["digest"]
            except (OSError, ValueError, KeyError):
                value["complete"] = False
        if value["complete"] and not stopped and value["spec_digest"] is None:
            value["complete"] = False
        # Durable evidence excludes lease and secrets, and is safe for a stopped backup.
        write_json(self.directory(spec["runtime_id"]) / "last-observation.json",
                   {key: item for key, item in value.items() if key != "lease"})
        return value, gate

    def attach_control(self, runtime_id, uid=None):
        network = "px-" + check_id(runtime_id) + "-management"
        record = json.loads(self.docker_run("network", "inspect", network))[0]
        labels = record.get("Labels") or {}
        if (record.get("Name") != network or record.get("Internal") is not True or
                labels.get(MANAGED) != "true" or labels.get("peixian.runtime_id") != runtime_id):
            raise RuntimeFailure("management_network_owner_mismatch")
        if uid is None:
            state = self.state(runtime_id)
            if state is None:
                pending = self.directory(runtime_id) / "pending.json"
                state = json.loads(pending.read_text(encoding="utf-8")) if pending.is_file() else {}
            if state.get("runtime_id") != runtime_id:
                raise RuntimeFailure("runtime_owner_mismatch")
            uid = state.get("uid")
        uid = check_id(uid)
        deployment = getattr(self, "deployment_id", None)
        if (labels.get("peixian.uid") != uid
                or (deployment and labels.get("peixian.deployment") != deployment)):
            raise RuntimeFailure("management_network_owner_mismatch")
        control = json.loads(self.docker_run("inspect", self.control_container))[0]
        control_labels = control.get("Config", {}).get("Labels") or {}
        if (control.get("Name") != "/" + self.control_container
                or (deployment and control_labels.get("peixian.deployment") != deployment)):
            raise RuntimeFailure("management_control_owner_mismatch")
        attached = control.get("NetworkSettings", {}).get("Networks", {})
        if network not in attached:
            network_id, control_id = record.get("Id"), control.get("Id")
            if not network_id or not control_id:
                raise RuntimeFailure("management_network_identity_missing")
            try:
                self.docker_run("network", "connect", network_id, control_id, timeout=30)
            except RuntimeFailure:
                # Another current deployment maintenance operation may already
                # have connected it. Read back the same immutable identities.
                pass
            current = json.loads(self.docker_run("inspect", control_id))[0]
            attached = current.get("NetworkSettings", {}).get("Networks", {})
            if attached.get(network, {}).get("NetworkID") != network_id:
                raise RuntimeFailure("management_network_reconnect_unconfirmed")
        elif record.get("Id") and attached[network].get("NetworkID") != record["Id"]:
            raise RuntimeFailure("management_network_owner_mismatch")

    def verify(self, spec, revision):
        self.attach_control(spec["runtime_id"], spec.get("uid"))
        for _ in range(18):
            try:
                health = self.private_get(spec, "/health")
                native = self.private_get(spec, "/global/health")
                # This instance route initializes managed Config, Skills and Plugin services.
                skills = self.private_get(spec, "/skill")
                if revision == spec['revision']:
                    expected={p['id'].removeprefix('peixian-records-') for p in spec.get('plugins',[]) if p['id'].startswith('peixian-records-')}
                    if expected:
                        facts=self.private_get(spec,'/internal/facts/status')
                        if facts.get('protocol')!='facts-coordinator-v1' or facts.get('ready') is not True or set(facts.get('modules',[]))!=expected:
                            raise RuntimeFailure('runtime_facts_protocol_mismatch')
                if (health.get("ok") is True and health.get("revision") == revision and
                        health.get("runtime_id") == spec["runtime_id"] and native.get("healthy") is True and
                        native.get("version") == "1.18.30" and isinstance(skills, list)):
                    return
            except (RuntimeFailure, ValueError):
                pass
            time.sleep(2)
        raise RuntimeFailure("runtime_revision_health_failed")

    def wait_idle(self, spec, heartbeat, *, seconds=2):
        # Historical migration callers also get one bounded probe, never a 300 s hold.
        heartbeat()
        if "runtime_key" in spec.get("private", {}):
            state = self.runtime_request(spec, "GET", "/internal/runtime/state")
            activity = state.get("activity", {})
            if activity.get("complete") is not True or activity.get("unknown") is not False:
                raise RuntimeFailure("runtime_activity_unknown")
            if activity.get("idle") is not True:
                raise Deferred()
            return
        status = self.private_get(spec, "/session/status")
        if any(not isinstance(item, dict) or item.get("type") != "idle" for item in status.values()):
            raise Deferred()

    def reconcile(self, *, batch=4):
        failures = []
        directory = self.root / "runtimes"
        if not directory.is_dir():
            return failures
        accounts = sorted(account for account in directory.iterdir() if ID.fullmatch(account.name))
        if not accounts:
            return failures
        start = getattr(self, "reconcile_cursor", 0) % len(accounts)
        selected = [accounts[(start + i) % len(accounts)] for i in range(min(batch, len(accounts)))]
        self.reconcile_cursor = (start + len(selected)) % len(accounts)
        for account in selected:
            try:
                value = self.state(account.name)
                if value is None or value.get("paused") or not self.running(account.name):
                    continue
                check_id(value["uid"])
                inside(account, Path(value["compose"]))
                self.attach_control(account.name)
            except (RuntimeFailure, ValueError, KeyError, OSError):
                failures.append("registered_runtime_network_reconcile_failed")
        return failures

    def capacity(self, runtime_id):
        filtering = ["--filter", "label=peixian.deployment=" + self.deployment_id] if getattr(self, "deployment_id", None) else []
        ids = self.docker_run("ps", *filtering, "--filter", "label=" + MANAGED + "=true",
                              "--filter", "label=com.docker.compose.service=agent", "--format", "{{.ID}}").split()
        records = json.loads(self.docker_run("inspect", *ids)) if ids else []
        others = {item["Config"]["Labels"].get("peixian.runtime_id") for item in records}
        others.discard(runtime_id)
        if len(others) >= self.maximum:
            raise RuntimeFailure("runtime_capacity_reached")
        info = json.loads(self.docker_run("info", "--format", "{{json .}}"))
        # Use the same versioned admission policy as platform preflight.
        # Sharing is CPU planning only; RAM ceilings and headroom remain strict.
        limits = getattr(self, "limits", DEFAULT_LIMITS)
        try:
            required = capacity_contract.budget(getattr(self, "config_version", 1), self.maximum, limits,
                                                getattr(self, "control_resources", {"cpus": 1.0, "memory_mib": 512}),
                                                getattr(self, "capacity_policy", {}))
        except ValueError as error:
            raise RuntimeFailure(str(error)) from None
        result = capacity_contract.evaluate(info, required)
        if "docker_memory_below_configured_runtime_budget" in result["failures"]:
            raise RuntimeFailure("docker_memory_budget_exceeded")
        if result["failures"]:
            raise RuntimeFailure("docker_cpu_budget_exceeded")

    def prepare(self, spec, download):
        runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        revision = spec["revision"]
        if type(revision) is not int or revision < 1:
            raise RuntimeFailure("invalid_revision")
        directory = self.directory(runtime_id)
        directory.mkdir(parents=True, exist_ok=True)
        release = inside(directory, directory / "releases" / str(revision))
        digest = hashlib.sha256(json_bytes(spec)).hexdigest()
        if release.exists():
            if json.loads((release / "publication.json").read_text()) != {"digest": digest, "uid": uid, "revision": revision}:
                raise RuntimeFailure("immutable_release_conflict")
            return release
        stage = directory / "releases" / (".staging-" + uuid.uuid4().hex)
        stage.mkdir(parents=True, exist_ok=False)
        for folder in ("agent/skills", "agent/loaders", "gateway/plugins", "relay", "private"):
            (stage / folder).mkdir(parents=True, exist_ok=True)
        for folder in ("agent", "gateway"):
            shutil.copyfile(Path(__file__).with_name("plugin-client.mjs"), stage / folder / "platform-client.mjs")
        config = json.loads(json.dumps(spec["config"]))
        config["plugin"] = []
        config["skills"] = {"paths": ["/managed/skills"]}
        seven_ids = {"peixian-records-" + m for m in ("funds","calls","portrait","composite","night","vehicle","lookup")}
        provider_ids={'peixian-theft-'+m for m in ('incidents','captures','tracks','night','community','warning-detail','warning-logs','profile')}
        has_provider=any(p['id'] in provider_ids for p in spec['plugins'])
        has_seven = any(p["id"] in seven_ids for p in spec["plugins"])
        if has_seven and any(p["id"] == "peixian-synthetic-records" for p in spec["plugins"]):
            raise RuntimeFailure("ambiguous_records_plugin_chain")
        facts_token = hmac.new(spec["private"]["gateway_key"].encode(), b"facts-agent-v1", hashlib.sha256).hexdigest()
        if has_seven or has_provider:
            # These fixed platform helpers are not user-installed plugin tools.
            # Gateway still binds every invocation to the authorized durable Run.
            config.setdefault("permission", {}).update({name: "allow" for name in (
                "peixian_get_scenario_context", "peixian_prepare_scenario_facts", "peixian_check_scenario_summary")})
            source = Path(__file__).with_name("platform-facts")
            shutil.copytree(source, stage / "gateway/platform-facts", ignore=shutil.ignore_patterns("*.test.mjs", "fixtures.json", "coordinator.mjs"))
            shutil.copyfile(source / "agent-client.mjs", stage / "agent/facts-client.mjs")
            (stage / "agent/loaders/platform-facts.mjs").write_text(
                "import { helpers } from '../facts-client.mjs';\nexport default async () => helpers(" + json.dumps(facts_token) + ");\n", encoding="utf-8")
            config["plugin"].append("file:///managed/loaders/platform-facts.mjs")
        tests = {}
        seen = set()
        for plugin in spec["plugins"]:
            if (not SLUG.fullmatch(plugin["id"]) or not VERSION.fullmatch(plugin["version"]) or
                    not DIGEST.fullmatch(plugin["digest"]) or plugin["id"] in seen or
                    not isinstance(plugin["options"], dict)):
                raise RuntimeFailure("invalid_published_plugin")
            seen.add(plugin["id"])
            relative = Path("plugins") / plugin["id"] / plugin["version"]
            unpack_plugin(download(plugin["digest"]), plugin, stage / "agent" / relative)
            shutil.copytree(stage / "agent" / relative, stage / "gateway" / relative)
            entry = "/managed/" + relative.as_posix() + "/entry.mjs"
            bindings = plugin.get("platform_connections", {})
            if not isinstance(bindings, dict) or any(not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", alias) or not isinstance(value, dict) or
                    set(value) != {"id", "token"} or not isinstance(value["id"], str) or
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["id"]) or not isinstance(value["token"], str) or
                    len(value["token"]) < 16 for alias, value in bindings.items()):
                raise RuntimeFailure("invalid_platform_connection_bindings")
            tests[plugin["id"]] = {"entry": entry, "options": plugin["options"], "platform_connections": bindings}
            loader = stage / "agent/loaders" / (plugin["id"] + ".mjs")
            loader.write_text(
                "import plugin from " + json.dumps("../" + relative.as_posix() + "/entry.mjs") + ";\n"
                "import { createPlatform } from '../platform-client.mjs';\n"
                "const options = " + json.dumps(plugin["options"], ensure_ascii=False) + ";\n"
                "const platform = createPlatform(" + json.dumps(bindings) + ");\n"
                "export default async (context) => plugin(context, options, platform);\n", encoding="utf-8")
            if plugin["id"] in seven_ids | provider_ids:
                # Only Gateway holds the service connection bindings. Model-facing
                # tools delegate through the account/Run checked facts endpoint.
                loader.write_text(
                    "import plugin from " + json.dumps("../" + relative.as_posix() + "/entry.mjs") + ";\n"
                    "import { remoteTool } from '../facts-client.mjs';\n"
                    "export default async (context) => { const loaded = await plugin(context, {}, undefined); return {...loaded, tool:Object.fromEntries(Object.entries(loaded.tool).map(([name,def])=>[name,remoteTool("
                    + json.dumps(facts_token) + ",name,def)]))}; };\n", encoding="utf-8")
            if plugin["id"] in provider_ids:
                declared=plugin.get("manifest",{}).get("tools",[])
                if len(declared)!=1:
                    raise RuntimeFailure("provider_tool_manifest_mismatch")
                only=declared[0]
                loader.write_text(
                    "import plugin from " + json.dumps("../" + relative.as_posix() + "/entry.mjs") + ";\n"
                    "import { remoteTool } from '../facts-client.mjs';\n"
                    "const expected = " + json.dumps(only) + ";\n"
                    "export default async (context) => { const loaded = await plugin(context, {}, undefined);"
                    "const names = Object.keys(loaded.tool ?? {});"
                    "if (names.length !== 1 || names[0] !== expected) throw new Error('provider_tool_manifest_mismatch');"
                    "return {...loaded,tool:{[expected]:remoteTool(" + json.dumps(facts_token)
                    + ",expected,loaded.tool[expected])}}; };\n", encoding="utf-8")
            config["plugin"].append("file:///managed/loaders/" + plugin["id"] + ".mjs")
        for skill in spec["skills"]:
            # Existing migration snapshots used 28-hex deterministic Skill IDs.
            # Preserve those immutable snapshots; runtime/user IDs remain 32 hex.
            if not isinstance(skill.get("id"), str) or not re.fullmatch(r"(?:[a-f0-9]{28}|[a-f0-9]{32})", skill["id"]):
                raise RuntimeFailure("invalid_skill_identity")
            if not all(isinstance(skill.get(key), str) for key in ("name", "description", "content")):
                raise RuntimeFailure("invalid_published_skill")
            target = stage / "agent/skills" / skill["id"] / "SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("---\nname: " + json.dumps(skill["name"], ensure_ascii=False) +
                              "\ndescription: " + json.dumps(skill["description"], ensure_ascii=False) +
                              "\n---\n" + skill["content"], encoding="utf-8")
        version = {"uid": uid, "runtime_id": runtime_id, "revision": revision}
        write_json(stage / "agent/opencode.json", config)
        write_json(stage / "agent/revision.json", version)
        write_json(stage / "gateway/revision.json", version)
        write_json(stage / "gateway/plugin-tests.json", tests)
        write_json(stage / "relay/model-relay.json", {"models": spec["models"]})
        write_json(stage / "relay/connections.json", {"account_id": uid, "connections": spec.get("connections", [])})
        write_json(stage / "relay/revision.json", version)
        write_secret(stage / "private/gateway-token", spec["private"]["gateway_key"])
        write_secret(stage / "private/opencode-password", spec["private"]["agent_password"])
        if "runtime_key" in spec["private"]:
            write_secret(stage / "private/runtime-key", spec["private"]["runtime_key"])
            write_secret(stage / "private/relay-management-key", spec["private"]["relay_management_key"])
        write_json(stage / "publication.json", {"digest": digest, "uid": uid, "revision": revision})
        # Compose paths point at the final immutable location, never the staging name.
        write_json(stage / "compose.json", compose_spec(spec, release, agent_image=self.agent_image,
                   gateway_image=self.gateway_image, limits=getattr(self, "limits", None),
                   deployment_id=getattr(self, "deployment_id", None),
                   control_container=getattr(self, "control_container", "peixian-console"),
                   orchestration=getattr(self, "orchestration", None)))
        grant_container_read(stage)
        os.rename(stage, release)
        return release

    def ensure_volumes(self, spec, compose):
        project = "px-" + spec["runtime_id"]
        for definition in compose["volumes"].values():
            name = definition["name"]
            if definition.get("external"):
                self.docker_run("volume", "inspect", name)
                consumers = self.docker_run("ps", "--filter", "volume=" + name, "--format", "{{.ID}}").split()
                if consumers:
                    records = json.loads(self.docker_run("inspect", *consumers))
                    if any(item["Config"]["Labels"].get("com.docker.compose.project") != project for item in records):
                        raise RuntimeFailure("legacy_volume_still_in_use")
                continue
            found = self.docker_run("volume", "ls", "--filter", "name=^" + re.escape(name) + "$", "--format", "{{.Name}}").split()
            if found:
                record = json.loads(self.docker_run("volume", "inspect", name))[0]
                if (record.get("Labels") or {}).get("peixian.runtime_id") != spec["runtime_id"]:
                    raise RuntimeFailure("volume_owner_mismatch")
            else:
                labels = ["--label", MANAGED + "=true", "--label", "peixian.runtime_id=" + spec["runtime_id"],
                          "--label", "peixian.uid=" + spec["uid"]]
                if getattr(self, "deployment_id", None):
                    labels.extend(["--label", "peixian.deployment=" + self.deployment_id])
                self.docker_run("volume", "create", *labels, name)
            # Recover an interrupted initialization only when the owned volume is still empty.
            # Imported volumes took the branch above and can never reach this operation.
            self.docker_run("run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                            "--security-opt", "no-new-privileges:true", "--memory", "64m", "--cpus", "0.5", "--pids-limit", "32",
                            "--cap-drop", "ALL", "--cap-add", "CHOWN", "--user", "0:0",
                            "--mount", "type=volume,source=" + name + ",target=/volume",
                            "--entrypoint", "python3", self.agent_image, "-c",
                            "import os,sys;s=os.stat('/volume');"
                            "sys.exit(0) if (s.st_uid,s.st_gid)==(10001,10001) else None;"
                            "assert s.st_uid==0 and not os.listdir('/volume');"
                            "os.chmod('/volume',0o700);os.chown('/volume',10001,10001)", timeout=30)

    def running(self, runtime_id):
        return self.docker_run("ps", "--filter", "label=com.docker.compose.project=px-" + check_id(runtime_id),
                               "--format", "{{.ID}}").split()

    def stop_checked(self, runtime_id, file):
        self.compose(file, "stop", timeout=90)
        # Compose completion and daemon visibility can briefly differ. Require
        # observed exit, with a bounded grace period; never infer stopped from
        # the successful command alone or release capacity on timeout.
        deadline = time.monotonic() + 5
        while self.running(runtime_id):
            if time.monotonic() >= deadline:
                raise RuntimeFailure("runtime_stop_unconfirmed")
            time.sleep(0.2)

    def check_images(self):
        # Fail locally when images are absent; never pull at account creation.
        for image in (self.agent_image, self.gateway_image):
            result = json.loads(self.docker_run("image", "inspect", image))[0]
            if result.get("Os") != "linux" or result.get("Architecture") != "amd64":
                raise RuntimeFailure("runtime_image_platform_mismatch")

    def apply(self, job, spec, download, heartbeat):
        runtime_id, uid = check_id(spec["runtime_id"]), check_id(spec["uid"])
        if job["uid"] != uid or job["revision"] != spec["revision"] or job["action"] not in {"provision", "apply", "pause", "resume"}:
            raise RuntimeFailure("job_spec_mismatch")
        managed = "runtime_key" in spec.get("private", {})
        if managed and (job.get("phase") != "applying" or job.get("mutation_authorized") is not True):
            raise RuntimeFailure("runtime_mutation_requires_applying_receipt")
        if managed:
            heartbeat()
            self.mutation_record(job, "running")
        previous = self.state(runtime_id)
        if previous and previous["uid"] != uid:
            raise RuntimeFailure("runtime_owner_mismatch")
        running = self.running(runtime_id)
        old_file = inside(self.directory(runtime_id), Path(previous["compose"])) if previous else None
        pending_file = self.directory(runtime_id) / "pending.json"
        if running and not previous:
            # Resume only a deployment this worker journaled before Compose started.
            pending = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.is_file() else {}
            if pending.get("uid") != uid or pending.get("runtime_id") != runtime_id:
                raise RuntimeFailure("runtime_state_missing")
            old_file = inside(self.directory(runtime_id), Path(pending["compose"]))
            previous = {**pending, "paused": True}
        if previous and not previous.get("paused") and running and not managed:
            self.attach_control(runtime_id)
            self.wait_idle(spec, heartbeat)
        if job["action"] == "pause":
            if previous:
                self.stop_checked(runtime_id, old_file)
                write_json(self.directory(runtime_id) / "state.json", {**previous, "paused": True})
            if managed:
                self.mutation_record(job, "idle")
            return {"ok": True, "cleanup_confirmed": True}
        file = None
        attempted = False
        try:
            self.capacity(runtime_id)
            self.check_images()
            release = self.prepare(spec, download)
            file = release / "compose.json"
            config = json.loads(file.read_text(encoding="utf-8"))
            self.ensure_volumes(spec, config)
            self.ensure_networks(spec)
            heartbeat()
            write_json(pending_file, {
                "uid": uid, "runtime_id": runtime_id, "revision": spec["revision"], "compose": str(file),
            })
            attempted = True
            self.compose(file, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180", timeout=240)
            self.verify(spec, spec["revision"])
            write_json(self.directory(runtime_id) / "state.json", {
                "uid": uid, "runtime_id": runtime_id, "revision": spec["revision"], "compose": str(file), "paused": False,
            })
            if managed:
                self.mutation_record(job, "idle")
            return {"ok": True}
        except Exception as error:
            code = error.code if isinstance(error, RuntimeFailure) else "release_failed"
            if managed and code in {"worker_heartbeat_failed", "worker_lease_lost", "control_api_unavailable", "host_command_unavailable"}:
                self.mutation_record(job, "unknown")
                raise RuntimeFailure(code) from None
            if previous and not previous.get("paused"):
                try:
                    if attempted:
                        self.compose(old_file, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180", timeout=240)
                    self.verify(spec, previous["revision"])
                except (RuntimeFailure, ValueError):
                    pass
                else:
                    if managed:
                        self.mutation_record(job, "idle")
                    raise RuntimeFailure("release_failed_rolled_back", rolled_back=True) from None
            try:
                current = self.running(runtime_id)
                if current:
                    stop_file = file if attempted else old_file
                    if stop_file is None:
                        raise RuntimeFailure("runtime_stop_unconfirmed")
                    self.stop_checked(runtime_id, stop_file)
            except (RuntimeFailure, ValueError):
                raise RuntimeFailure("release_failed_cleanup_unconfirmed") from None
            # Only this branch has confirmed every project container is stopped.
            if managed:
                self.mutation_record(job, "idle")
            raise RuntimeFailure(code, cleanup_confirmed=True) from None
