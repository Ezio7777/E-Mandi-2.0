"""Stage 20: deployment artefacts stay consistent with the app (cheap guards; no Docker daemon needed)."""
import re
from pathlib import Path

import yaml
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "API_DOMAIN", "ACME_EMAIL", "WEB_CONCURRENCY",
                "RUN_MIGRATIONS"}


def env_keys() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_env_example_keys_are_real_settings_and_hold_no_secrets():
    keys = env_keys()
    unknown = set(keys) - set(Settings.model_fields) - COMPOSE_ONLY
    assert not unknown, unknown
    for k, v in keys.items():
        if any(w in k for w in ("SECRET", "PASSWORD", "API_KEY", "TOKEN")) and k != "BACKUP_S3_PREFIX":
            assert v == "", f"{k} must be empty in .env.example"


def test_env_example_loads_into_settings(monkeypatch):
    for k, v in env_keys().items():
        if k in Settings.model_fields:
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:realpw@db/x")
    s = Settings(_env_file=None)
    assert s.is_production and "*" not in s.cors_origins_list


def test_compose_files_are_valid_and_wire_every_role():
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert {"db", "redis", "migrate", "api", "worker"} <= set(base["services"])
    assert base["services"]["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert "127.0.0.1:8000:8000" in base["services"]["api"]["ports"]  # never published on 0.0.0.0 in the base stack
    for name in ("db", "redis"):
        assert "ports" not in base["services"][name], f"{name} must not be published"
        assert "healthcheck" in base["services"][name]
    assert base["services"]["db"]["image"].startswith("pgvector/pgvector")
    text = (ROOT / "docker-compose.prod.yml").read_text()
    assert "caddy" in text and "API_DOMAIN" in text


def test_entrypoint_roles_match_dockerfile_and_worker_settings():
    ep = (ROOT / "docker/entrypoint.sh").read_text()
    for role in ("api)", "worker)", "migrate)"):
        assert role in ep
    assert "arq app.workers.settings.WorkerSettings" in ep and 'gunicorn "app.main:create_app()"' in ep
    df = (ROOT / "Dockerfile").read_text()
    assert "chmod 0555 /usr/local/bin/entrypoint.sh" in df and "USER emandi" in df and "tini" in df and "HEALTHCHECK" in df and "alembic.ini" in df and "./alembic" in df
    assert not re.search(r"^\s*(ENV|ARG)\s+\w*(SECRET|PASSWORD|KEY)\w*=", df, re.M | re.I)


def test_dockerignore_keeps_secrets_and_tests_out_of_the_image():
    ig = (ROOT / ".dockerignore").read_text().split()
    assert ".env" in ig and "tests" in ig and ".git" in ig


def test_caddyfile_protects_sse_and_body_size():
    c = (ROOT / "docker/Caddyfile").read_text()
    assert "flush_interval -1" in c and "max_size" in c and "/api/v1/notifications/stream" in c


def test_backup_scripts_are_executable_and_safe():
    for n in ("backup_db.sh", "restore_db.sh"):
        p = ROOT / "scripts" / n
        assert "set -euo pipefail" in p.read_text()
    assert "--yes" in (ROOT / "scripts/restore_db.sh").read_text()
