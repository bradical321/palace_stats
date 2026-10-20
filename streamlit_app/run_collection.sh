#!/bin/bash
# Pulls new matches, then refreshes opponent scouting for anyone new.
# Runs on a cron schedule — see the crontab entry (TZ=America/New_York) for timing.
cd "$(dirname "$0")"

# Drive settings (FC_STORAGE_BACKEND, folder id, key path) live outside the repo.
# Without this file the scripts fall back to local CSVs in data/.
ENV_FILE="$HOME/.config/fc_scuffed/env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

echo "===== $(date) ====="
../.venv/bin/python collector.py
../.venv/bin/python opponent_scout.py
echo "===== done $(date) ====="
echo
