#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Full Company Identity Resolver Actor.
# Creates an isolated virtualenv and installs the pinned Python dependencies.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The default base image ships Python 3.12 but may not include the venv module.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

# `python3 -m venv` is safe to re-run against an existing environment.
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# Fail fast if the Actor source does not compile.
./.venv/bin/python -m compileall -q my_actor

echo "Environment ready. Activate with: source .venv/bin/activate"
