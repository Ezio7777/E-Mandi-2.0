#!/usr/bin/env bash
# Builds /opt/emandi/shared/.env from SSM Parameter Store (SecureString) + host.env. Secrets never touch git or the AMI.
# Every parameter under $PARAM_PREFIX/ becomes KEY=value (name = last path segment).
set -euo pipefail
SHARED="${SHARED_DIR:-/opt/emandi/shared}"
set -a; . "$SHARED/host.env"; set +a
OUT="$SHARED/.env"; TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT; umask 077
aws ssm get-parameters-by-path --region "$AWS_REGION" --path "$PARAM_PREFIX" --recursive --with-decryption \
  --query 'Parameters[].[Name,Value]' --output json | python3 -c '
import json, sys
for name, value in json.load(sys.stdin):
    key = name.rsplit("/", 1)[-1]
    if "\n" in value or "\r" in value:
        sys.exit(f"parameter {key} contains a newline; refusing")
    print(f"{key}={value}")
' > "$TMP"
# values derived from the stack (explicit parameters win because they are appended last only when absent)
add() { grep -q "^$1=" "$TMP" || echo "$1=$2" >> "$TMP"; }
add ENVIRONMENT production
add AWS_REGION "$AWS_REGION"
add AWS_S3_BUCKET "$UPLOADS_BUCKET"
add BACKUP_S3_BUCKET "$OPS_BUCKET"
add API_DOMAIN "$API_DOMAIN"
add RUN_MIGRATIONS 0
for k in POSTGRES_PASSWORD REDIS_PASSWORD JWT_SECRET CORS_ORIGINS FRONTEND_URL ACME_EMAIL; do
  grep -q "^$k=.\+" "$TMP" || { echo "missing required parameter $PARAM_PREFIX/$k" >&2; exit 1; }
done
JWT="$(grep '^JWT_SECRET=' "$TMP" | cut -d= -f2-)"; [ "${#JWT}" -ge 32 ] || { echo "JWT_SECRET must be >= 32 chars" >&2; exit 1; }
grep -q '^CORS_ORIGINS=.*\*' "$TMP" && { echo "CORS_ORIGINS must not contain *" >&2; exit 1; }
install -m 0600 "$TMP" "$OUT"
echo "rendered $OUT ($(wc -l < "$OUT") variables)"
