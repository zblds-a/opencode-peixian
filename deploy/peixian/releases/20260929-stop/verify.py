"""Verify the candidate changed only frontend static files."""

import hashlib
import json
import subprocess


BASE = "sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91"
CANDIDATE = "peixian-control:ui-stop-20260929-candidate"
EXPECTED_INDEX = "3f1d859910073b78b580db0541a407a7e0f35bd8562ec9ff96069e5f0227b760"
SCRIPT = """
import hashlib, json, pathlib
roots = [pathlib.Path('/candidate/control'), pathlib.Path('/candidate/shared')]
files = sorted((str(path), hashlib.sha256(path.read_bytes()).hexdigest())
               for root in roots for path in root.rglob('*') if path.is_file())
print(json.dumps(files, separators=(',', ':')))
"""


def files(image):
    output = subprocess.check_output(
        ["docker", "run", "--rm", "--entrypoint", "python3", image, "-c", SCRIPT], text=True
    )
    return json.loads(output)


base = files(BASE)
candidate = files(CANDIDATE)
assert base and base == candidate, "backend files differ between base and candidate"
index = subprocess.check_output(
    ["docker", "run", "--rm", "--entrypoint", "python3", CANDIDATE, "-c",
     "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('/candidate/static/index.html').read_bytes()).hexdigest())"],
    text=True,
).strip()
assert index == EXPECTED_INDEX, "candidate static index differs from local build"
print(json.dumps({"backend_file_count": len(base), "backend_tree_sha256": hashlib.sha256(json.dumps(base).encode()).hexdigest(), "index_sha256": index}))
