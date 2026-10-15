# Security and production-readiness audit (Stage 22)

Scope: this backend as delivered. Method: automated scans (ruff `S` rules, bandit, pip-audit, secret regex scan), the OpenAPI-driven test sweeps from Stage 19, and a manual review of the controls below. It is **not** a penetration test or a compliance certification.

## Verified controls
| Area | Control | Evidence |
|---|---|---|
| AuthN | Argon2 passwords, short-lived JWT (15 min) bound to a server-side session, refresh rotation, forged/expired/alg=none rejected | tests/unit/test_security.py, test_security_sweep.py |
| AuthZ | Role gates on every admin/audit/analytics route; owner checks hide other users' objects as 404; four-eyes on sensitive admin actions | route sweep, test_risk.py, test_concurrency_extra.py |
| Money | Amounts computed server-side; webhook HMAC verified before any DB write; unique event id + `processed_at`; amount/currency must match | test_payments.py |
| AI safety | LLMs never set prices, pick inventory or take sensitive actions; risk output is FLAGGED_FOR_REVIEW / HIGH_RISK_SIGNAL only; no chain-of-thought stored | agent tests |
| Input | Pydantic validation (`extra="forbid"` on write models), bounded pagination, body cap 10 MB (app) / 8 MB (Caddy), image/audio sniffing | sweeps, test_hardening.py |
| Output | Uniform error envelope, no stack traces, no secrets/hashes in responses | test_security_sweep.py |
| Transport | HSTS in production, security headers, CORS allow-list (never `*` with credentials), HTTPS via Caddy, TLS-only S3 | config validator, infra tests |
| Config | Production refuses: weak/short JWT secret, `*` CORS, placeholder DB password, razorpay without credentials | test_hardening.py |
| Data | Audit log is append-only (DB trigger); S3 private + encrypted + versioned; presigned uploads with size/type conditions | migrations, infra tests |
| Ops | Non-root container, DB/Redis never published, secrets from SSM, IMDSv2, least-privilege role, health + backup alarms | infra tests |
| Supply chain | pip-audit clean at delivery; Dependabot + CI audit | CI |

## Findings and status
1. **Fixed (Stage 20):** worker heartbeat format made `/health/ready` return 503 while the worker ran.
2. **Fixed (Stage 22):** unbounded request bodies at the app layer; production could start with the placeholder DB password or half-configured Razorpay.
3. **Fixed (Stage 22):** a silent `except: pass` on SSE counter release now logs (the counter has a TTL).
4. **Resolved - OTP in production:** set `SMS_PROVIDER=sns` (AWS SNS, instance role; the stack grants `sns:Publish`). In India, register the sender ID and message template (DLT) and set `SMS_SENDER_ID`/`SMS_TEMPLATE` to match; set an account SMS spending limit in SNS. `auto` stays unavailable in production and `console` is refused. OTP requests are rate-limited per IP (5/10 min) and per phone (3/10 min).
5. **Open - single host:** availability and recovery limits are described in docs/AWS_DEPLOYMENT.md.
6. **Open - demo mode:** `DEMO_MODE=true` enables demo accounts and the payment simulator (mock provider only). Keep it `false` in production unless you want a public demo.
7. **Accepted - Redis password in the container environment:** DB/Redis are reachable only on the private Docker network.
8. **Not covered:** penetration test, DDoS protection (consider CloudFront/WAF), formal data-protection review for your jurisdiction, a regulated escrow/settlement setup (the payment flow is a sandbox-first marketplace flow, not escrow).

## Before go-live checklist
- [ ] Real secrets in SSM (`JWT_SECRET`, DB/Redis passwords, provider keys); `ENVIRONMENT=production`
- [ ] `CORS_ORIGINS` and `FRONTEND_URL` set to the exact production origin
- [ ] Payment provider sandbox end-to-end tested, webhook URL + secret configured
- [ ] Restore from backup rehearsed on a scratch instance
- [ ] Alarm e-mail confirmed; first alarm test fired
- [ ] Admin accounts created; `DEMO_MODE` decision made
