#!/usr/bin/env bash
# Nightly backup (cron: 15 3 * * * /opt/megavirtrace/deploy/backup.sh).  Keeps 14 days.
set -euo pipefail
DEST=${MEGAVIR_BACKUP_DIR:-/var/backups/megavirtrace}
mkdir -p "$DEST"
pg_dump --format=custom --dbname="${MEGAVIR_DATABASE_URL:?set MEGAVIR_DATABASE_URL}" --file="$DEST/megavir-$(date +%F).dump"
find "$DEST" -name 'megavir-*.dump' -mtime +14 -delete
