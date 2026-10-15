# E-MANDI 2.0 Backend
FastAPI modular monolith. Setup, Docker, AWS and OAuth docs are completed in later stages.
Quick start: `cp .env.example .env && make install && make dev`.

## Operations docs
* Docker: `docker/README.md` - AWS runbook: `docs/AWS_DEPLOYMENT.md` - quality gates: `docs/QUALITY.md` - audit: `docs/SECURITY_AUDIT.md`
* CI/CD: `.github/workflows/ci.yml` (lint, mypy, tests, infra, security, image) and `deploy.yml` (OIDC, SSM, health-gated)
