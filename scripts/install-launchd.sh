#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LABEL="com.aifrontier.daily"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
TMP="$TARGET.tmp.$$"
UID_NUM="$(id -u)"

[ -x "$ROOT/.venv/bin/python" ] || { echo "请先运行 $ROOT/scripts/setup.sh" >&2; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$TMP" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/run-server.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>ProcessType</key>
  <string>Background</string>
  <key>StandardOutPath</key>
  <string>$ROOT/logs/service.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/service.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$TMP" >/dev/null
chmod 600 "$TMP"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
mv "$TMP" "$TARGET"
launchctl bootstrap "gui/$UID_NUM" "$TARGET"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"
for _ in $(seq 1 30); do
  if /usr/bin/curl -fsS --max-time 1 http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
    echo "已安装服务：$LABEL"
    echo "管理页面：http://127.0.0.1:8787"
    exit 0
  fi
  sleep 0.5
done
echo "已安装服务：$LABEL，但健康检查接口尚未就绪，请查看 logs/service.err.log" >&2
exit 1
