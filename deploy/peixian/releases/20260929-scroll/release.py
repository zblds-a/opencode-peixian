"""Switch only Console after current-image checks; restore on failure."""

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import time


parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True, help="Current production Console image ID")
parser.add_argument("--candidate", required=True, help="Verified frontend candidate image ID")
parser.add_argument("--tag", required=True, help="New production frontend tag")
parser.add_argument("--index-sha256", required=True)
args = parser.parse_args()

root = pathlib.Path("/srv/peixian-alignment-20260917")
platform_path = root / "platform.json"
compose_path = root / "runtime/generated/compose.server.json"
console = "peixian-alignment-20260917-console"
https = "peixian-alignment-20260917-https"


def inspect(name, template):
    return subprocess.check_output(["docker", "inspect", name, "--format", template], text=True).strip()


def health():
    return {
        "image": inspect(console, "{{.Image}}"),
        "console": inspect(console, "{{.State.Health.Status}}"),
        "https": inspect(https, "{{.State.Health.Status}}"),
    }


def atomic_write(path, data):
    temp = path.with_name(path.name + ".ui-scroll.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def start(expected):
    subprocess.run(["docker", "compose", "-f", str(compose_path), "up", "-d", "--no-deps", "--no-build", "console"], check=True)
    for _ in range(60):
        if health() == {"image": expected, "console": "healthy", "https": "healthy"}:
            return
        time.sleep(5)
    raise RuntimeError(f"Console or HTTPS failed to become healthy: {health()}")


# The operator explicitly approved this frontend-only release while backend tasks are active.
# Image identity and health still guard against replacing a newer backend image.
assert health() == {"image": args.base, "console": "healthy", "https": "healthy"}
assert inspect(args.candidate, "{{.Id}}") == args.candidate
assert subprocess.run(["systemctl", "is-active", "--quiet", "peixian-alignment-worker.service"]).returncode == 0

platform_original = platform_path.read_bytes()
compose_original = compose_path.read_bytes()
platform = json.loads(platform_original)
compose = json.loads(compose_original)
old_tag = platform["images"]["control"]
assert compose["services"]["console"]["image"] == args.base
assert inspect(old_tag, "{{.Id}}") == args.base
stamp = time.strftime("%Y%m%d-%H%M%S")
platform_backup = root / f"platform.before-ui-scroll-{stamp}.json"
compose_backup = compose_path.with_name(f"compose.server.before-ui-scroll-{stamp}.json")
assert not platform_backup.exists() and not compose_backup.exists()
platform_backup.write_bytes(platform_original)
compose_backup.write_bytes(compose_original)
subprocess.run(["docker", "tag", args.candidate, args.tag], check=True)
assert inspect(args.tag, "{{.Id}}") == args.candidate
platform["images"]["control"] = args.tag
compose["services"]["console"]["image"] = args.candidate

try:
    atomic_write(platform_path, (json.dumps(platform, ensure_ascii=False, indent=2) + "\n").encode())
    atomic_write(compose_path, (json.dumps(compose, ensure_ascii=False, indent=2) + "\n").encode())
    start(args.candidate)
    response = subprocess.check_output(["curl", "--insecure", "--fail", "--silent", "--show-error", "https://127.0.0.1:19460/"])
    assert hashlib.sha256(response).hexdigest() == args.index_sha256, "served index differs from candidate"
except Exception:
    atomic_write(platform_path, platform_original)
    atomic_write(compose_path, compose_original)
    start(args.base)
    raise

print(json.dumps({
    "status": "PRODUCTION_DEPLOYED", "old_tag": old_tag, "old_image": args.base,
    "tag": args.tag, "image": args.candidate, "index_sha256": args.index_sha256,
    "platform_backup": str(platform_backup), "compose_backup": str(compose_backup), "health": health(),
}))
