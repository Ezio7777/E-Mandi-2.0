# Docker (Stage 20)

| File | Purpose |
|---|---|
| `Dockerfile` | One multi-stage image (non-root, tini, healthcheck). Role chosen by the first argument: `api` (default), `worker`, `migrate`, `seed`. |
| `docker/entrypoint.sh` | Waits for Postgres, then runs gunicorn+uvicorn workers / the arq worker / `alembic upgrade head`. |
| `docker-compose.yml` | db (pgvector/pg16), redis (AOF + password), one-shot `migrate`, `api` (127.0.0.1:8000), `worker` (heartbeat healthcheck). DB and Redis are never published. |
| `docker-compose.prod.yml` | Adds Caddy (automatic HTTPS, SSE-safe, 8 MB body cap), removes the host port from the API, log rotation, memory limits. |
| `docker/Caddyfile` | Reverse proxy config (`API_DOMAIN`, `ACME_EMAIL` from `.env`). |
| `.env.example` | Every supported variable; secrets are empty. Copy to `.env` (never commit it). |

## Local / single host
```bash
cp .env.example .env            # set POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET (>=32 chars), ENVIRONMENT=development for local
docker compose up -d --build    # migrations run automatically via the `migrate` service
curl localhost:8000/health/ready
```

## Production (EC2, Stage 21 covers provisioning)
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Set `ENVIRONMENT=production`, `CORS_ORIGINS`, `API_DOMAIN`, `ACME_EMAIL` and a strong `JWT_SECRET`; the app refuses to start in production with a weak secret or `*` CORS.

## Operations
* Migrate only: `docker compose run --rm migrate`
* Worker status: `GET /api/v1/admin/workers` (heartbeat age + last result of each recovery sweeper)
* Backup to S3 (cron on the host): `bash scripts/backup_db.sh`; restore: `bash scripts/restore_db.sh latest --yes`
* Scripts do not rely on the executable bit: run them with `bash`.
