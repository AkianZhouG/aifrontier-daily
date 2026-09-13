#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "人工智能前沿日报的 Python 虚拟环境不存在：$PYTHON" >&2
  echo "请运行：$ROOT/scripts/setup.sh" >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$ROOT/data"

# Bounded local logs. Per-run JSONL files are retained for 30 days; service
# logs rotate on restart once they exceed 5 MiB.
for log in "$ROOT/logs/service.log" "$ROOT/logs/service.err.log"; do
  if [ -f "$log" ] && [ "$(wc -c < "$log" | tr -d ' ')" -gt 5242880 ]; then
    rm -f "$log.3"
    [ ! -f "$log.2" ] || mv "$log.2" "$log.3"
    [ ! -f "$log.1" ] || mv "$log.1" "$log.2"
    mv "$log" "$log.1"
  fi
done
find "$ROOT/logs" -type f -name 'run-*.jsonl' -mtime +30 -delete 2>/dev/null || true

# launchd can inherit unrelated interactive-shell variables. Start the service
# from an explicit allowlist. Provider subscription credentials remain in the
# user's HOME auth store and do not need to be copied into this environment.
# Keep common user-installed Node and Pi locations without assuming a specific
# username, Node version, or package-manager layout.
USER_HOME="${HOME:-$(cd ~ && pwd -P)}"
USER_NAME="${USER:-$(id -un)}"
SERVICE_PATH="$ROOT/.venv/bin"

add_path() {
  local path="$1"
  [ -d "$path" ] || return 0
  case ":$SERVICE_PATH:" in
    *":$path:"*) ;;
    *) SERVICE_PATH="$SERVICE_PATH:$path" ;;
  esac
}

if command -v node >/dev/null 2>&1; then
  add_path "$(dirname "$(command -v node)")"
fi
for node_bin in "$USER_HOME"/.nvm/versions/node/*/bin; do
  [ -x "$node_bin/node" ] && add_path "$node_bin"
done
for bin_dir in \
  "$USER_HOME/.local/bin" \
  "$USER_HOME/.npm-global/bin" \
  /opt/homebrew/bin \
  /usr/local/bin \
  /usr/bin \
  /bin \
  /usr/sbin \
  /sbin; do
  add_path "$bin_dir"
done

exec /usr/bin/env -i \
  HOME="$USER_HOME" \
  USER="$USER_NAME" \
  LOGNAME="${LOGNAME:-$USER_NAME}" \
  LANG="${LANG:-en_US.UTF-8}" \
  TMPDIR="${TMPDIR:-/tmp}" \
  PATH="$SERVICE_PATH" \
  FRONTIER_ROOT="$ROOT" \
  PI_SKIP_VERSION_CHECK=1 \
  PI_TELEMETRY=0 \
  "$PYTHON" -m frontier_daily.cli serve
