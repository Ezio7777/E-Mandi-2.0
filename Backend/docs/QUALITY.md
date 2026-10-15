# Quality gates (Stage 22)

| Gate | Command | State |
|---|---|---|
| Lint | `ruff check .` | clean (rules: E F I B UP S ASYNC SIM RUF) |
| Types | `mypy app` | clean, 196 files (`check_untyped_defs`, pydantic plugin) |
| Tests | `pytest` (needs Postgres+pgvector and Redis) | 500+ tests |
| Migrations | `alembic upgrade head && alembic check` | enforced in CI |
| Infra | `cfn-lint infra/cloudformation.yaml`, `shellcheck`, `docker compose config` | enforced in CI |
| Dependencies | `pip-audit` | no known vulnerabilities at delivery |
| Secrets | gitleaks in CI | no secrets in the tree |
| Image | CI builds the Docker image and smoke-tests it | CI only (not built in the delivery sandbox) |

## Deliberate choices
* `ruff format` is **not** enforced: it would rewrite ~195 delivered files for no behavioural gain. `line-length = 150` and `E501` is ignored because long literals (voice templates, messages) are intentional.
* Ignored rules: `E741` (`l` = listing), `RUF059`, `SIM108`. `alembic/versions` is excluded (applied migrations are never edited).
* mypy is a **baseline**, not `strict`. Enabling `strict = true` currently adds roughly 200 annotation-only findings (missing return types on route handlers/dependencies, bare generics). Real defects it found (unnarrowed Optional rows, a mis-typed ternary, forward references) were fixed; one finding exposed a genuine bug I introduced during the cleanup (a commented-out `.digest()`), which the test suite also covers now.
* Coverage gate in CI is 80 %; raise it as tests grow.

## Backlog
Strict mypy; `ruff format`; an OTP/SMS provider for production (see SECURITY_AUDIT); load tests; seed data scripts.
