#!/usr/bin/env bash
# Host probe (cron, every 5 min): publishes EMandi/HealthFailure (0 = healthy, 1 = failing) to CloudWatch; the stack alarm
# e-mails after 3 consecutive failures. Checks: public HTTPS, API readiness (db+redis), worker heartbeat, disk space.
set -uo pipefail
SHARED=/opt/emandi/shared
set -a; . "$SHARED/host.env"; set +a
compose() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
fail=0; why=""
bad() { fail=1; why="$why $1"; }
curl -fsS --max-time 8 "https://${API_DOMAIN}/health/live" >/dev/null 2>&1 || bad public_https
ready="$(compose exec -T api curl -fsS --max-time 8 http://127.0.0.1:8000/health/ready 2>/dev/null || true)"
echo "$ready" | grep -q '"status":"ready"' || bad api_not_ready
echo "$ready" | grep -q '"worker":"ok"' || bad worker_stale
used="$(df --output=pcent / | tail -1 | tr -dc 0-9)"; [ "${used:-0}" -lt 85 ] || bad disk_${used}pct
echo "$(date -u +%FT%TZ) failure=$fail${why:+ reasons:$why}"
aws cloudwatch put-metric-data --region "$AWS_REGION" --namespace EMandi --metric-name HealthFailure --value "$fail" --unit Count >/dev/null 2>&1 || true
exit 0
