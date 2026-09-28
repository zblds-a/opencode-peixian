#!/bin/sh
# Fresh, offline, single-host installation. Run as root after editing platform.json.
set -eu
umask 077
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
config_input=${1:-}
install_root=/opt/peixian-private/20260928
config_target=/etc/peixian-private/platform.json
service_target=/etc/systemd/system/peixian-private-worker.service

if [ "$(id -u)" -ne 0 ]; then echo 'Run as root.' >&2; exit 1; fi
if [ -z "$config_input" ] || [ ! -f "$config_input" ]; then
  echo "Usage: $0 /absolute/path/to/platform.json" >&2
  exit 1
fi
if [ -e "$service_target" ] || [ -e "$config_target" ]; then
  echo 'Existing installation detected; this installer is for a fresh host only.' >&2
  exit 1
fi
config_input=$(realpath "$config_input")
if grep -q 'REPLACE_' "$config_input"; then
  echo 'Fill every REPLACE_ value in platform.json before installation.' >&2
  exit 1
fi

echo '[1/8] Read-only host probe'
sh "$bundle/probe-host.sh"
echo '[2/8] Package checksums'
(cd "$bundle" && sha256sum -c SHA256SUMS)
echo '[3/8] Load pinned offline images'
for archive in "$bundle"/images/*.tar; do docker load -i "$archive"; done
while read -r tag expected; do
  [ -n "$tag" ] || continue
  actual=$(docker image inspect "$tag" --format '{{.Id}}')
  if [ "$actual" != "$expected" ]; then
    echo "Image ID mismatch: $tag" >&2
    exit 1
  fi
done < "$bundle/images.ids"

python3 - "$config_input" <<'PY'
import json, sys
config = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {
    "control": "peixian-control:euler-20260928",
    "gateway": "peixian-gateway:euler-20260928",
    "agent": "peixian-agent:euler-20260928",
    "proxy": "peixian-proxy:euler-20260928",
}
if config.get("images") != expected:
    raise SystemExit("platform.json images must match the verified offline release")
if "REPLACE_" in config.get("public_url", ""):
    raise SystemExit("set the private-network public_url")
PY

echo '[4/8] Install pinned source and offline worker dependencies'
install -d -m 0755 "$install_root/source"
tar -xzf "$bundle/source.tar.gz" -C "$install_root/source"
python3 -m venv "$install_root/venv"
"$install_root/venv/bin/python" -m pip install --no-index --find-links="$bundle/wheels-worker" \
  -r "$install_root/source/deploy/peixian/requirements.txt"
install -d -m 0700 /etc/peixian-private
install -m 0600 "$config_input" "$config_target"

echo '[5/8] Initialize private credentials'
"$install_root/venv/bin/python" "$install_root/source/deploy/peixian/platform-manage.py" init --config "$config_target"
echo '[6/8] Validate host capacity, TLS, ports, network and image labels'
"$install_root/venv/bin/python" "$install_root/source/deploy/peixian/platform-manage.py" check --config "$config_target"
echo '[7/8] Start platform'
"$install_root/venv/bin/python" "$install_root/source/deploy/peixian/platform-manage.py" up --config "$config_target"
install -m 0644 "$bundle/peixian-private-worker.service" "$service_target"
systemctl daemon-reload
systemctl enable --now peixian-private-worker.service

echo '[8/8] Local health check'
python3 - "$config_target" <<'PY'
import json, sys, time, urllib.request
config = json.load(open(sys.argv[1], encoding="utf-8"))
url = f"http://127.0.0.1:{config['control_port']}/health"
for attempt in range(30):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                print(f"healthy: {config['public_url']}")
                break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit(f"health check failed: {url}")
PY
systemctl is-active --quiet peixian-private-worker.service
echo 'Private platform installed. Configure model and business data connections in the administrator UI.'
