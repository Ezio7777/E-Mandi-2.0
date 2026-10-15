#!/usr/bin/env bash
# Run on YOUR machine: package the backend and upload it to the ops bucket (no git access needed on the server).
# usage: OPS_BUCKET=<bucket> bash scripts/release.sh      (AWS credentials of an admin/deployer profile)
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPS_BUCKET:?set OPS_BUCKET to the OpsBucketName stack output}"
NAME="e-mandi-$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar --exclude='.git' --exclude='.env' --exclude='.env.*' --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
    --exclude='.ruff_cache' --exclude='.mypy_cache' --exclude='*.egg-info' --exclude='*.zip' --exclude='backups' --exclude='.venv' \
    -czf "$TMP/$NAME.tar.gz" .
( cd "$TMP" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
aws s3 cp "$TMP/$NAME.tar.gz" "s3://${OPS_BUCKET}/releases/$NAME.tar.gz" --sse AES256 --only-show-errors
aws s3 cp "$TMP/$NAME.tar.gz.sha256" "s3://${OPS_BUCKET}/releases/$NAME.tar.gz.sha256" --sse AES256 --only-show-errors
echo "released: $NAME"
echo "deploy it:  sudo bash /opt/emandi/current/scripts/deploy.sh $NAME   (or first time: see docs/AWS_DEPLOYMENT.md)"
