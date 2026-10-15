#!/usr/bin/env bash
# Restore a backup into the running db container. DESTRUCTIVE: drops and recreates the target database.
# usage: scripts/restore_db.sh <s3-key-or-latest> --yes
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"
PREFIX="${BACKUP_S3_PREFIX:-e-mandi/backups/}"; DB="${POSTGRES_DB:-emandi}"; USER_="${POSTGRES_USER:-emandi}"
WHICH="${1:?usage: restore_db.sh <s3-key|latest> --yes}"; [ "${2:-}" = "--yes" ] || { echo "refusing without --yes" >&2; exit 2; }
if [ "$WHICH" = "latest" ]; then WHICH="${PREFIX}$(aws s3 ls "s3://${BACKUP_S3_BUCKET}/${PREFIX}" | awk '{print $4}' | grep -E "^${DB}-" | sort | tail -1)"; fi
COMPOSE="docker compose -f docker-compose.yml"; [ -f docker-compose.prod.yml ] && COMPOSE="$COMPOSE -f docker-compose.prod.yml"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
aws s3 cp "s3://${BACKUP_S3_BUCKET}/${WHICH}" "$TMP" --only-show-errors; gzip -t "$TMP"
echo "stopping api/worker, restoring ${WHICH} into ${DB}"
$COMPOSE stop api worker
$COMPOSE exec -T db psql -U "$USER_" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$DB\" WITH (FORCE)" -c "CREATE DATABASE \"$DB\" OWNER \"$USER_\""
$COMPOSE exec -T db psql -U "$USER_" -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS vector"
gunzip -c "$TMP" | $COMPOSE exec -T db psql -U "$USER_" -d "$DB" -v ON_ERROR_STOP=1 -q
$COMPOSE run --rm migrate
$COMPOSE up -d api worker
echo "restore complete"
