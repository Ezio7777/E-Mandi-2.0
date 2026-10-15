#!/usr/bin/env bash
# Logical backup: pg_dump (inside the db container) -> gzip -> S3, then prune backups older than BACKUP_RETENTION_DAYS.
# Run from the repo directory on the host (cron). Needs: docker compose, aws cli (EC2 instance role is enough).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; [ -f /opt/emandi/shared/host.env ] && . /opt/emandi/shared/host.env; set +a
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"
PREFIX="${BACKUP_S3_PREFIX:-e-mandi/backups/}"; RETAIN="${BACKUP_RETENTION_DAYS:-14}"
DB="${POSTGRES_DB:-emandi}"; USER_="${POSTGRES_USER:-emandi}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; KEY="${PREFIX}${DB}-${STAMP}.sql.gz"
COMPOSE="docker compose -f docker-compose.yml"; [ -f docker-compose.prod.yml ] && COMPOSE="$COMPOSE -f docker-compose.prod.yml"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
$COMPOSE exec -T db pg_dump -U "$USER_" -d "$DB" --no-owner --no-privileges | gzip -9 > "$TMP"
[ "$(stat -c %s "$TMP")" -gt 1024 ] || { echo "backup suspiciously small, aborting" >&2; exit 1; }
gzip -t "$TMP"
aws s3 cp "$TMP" "s3://${BACKUP_S3_BUCKET}/${KEY}" --sse AES256 --only-show-errors
echo "uploaded s3://${BACKUP_S3_BUCKET}/${KEY}"
[ -z "${AWS_REGION:-}" ] || aws cloudwatch put-metric-data --region "$AWS_REGION" --namespace EMandi --metric-name BackupSuccess --value 1 --unit Count >/dev/null 2>&1 || true
CUTOFF="$(date -u -d "-${RETAIN} days" +%Y%m%d)"
aws s3 ls "s3://${BACKUP_S3_BUCKET}/${PREFIX}" | awk '{print $4}' | grep -E "^${DB}-[0-9]{8}T" | while read -r f; do
  d="${f#${DB}-}"; d="${d:0:8}"
  if [ "$d" -lt "$CUTOFF" ]; then aws s3 rm "s3://${BACKUP_S3_BUCKET}/${PREFIX}${f}" --only-show-errors && echo "pruned $f"; fi
done
