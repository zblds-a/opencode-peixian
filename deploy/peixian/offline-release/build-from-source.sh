#!/bin/sh
# Optional offline Control/Gateway rebuild on an amd64 Docker host.
set -eu
bundle=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work=${1:-"$bundle/rebuild-work"}
if [ -e "$work" ]; then echo "Build directory already exists: $work" >&2; exit 1; fi
(cd "$bundle" && sha256sum -c SHA256SUMS)
for archive in "$bundle"/images/*.tar; do docker load -i "$archive"; done
for tag in peixian-build-python:20260928 peixian-build-node:20260928 peixian-agent:euler-20260928; do
  expected=$(awk -v tag="$tag" '$1 == tag {print $2}' "$bundle/images.ids")
  actual=$(docker image inspect "$tag" --format '{{.Id}}')
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo "Build base mismatch: $tag" >&2
    exit 1
  fi
done
mkdir -p "$work/source"
tar -xzf "$bundle/source.tar.gz" -C "$work/source"
tar -xzf "$bundle/frontend-node_modules.tar.gz" -C "$work/source"
mkdir -p "$work/source/deploy/peixian/offline-release/wheels-control"
cp -a "$bundle/wheels-control/." "$work/source/deploy/peixian/offline-release/wheels-control/"
docker run --rm --network none -v "$work/source:/repo" -w /repo/packages/peixian-console \
  peixian-build-node:20260928 sh -lc 'npm run typecheck && npm run build'
revision=$(cat "$bundle/source-commit.txt")
docker build --network none --pull=false -f "$work/source/deploy/peixian/offline-release/Control.Dockerfile" \
  --build-arg "SOURCE_REVISION=$revision" -t peixian-control:euler-20260928 "$work/source"
docker build --network none --pull=false -f "$work/source/deploy/peixian/offline-release/Gateway.Dockerfile" \
  --build-arg "SOURCE_REVISION=$revision" -t peixian-gateway:euler-20260928 "$work/source"
echo 'Offline rebuild finished. Compare behavior and static asset hashes before deployment.'
