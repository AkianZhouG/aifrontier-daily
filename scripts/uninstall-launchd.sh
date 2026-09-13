#!/bin/bash
set -euo pipefail
LABEL="com.aifrontier.daily"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$TARGET"
echo "已移除服务：$LABEL。应用数据已保留。"
