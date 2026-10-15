#!/bin/sh
# Roles: api (default) | worker | migrate | seed | shell-style passthrough for any other command.
set -eu

wait_for_db() {
  python - <<'PY'
import asyncio, os, sys, time
import asyncpg
url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
async def main():
    for i in range(60):
        try:
            c = await asyncpg.connect(url, timeout=3)
            await c.close()
            return
        except Exception as e:  # noqa: BLE001
            print(f"waiting for database ({i + 1}/60): {type(e).__name__}", flush=True)
            await asyncio.sleep(2)
    sys.exit("database never became reachable")
asyncio.run(main())
PY
}

case "${1:-api}" in
  api)
    wait_for_db
    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then alembic upgrade head; fi
    exec gunicorn "app.main:create_app()" \
      --worker-class uvicorn.workers.UvicornWorker \
      --workers "${WEB_CONCURRENCY:-2}" --bind 0.0.0.0:8000 \
      --timeout 60 --graceful-timeout 30 --keep-alive 15 \
      --max-requests 2000 --max-requests-jitter 200 \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
      --access-logfile - --error-logfile -
    ;;
  worker)
    wait_for_db
    exec arq app.workers.settings.WorkerSettings
    ;;
  migrate)
    wait_for_db
    exec alembic upgrade head
    ;;
  seed)
    wait_for_db
    exec python -m scripts.seed
    ;;
  *)
    exec "$@"
    ;;
esac
