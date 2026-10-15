#!/usr/bin/env bash
# Run ON THE SERVER (via SSM Session Manager / send-command) as root: install a release bundle, health-gate it, roll back on failure.
# usage: sudo bash deploy.sh <release-name|latest>
set -euo pipefail
ROOT=/opt/emandi; SHARED="$ROOT/shared"
set -a; . "$SHARED/host.env"; set +a
WANT="${1:?usage: deploy.sh <release-name|latest>}"
if [ "$WANT" = "latest" ]; then
  WANT="$(aws s3 ls "s3://${OPS_BUCKET}/releases/" | awk '{print $4}' | grep -E '\.tar\.gz$' | sort | tail -1)"; WANT="${WANT%.tar.gz}"
fi
[[ "$WANT" =~ ^e-mandi-[0-9]{8}T[0-9]{6}Z$ ]] || { echo "bad release name: $WANT" >&2; exit 2; }
DEST="$ROOT/releases/$WANT"; PREV="$(readlink -f "$ROOT/current" 2>/dev/null || true)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
aws s3 cp "s3://${OPS_BUCKET}/releases/$WANT.tar.gz" "$TMP/" --only-show-errors
aws s3 cp "s3://${OPS_BUCKET}/releases/$WANT.tar.gz.sha256" "$TMP/" --only-show-errors
( cd "$TMP" && sha256sum -c "$WANT.tar.gz.sha256" )
mkdir -p "$DEST" && tar -xzf "$TMP/$WANT.tar.gz" -C "$DEST"
bash "$DEST/scripts/render_env.sh"
ln -sfn "$SHARED/.env" "$DEST/.env"
compose() { ( cd "$1" && docker compose -f docker-compose.yml -f docker-compose.prod.yml "${@:2}" ); }

wait_ready() {  # api must report ready (db + redis) AND the worker heartbeat must be fresh
  for _ in $(seq 1 40); do
    out="$(compose "$1" exec -T api curl -fsS http://127.0.0.1:8000/health/ready 2>/dev/null || true)"
    if echo "$out" | grep -q '"status":"ready"' && echo "$out" | grep -q '"worker":"ok"'; then return 0; fi
    sleep 5
  done
  return 1
}

echo "building $WANT"
compose "$DEST" build --pull
ln -sfn "$DEST" "$ROOT/current"
if compose "$DEST" up -d --remove-orphans && wait_ready "$DEST"; then
  echo "deploy OK: $WANT"
  ls -1dt "$ROOT"/releases/* | tail -n +6 | xargs -r rm -rf   # keep the 5 newest
  exit 0
fi
echo "deploy FAILED health gate: $WANT" >&2
compose "$DEST" logs --tail=80 api worker migrate >&2 || true
if [ -n "$PREV" ] && [ -d "$PREV" ] && [ "$PREV" != "$DEST" ]; then
  echo "rolling back to $PREV (database migrations are forward-only: see docs/AWS_DEPLOYMENT.md)" >&2
  ln -sfn "$PREV" "$ROOT/current"; ln -sfn "$SHARED/.env" "$PREV/.env"
  compose "$PREV" up -d --remove-orphans || true
fi
exit 1
