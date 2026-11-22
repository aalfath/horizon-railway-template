#!/bin/sh
# Railway start script for Horizon: prepares the volume, then runs the web UI
# and the daily scheduler (railway/server.py) as the unprivileged user.
set -eu

DATA="${HORIZON_DATA_DIR:-/app/data}"
mkdir -p "$DATA/summaries" "$DATA/logs"

if [ -z "${HORIZON_PASSWORD:-}" ]; then
  echo "HORIZON_PASSWORD is empty: set it (the template generates one) so the web UI is not public." >&2
  exit 1
fi

if [ ! -f "$DATA/config.json" ]; then
  cp /app/railway/config.default.json "$DATA/config.json"
  echo "Created $DATA/config.json from the template's default sources."
fi
[ -f "$DATA/config.example.json" ] || cp /app/defaults/config.example.json "$DATA/config.example.json"

# Railway mounts volumes as root; hand the data directory to the app user.
chown -R 10001:10001 "$DATA" /app/docs

exec setpriv --reuid=10001 --regid=10001 --clear-groups \
  env HOME=/home/horizon /app/.venv/bin/python /app/railway/server.py
