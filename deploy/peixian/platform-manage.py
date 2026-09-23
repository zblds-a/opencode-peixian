"""Cross-platform single-server lifecycle. Secrets and existing data are never overwritten."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


config = module("platform-config")


class PlatformError(RuntimeError):
    pass


def command(*args, timeout=180):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise PlatformError("host_command_unavailable") from None
    if result.returncode:
        raise PlatformError("host_command_failed")
    return result.stdout.strip()


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise PlatformError("private_path_is_link")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as out:
        out.write(data)


def initialize(cfg):
    module("console-runtime").protect_root(cfg.root)
    for folder in (cfg.root, cfg.secrets, cfg.worker_root, cfg.root / "generated"):
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(folder, 0o700)
    values = {"console-control.key": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
              "console-worker.key": lambda: secrets.token_urlsafe(48),
              "console-admin.password": lambda: secrets.token_urlsafe(24)}
    for name, generate in values.items():
        target = cfg.secrets / name
        if target.is_symlink():
            raise PlatformError("credential_path_is_link")
        if target.exists():
            if not target.is_file() or len(target.read_text().strip()) < 24:
                raise PlatformError("existing_credential_invalid_preserved")
            continue
        private_write(target, generate() + "\n")
    if os.name == "posix":
        if not shutil.which("setfacl"):
            raise PlatformError("linux_acl_required_install_acl_package")
        command("setfacl", "-m", "u:10001:x", str(cfg.root))
        command("setfacl", "-m", "u:10001:rx", str(cfg.secrets))
        for path in cfg.secrets.iterdir():
            if path.is_file():
                command("setfacl", "-m", "u:10001:r", str(path))
        for path in (cfg.certificate, cfg.private_key):
            if path.is_file():
                command("setfacl", "-m", "u:10001:r", str(path))
        command("setfacl", "-m", "u:10001:rx", str(cfg.root / "generated"))
    return {"status": "initialized", "administrator": "admin", "password_file": str(cfg.secrets / "console-admin.password")}


def compose_config(cfg, pinned=None):
    images = pinned or cfg.images
    bind = lambda source, target: {"type": "bind", "source": str(source), "target": target, "read_only": True,
                                  "bind": {"create_host_path": False}}
    common = {"platform": "linux/amd64", "init": True, "read_only": True, "restart": "unless-stopped",
              "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"], "user": "10001:10001",
              "labels": {"peixian.deployment": cfg.deployment_id},
              "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}}
    console = {**common, "container_name": cfg.control_container, "image": images["control"],
               "stop_grace_period": str(10 + 4 * cfg.concurrency.get("hub_shutdown_seconds", 5)) + "s",
               "cpus": cfg.control_resources["cpus"], "mem_limit": str(cfg.control_resources["memory_mib"]) + "m", "pids_limit": 128,
               "tmpfs": ["/tmp:rw,nosuid,nodev,size=128m,mode=1777"],
               "ports": [{"target": 8080, "published": str(cfg.control_port), "host_ip": "127.0.0.1", "protocol": "tcp"}],
               "environment": {"CONTROL_DATA": "/data", "CONTROL_KEY_FILE": "/run/secrets/control-key",
                               "WORKER_KEY_FILE": "/run/secrets/worker-key", "ADMIN_PASSWORD_FILE": "/run/secrets/admin-password",
                               "CONSOLE_ORIGINS": cfg.public_url, "COOKIE_SECURE": "true", "MAX_RUNTIMES": str(cfg.max_runtimes),
                               "PLATFORM_NAME": cfg.product["name"], "PLATFORM_SHORT_NAME": cfg.product["short_name"],
                               "PLATFORM_DESCRIPTION": cfg.product["description"]},
               "volumes": [{"type": "volume", "source": "control-data", "target": "/data"},
                           bind(cfg.secrets / "console-control.key", "/run/secrets/control-key"),
                           bind(cfg.secrets / "console-worker.key", "/run/secrets/worker-key"),
                           bind(cfg.secrets / "console-admin.password", "/run/secrets/admin-password")],
               "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)"],
                               "interval": "10s", "timeout": "5s", "start_period": "20s", "retries": 6},
               "networks": ["front"]}
    if cfg.version >= 2:
        console["memswap_limit"] = console["mem_limit"]
        console["environment"].update(cfg.concurrency_environment)
    if cfg.version >= 3:
        console["environment"].update(cfg.orchestration_environment)
    if cfg.version == 4:
        console["environment"]["PX_RUNTIME_MODE"] = cfg.runtime_pool["runtime_mode"]
        console["environment"]["PX_RUNTIME_POOL_CONFIG"] = json.dumps(cfg.runtime_pool, separators=(',', ':'))
    for name, env in {"task_spec_v1":"PX_TASKSPEC_V1_UIDS", "multi_agent_v1":"PX_MULTI_AGENT_V1_UIDS", "trusted_result_v2":"PX_TRUSTED_RESULT_V2_UIDS", "theft_provider_v1":"PX_THEFT_PROVIDER_UIDS", "theft_planner_v1":"PX_THEFT_PLANNER_UIDS", "theft_native":"PX_THEFT_NATIVE_UIDS"}.items():
        console["environment"][env] = ",".join(cfg.feature_scopes.get(name, []))
    provider_file = cfg.secrets / 'console-provider.json'
    if provider_file.is_file():
        if provider_file.is_symlink():
            raise PlatformError('provider_config_is_link')
        console['volumes'].append(bind(provider_file, '/run/secrets/provider-config'))
        console['environment']['PX_THEFT_REAL_CONFIG_FILE'] = '/run/secrets/provider-config'
    # This applies to v1 upgrades too: browser users must not share the proxy IP
    # in source-based login limits. No account management network is trusted.
    console["environment"]["FORWARDED_ALLOW_IPS"] = str(next(ipaddress.ip_network(cfg.network_pool).subnets(new_prefix=28)))
    proxy = {**common, "container_name": cfg.deployment_id + "-https", "image": images["proxy"],
             "cpus": 0.5, "mem_limit": "128m", "pids_limit": 64,
             "entrypoint": ["nginx", "-g", "daemon off;"],
             "tmpfs": ["/tmp:rw,nosuid,nodev,size=32m,mode=1777"],
             "ports": [{"target": 8443, "published": str(cfg.https_port), "host_ip": cfg.bind_host, "protocol": "tcp"}],
             "volumes": [bind(cfg.root / "generated/nginx.conf", "/etc/nginx/nginx.conf"),
                         bind(cfg.certificate, "/run/tls/certificate.pem"), bind(cfg.private_key, "/run/tls/private-key.pem")],
             "depends_on": {"console": {"condition": "service_healthy"}}, "networks": ["front"],
             "healthcheck": {"test": ["CMD", "wget", "--no-check-certificate", "-q", "-O", "/dev/null", "https://127.0.0.1:8443/health"],
                             "interval": "10s", "timeout": "5s", "retries": 6}}
    if cfg.version >= 2:
        proxy["memswap_limit"] = proxy["mem_limit"]
    proxy_fingerprint = hashlib.sha256((ROOT / "server/nginx.conf").read_bytes())
    if cfg.certificate.is_file():
        proxy_fingerprint.update(cfg.certificate.read_bytes())
    proxy["labels"] = {**common["labels"], "peixian.proxy_config": proxy_fingerprint.hexdigest()}
    # Explicit IPAM keeps this entry network out of Docker's exhaustible default pools.
    subnet = next(ipaddress.ip_network(cfg.network_pool).subnets(new_prefix=28))
    return {"name": cfg.deployment_id, "services": {"console": console, "https": proxy},
            "volumes": {"control-data": {"name": cfg.control_volume, "labels": {"peixian.deployment": cfg.deployment_id}}},
            "networks": {"front": {"name": cfg.deployment_id + "-front", "labels": {"peixian.deployment": cfg.deployment_id},
                                    "ipam": {"config": [{"subnet": str(subnet)}]}}}}


def render(cfg, pinned=None):
    folder = cfg.root / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    for path in (folder, cfg.compose_path, folder / "nginx.conf"):
        if path.is_symlink():
            raise PlatformError("generated_path_is_link")
    cfg.compose_path.write_text(json.dumps(compose_config(cfg, pinned), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "server/nginx.conf", folder / "nginx.conf")
    return {"status": "rendered", "compose": str(cfg.compose_path)}


def inspect_images(cfg):
    result = {}
    for name, image in cfg.images.items():
        info = json.loads(command("docker", "image", "inspect", image))[0]
        if info.get("Os") != "linux" or info.get("Architecture") != "amd64":
            raise PlatformError("linux_amd64_image_required")
        if name == "control":
            try:
                cfg.verify_control_image(info.get("Config", {}).get("Labels"))
            except config.ConfigError as error:
                raise PlatformError(str(error)) from None
        try:
            config.image_supports_orchestration(info.get("Config", {}).get("Labels"), name, cfg.version)
            if cfg.runtime_pool.get('idle_pause_enabled') and name in ('gateway','agent') and 'idle_activity_v1' not in (info.get('Config',{}).get('Labels') or {}).get('org.peixian.runtime.capabilities','').split(','):
                raise config.ConfigError('runtime_image_idle_activity_incompatible')
        except config.ConfigError as error:
            raise PlatformError(str(error)) from None
        result[name] = info["Id"]
    return result


def check(cfg):
    info = json.loads(command("docker", "info", "--format", "{{json .}}"))
    if info.get("OSType") != "linux":
        raise PlatformError("docker_linux_engine_required")
    capacity = config.capacity.evaluate(info, cfg.resource_budget)
    if capacity["failures"]:
        raise PlatformError(capacity["failures"][0])
    command("docker", "compose", "version")
    endpoint = json.loads(command("docker", "context", "inspect"))[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith(("unix://", "npipe://")):
        raise PlatformError("local_docker_engine_required")
    for name in ("console-control.key", "console-worker.key", "console-admin.password"):
        path = cfg.secrets / name
        if path.is_symlink() or not path.is_file() or len(path.read_text().strip()) < 24:
            raise PlatformError("initialize_credentials_before_start")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cfg.certificate), str(cfg.private_key))
    except (OSError, ssl.SSLError):
        raise PlatformError("certificate_or_matching_private_key_invalid") from None
    for port, container in ((cfg.control_port, cfg.control_container), (cfg.https_port, cfg.deployment_id + "-https")):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                names = command("docker", "ps", "--format", "{{.Names}}").splitlines()
                if container not in names:
                    raise PlatformError("server_port_occupied")
    images = inspect_images(cfg)
    subnet = next(ipaddress.ip_network(cfg.network_pool).subnets(new_prefix=28))
    identifiers = command("docker", "network", "ls", "--format", "{{.ID}}").splitlines()
    networks = json.loads(command("docker", "network", "inspect", *identifiers)) if identifiers else []
    for item in networks:
        if item.get("Name") == cfg.deployment_id + "-front":
            if (item.get("Labels") or {}).get("peixian.deployment") != cfg.deployment_id:
                raise PlatformError("entry_network_owner_mismatch")
            continue
        for ipam in (item.get("IPAM") or {}).get("Config") or []:
            if ipam.get("Subnet"):
                other = ipaddress.ip_network(ipam["Subnet"], strict=False)
                if other.version == 4 and subnet.overlaps(other):
                    raise PlatformError("entry_subnet_conflicts_choose_unused_network_pool")
    network = None
    if cfg.version >= 2:
        try:
            network = config.capacity.network_capacity(cfg.network_pool, networks, cfg.deployment_id,
                                                       cfg.max_runtimes, config.capacity.retained_ids(cfg.worker_root))
        except ValueError as error:
            raise PlatformError(str(error)) from None
        if network["status"] != "passed":
            raise PlatformError("configured_network_pool_capacity_insufficient")
    return {"status": "passed", "deployment_id": cfg.deployment_id, "images": images,
            "memory_budget_mib": cfg.memory_budget_mib, "cpu_budget": cfg.cpu_budget,
            "capacity_policy": capacity, "network_capacity": network}


def up(cfg):
    checked = check(cfg)
    render(cfg, checked["images"])
    guard = module("console-guard")
    # The reader and candidate are the inspected immutable control image.
    guard.READER = checked["images"]["control"]
    verified = guard.check(cfg.compose_path, cfg.root / "upgrade-backups")
    if verified["image_id"] != checked["images"]["control"]:
        raise PlatformError("control_image_changed_during_check")
    command("docker", "compose", "-f", str(cfg.compose_path), "up", "-d", "--no-build", "--pull", "never", "--wait", timeout=240)
    restored = restore_control_networks(cfg)
    return {"status": "started", "url": cfg.public_url, "images": checked["images"],
            "runtime_management": restored}


def restore_control_networks(cfg):
    """Restore dynamic management attachments lost when Compose replaces Control.

    This is deployment maintenance, after image/schema checks and replacement.
    It neither changes a runtime release nor opens its lifecycle gate.
    """
    runtime = module("console-runtime")
    registry = cfg.worker_root / "runtimes"
    if not registry.exists():
        return {"registered": 0, "connected": 0, "paused_missing": 0}
    if registry.is_symlink() or not registry.is_dir():
        raise PlatformError("runtime_management_registry_invalid")
    manager = object.__new__(runtime.RuntimeManager)
    manager.root, manager.control_container = cfg.worker_root, cfg.control_container
    manager.deployment_id = cfg.deployment_id
    def execute(*args, **kwargs):
        try:
            return command("docker", *args, timeout=kwargs.get("timeout", 30))
        except PlatformError:
            raise runtime.RuntimeFailure("runtime_management_recovery_pending") from None
    manager.docker_run = execute
    names = set(command("docker", "network", "ls", "--format", "{{.Name}}").splitlines())
    selected, paused_missing, registered = [], 0, 0
    try:
        for directory in sorted(registry.iterdir()):
            if directory.is_symlink() or not directory.is_dir() or not runtime.ID.fullmatch(directory.name):
                raise PlatformError("runtime_management_registry_invalid")
            path = directory / "state.json"
            if not path.exists():
                # An unfinished first provision has no registered release and
                # cannot be silently reported as a completed deployment repair.
                if (directory / "pending.json").exists():
                    raise PlatformError("runtime_management_recovery_pending")
                continue
            if path.is_symlink() or not path.is_file():
                raise PlatformError("runtime_management_registry_invalid")
            state = manager.state(directory.name)
            runtime.check_id(state["uid"])
            runtime.inside(directory, Path(state["compose"]))
            registered += 1
            components, complete = manager.components(state)
            if not complete or "unknown" in components.values():
                raise PlatformError("runtime_management_recovery_pending")
            network = "px-" + directory.name + "-management"
            if network not in names:
                if state.get("paused") is True and all(value == "stopped" for value in components.values()):
                    paused_missing += 1
                    continue
                raise PlatformError("runtime_management_recovery_pending")
            selected.append(state)
        for state in selected:
            manager.attach_control(state["runtime_id"], state["uid"])
    except runtime.RuntimeFailure as error:
        raise PlatformError(error.code) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise PlatformError("runtime_management_registry_invalid") from None
    return {"registered": registered, "connected": len(selected), "paused_missing": paused_missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "render", "check", "up", "stop", "status", "worker", "backup", "restore", "verify-backup", "upgrade-backup"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        cfg = config.load_config(args.config)
        if args.action in ("init", "render", "check", "up"):
            result = globals()[{"init": "initialize"}.get(args.action, args.action)](cfg)
        elif args.action in ("stop", "status"):
            if args.action == "stop":
                with module("platform-backup").worker_stopped(cfg):
                    command("docker", "compose", "-f", str(cfg.compose_path), "stop", timeout=240)
                result = {"status": "stopped"}
            else:
                output = command("docker", "compose", "-f", str(cfg.compose_path), "ps", "--all", "--format", "json")
                records = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
                result = {"status": "inspected", "services": [{key: value.get(key) for key in ("Service", "State", "Health")} for value in records]}
        elif args.action == "worker":
            sys.exit(subprocess.call([sys.executable, "-u", str(ROOT / "console-worker.py"), "--config", str(cfg.source)]))
        elif args.action == "upgrade-backup":
            guard = module("console-guard")
            guard.READER = inspect_images(cfg)["control"]
            result = guard.backup(cfg.compose_path, cfg.root / "upgrade-backups")
        else:
            backup = module("platform-backup")
            if args.action == "backup":
                result = backup.backup(cfg, args.destination)
            elif args.action == "restore":
                result = backup.restore(cfg, args.archive)
            else:
                result = backup.verify(args.archive)
        print(json.dumps(result, ensure_ascii=False))
    except (config.ConfigError, PlatformError, RuntimeError, OSError, ValueError) as error:
        code = str(error) if re_safe(str(error)) else "platform_operation_failed_existing_data_preserved"
        print(json.dumps({"status": "failed", "error": code}))
        sys.exit(1)


def re_safe(value):
    import re
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{2,100}", value))


if __name__ == "__main__":
    main()
