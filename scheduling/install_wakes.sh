#!/bin/bash
# One-time setup, run with sudo. Copies the wake scheduler somewhere only root
# can edit (it runs as root), then loads the daemon.
set -e
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
here="$(cd "$(dirname "$0")" && pwd)"
install -d -o root -g wheel -m 755 /Library/PalaceStats
install -o root -g wheel -m 755 "$here/schedule_wakes.sh" /Library/PalaceStats/schedule_wakes.sh
install -o root -g wheel -m 644 "$here/com.palace.schedule-wakes.plist" /Library/LaunchDaemons/com.palace.schedule-wakes.plist
launchctl bootout system/com.palace.schedule-wakes 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.palace.schedule-wakes.plist
sleep 2
pmset -g sched
