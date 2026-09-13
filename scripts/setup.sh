#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'

(
  cd frontend
  npm ci
  npm run build
)

.venv/bin/frontier-daily init
.venv/bin/python -m compileall -q src
.venv/bin/pytest

echo "安装准备完成。下一步运行：scripts/briefingctl install"
