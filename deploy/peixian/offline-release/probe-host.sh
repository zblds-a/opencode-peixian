#!/bin/sh
# Read-only host inventory for the Peixian offline amd64 release.
set -u
fail=0
warn=0
emit() { printf '%s=%s\n' "$1" "$2"; }
bad() { emit "fail.$1" "$2"; fail=$((fail + 1)); }
caution() { emit "warn.$1" "$2"; warn=$((warn + 1)); }
value() { command -v "$1" >/dev/null 2>&1 && command -v "$1" || printf 'missing'; }
osfield() { sed -n "s/^$1=//p" /etc/os-release 2>/dev/null | head -n 1 | tr -d '"'; }

emit probe_version 1
emit timestamp_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
emit os_id "$(osfield ID)"
emit os_like "$(osfield ID_LIKE)"
emit os_version "$(osfield VERSION_ID)"
emit os_pretty "$(osfield PRETTY_NAME)"
emit architecture "$(uname -m)"
emit kernel "$(uname -r)"
emit libc "$(ldd --version 2>&1 | head -n 1)"
emit pid1 "$(cat /proc/1/comm 2>/dev/null || printf unknown)"
emit cpu_count "$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf unknown)"
emit memory_kib "$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)"
emit root_free_kib "$(df -Pk / 2>/dev/null | awk 'NR==2{print $4}')"
emit cgroup_mode "$(test -f /sys/fs/cgroup/cgroup.controllers && printf v2 || printf v1)"
emit selinux "$(command -v getenforce >/dev/null 2>&1 && getenforce || printf unavailable)"
emit time_sync "$(command -v timedatectl >/dev/null 2>&1 && timedatectl show -p NTPSynchronized --value 2>/dev/null || printf unknown)"
emit route_ipv4 "$(command -v ip >/dev/null 2>&1 && ip -4 route show 2>/dev/null | tr '\n' ';' || printf unavailable)"
emit docker_path "$(value docker)"
emit python_path "$(value python3)"
emit systemctl_path "$(value systemctl)"
emit setfacl_path "$(value setfacl)"
emit curl_path "$(value curl)"
emit sha256sum_path "$(value sha256sum)"
emit tar_path "$(value tar)"

if [ "$(uname -m)" != x86_64 ]; then bad architecture "amd64 image required"; fi
if [ "$(cat /proc/1/comm 2>/dev/null)" != systemd ]; then bad systemd "PID 1 must be systemd"; fi
if ! command -v setfacl >/dev/null 2>&1; then bad acl "install acl package"; fi
if ! command -v sha256sum >/dev/null 2>&1; then bad sha256sum "required for offline integrity check"; fi
if ! command -v tar >/dev/null 2>&1; then bad tar "required for package extraction"; fi
if command -v python3 >/dev/null 2>&1; then
  emit python_version "$(python3 --version 2>&1)"
  if ! python3 -c 'import sys; assert sys.version_info >= (3, 11); import venv' >/dev/null 2>&1; then bad python "Python 3.11+ with venv required"; fi
else
  bad python "Python 3.11+ required"
fi
if command -v docker >/dev/null 2>&1; then
  emit docker_client "$(docker version --format '{{.Client.Version}}' 2>/dev/null || printf unavailable)"
  emit docker_server "$(docker version --format '{{.Server.Version}}' 2>/dev/null || printf unavailable)"
  emit docker_architecture "$(docker info --format '{{.Architecture}}' 2>/dev/null || printf unavailable)"
  emit docker_root "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || printf unavailable)"
  emit docker_storage "$(docker info --format '{{.Driver}}' 2>/dev/null || printf unavailable)"
  emit docker_cgroup "$(docker info --format '{{.CgroupVersion}}' 2>/dev/null || printf unavailable)"
  emit compose_version "$(docker compose version --short 2>/dev/null || printf unavailable)"
  if ! docker info >/dev/null 2>&1; then bad docker "local Docker daemon unavailable"; fi
  if ! docker compose version >/dev/null 2>&1; then bad compose "Docker Compose v2 required"; fi
  if [ "$(docker info --format '{{.Architecture}}' 2>/dev/null)" != x86_64 ]; then bad docker_architecture "Docker daemon must be amd64"; fi
  docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || printf /var/lib/docker)
  emit docker_free_kib "$(df -Pk "$docker_root" 2>/dev/null | awk 'NR==2{print $4}')"
  emit docker_network_subnets "$(docker network ls -q 2>/dev/null | xargs -r docker network inspect --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null | tr '\n' ';')"
else
  bad docker "Docker Engine and Compose v2 required"
fi
if command -v ss >/dev/null 2>&1; then
  emit candidate_ports "$(ss -H -lnt 2>/dev/null | awk '$4 ~ /:(19460|14099)$/ {print $4}' | tr '\n' ';')"
else
  caution ports "ss unavailable; manually inspect configured ports"
fi
if [ "$(getenforce 2>/dev/null || printf disabled)" = Enforcing ]; then
  caution selinux "enforcing; validate volume labels and ACLs during installation"
fi
emit failures "$fail"
emit warnings "$warn"
[ "$fail" -eq 0 ]
