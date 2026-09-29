"""Switch only Console to the verified frontend image; restore configs on failure."""

import json
import os
import pathlib
import subprocess
import time


ROOT = pathlib.Path("/srv/peixian-alignment-20260917")
PLATFORM = ROOT / "platform.json"
COMPOSE = ROOT / "runtime/generated/compose.server.json"
OLD_TAG = "peixian-control:minimal-input-20260928-r12"
OLD_ID = "sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91"
NEW_TAG = "peixian-control:frontend-stop-20260929-r1"
NEW_ID = "sha256:71ac6da1a478e66de36c0ad47b5ecef9feca409f611d4fe66b976357820d7d55"
CANDIDATE = "peixian-control:ui-stop-20260929-candidate"
CONSOLE = "peixian-alignment-20260917-console"
HTTPS = "peixian-alignment-20260917-https"


def inspect(name, template):
    return subprocess.check_output(["docker", "inspect", name, "--format", template], text=True).strip()


def health():
    return {
        "image": inspect(CONSOLE, "{{.Image}}"),
        "console": inspect(CONSOLE, "{{.State.Health.Status}}"),
        "https": inspect(HTTPS, "{{.State.Health.Status}}"),
    }


def atomic_write(path, data):
    temp = path.with_name(path.name + ".ui-stop.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def start(expected):
    subprocess.run(["docker", "compose", "-f", str(COMPOSE), "up", "-d", "--no-deps", "--no-build", "console"], check=True)
    for _ in range(60):
        state = health()
        if state == {"image": expected, "console": "healthy", "https": "healthy"}:
            return
        time.sleep(5)
    raise RuntimeError(f"Console or HTTPS did not become healthy: {health()}")


subprocess.run(["python3", "/root/PeiXianDB/check-release-idle.py"], check=True)
assert health() == {"image": OLD_ID, "console": "healthy", "https": "healthy"}
assert inspect(CANDIDATE, "{{.Id}}") == NEW_ID
assert subprocess.run(["systemctl", "is-active", "--quiet", "peixian-alignment-worker.service"]).returncode == 0
platform_original, compose_original = PLATFORM.read_bytes(), COMPOSE.read_bytes()
platform = json.loads(platform_original)
compose = json.loads(compose_original)
assert platform["images"]["control"] == OLD_TAG
assert compose["services"]["console"]["image"] == OLD_ID
stamp = time.strftime("%Y%m%d-%H%M%S")
platform_backup = ROOT / f"platform.before-ui-stop-{stamp}.json"
compose_backup = COMPOSE.with_name(f"compose.server.before-ui-stop-{stamp}.json")
assert not platform_backup.exists() and not compose_backup.exists()
subprocess.run(["docker", "tag", CANDIDATE, NEW_TAG], check=True)
assert inspect(NEW_TAG, "{{.Id}}") == NEW_ID
platform_backup.write_bytes(platform_original)
compose_backup.write_bytes(compose_original)
platform["images"]["control"] = NEW_TAG
compose["services"]["console"]["image"] = NEW_ID
try:
    atomic_write(PLATFORM, (json.dumps(platform, ensure_ascii=False, indent=2) + "\n").encode())
    atomic_write(COMPOSE, (json.dumps(compose, ensure_ascii=False, indent=2) + "\n").encode())
    start(NEW_ID)
    subprocess.run(["curl", "--insecure", "--fail", "--silent", "--show-error", "--output", "/dev/null", "https://127.0.0.1:19460/"], check=True)
except Exception:
    atomic_write(PLATFORM, platform_original)
    atomic_write(COMPOSE, compose_original)
    start(OLD_ID)
    raise
print(json.dumps({"status": "PRODUCTION_DEPLOYED", "tag": NEW_TAG, "image": NEW_ID,
                  "platform_backup": str(platform_backup), "compose_backup": str(compose_backup), "health": health()}))
