"""Verify a frontend-only Console candidate against the live parent image."""

import argparse
import hashlib
import json
import subprocess


parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True)
parser.add_argument("--candidate", required=True)
parser.add_argument("--index-sha256", required=True)
args = parser.parse_args()

script = """
import hashlib, json, pathlib
roots = [pathlib.Path('/candidate/control'), pathlib.Path('/candidate/shared')]
files = sorted((str(path), hashlib.sha256(path.read_bytes()).hexdigest())
               for root in roots for path in root.rglob('*') if path.is_file())
index = pathlib.Path('/candidate/static/index.html')
print(json.dumps({'backend': files, 'index': hashlib.sha256(index.read_bytes()).hexdigest()}))
"""


def contents(image):
    return json.loads(subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python3", image, "-c", script],
        text=True,
    ))


base = contents(args.base)
candidate = contents(args.candidate)
assert base["backend"] and base["backend"] == candidate["backend"], "backend files differ"
assert candidate["index"] == args.index_sha256, "candidate index differs from local build"
print(json.dumps({
    "backend_files": len(base["backend"]),
    "backend_tree_sha256": hashlib.sha256(json.dumps(base["backend"]).encode()).hexdigest(),
    "index_sha256": candidate["index"],
}))
