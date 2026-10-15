# AWS deployment runbook (Stage 21)

Target: **one always-on EC2 host** running Docker Compose (API, arq worker, Postgres+pgvector, Redis) behind **Caddy** (automatic HTTPS),
**S3** for images, **S3 + cron** for database backups, **SSM Parameter Store** for secrets, **CloudWatch** alarms by e-mail.
This is deliberately simple and cheap; the trade-off is a single host (see "Limits" at the end).

```
Internet ──443──▶ Caddy ──▶ api (gunicorn/uvicorn) ──▶ Postgres (volume)   ──▶ nightly pg_dump ─▶ S3 ops bucket
                                  │                  ▶ Redis (volume)
                                  └──▶ worker (arq + cron sweepers)  ──▶ S3 uploads bucket (images, presigned POST)
```

## 1. Create the stack
```bash
aws cloudformation deploy --stack-name e-mandi --template-file infra/cloudformation.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides DomainName=api.example.com FrontendOrigin=https://app.example.com AlarmEmail=ops@example.com
aws cloudformation describe-stacks --stack-name e-mandi --query 'Stacks[0].Outputs'
```
Then: (a) create a DNS **A record** for `DomainName` -> `PublicIp`; (b) confirm the SNS e-mail subscription.
Arm/Graviton: pass `InstanceType=t4g.small` and `LatestAmiId=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`.
The security group is created in your default VPC; add a `VpcId` if you do not have one.

What it creates: private versioned + encrypted buckets (uploads: CORS only for your frontend origin; ops: backups 30 d / releases 90 d lifecycle),
TLS-only bucket policies, an instance role limited to `e-mandi/*` in the uploads bucket, the backup/release prefixes, its own SSM parameters and one CloudWatch
namespace, an encrypted gp3 volume, IMDSv2 only, SG with 80/443 (22 only if you pass `SshCidr`), an Elastic IP, and four alarms
(system status with auto-recover, CPU, app health, missing backup). Buckets are `Retain` - deleting the stack never deletes your data.

## 2. Put the configuration in Parameter Store
Every parameter under `/emandi/prod/` becomes an environment variable (name = last path segment). Secrets are `SecureString`.
```bash
P=/emandi/prod
put() { aws ssm put-parameter --name "$P/$1" --type "${3:-SecureString}" --value "$2" --overwrite >/dev/null; }
put POSTGRES_PASSWORD "$(openssl rand -hex 24)"
put REDIS_PASSWORD    "$(openssl rand -hex 24)"
put JWT_SECRET        "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
put CORS_ORIGINS  https://app.example.com String
put FRONTEND_URL  https://app.example.com String
put ACME_EMAIL    ops@example.com String
# AI + payments (all optional until you enable them; models must be named explicitly)
put GEMINI_API_KEY ...;  put GEMINI_VISION_MODEL <model> String;  put GEMINI_TEXT_MODEL <model> String
put OPENAI_API_KEY ...;  put OPENAI_VISION_MODEL <model> String
put PAYMENT_PROVIDER razorpay String; put PAYMENT_KEY_ID ... String; put PAYMENT_KEY_SECRET ...; put PAYMENT_WEBHOOK_SECRET ...
put GOOGLE_CLIENT_ID ... String
put SMS_PROVIDER sns String; put SMS_SENDER_ID <dlt-sender-id> String   # phone-OTP login; see docs/SECURITY_AUDIT.md item 4
```
`AWS_S3_BUCKET`, `BACKUP_S3_BUCKET`, `AWS_REGION`, `API_DOMAIN` come from the stack automatically. **Do not set AWS keys**: the instance role is used.
`scripts/render_env.sh` refuses to continue if a required value is missing, `JWT_SECRET` is shorter than 32 chars, or `CORS_ORIGINS` contains `*`.

## 3. Release and deploy
On your machine (needs AWS credentials able to write the ops bucket):
```bash
OPS_BUCKET=<OpsBucketName> bash scripts/release.sh          # prints e.g. e-mandi-20261012T080000Z
```
**First deploy** (nothing is installed on the server yet) - open a shell with Session Manager (`aws ssm start-session --target <InstanceId>`):
```bash
sudo -i; set -a; . /opt/emandi/shared/host.env; set +a; R=e-mandi-20261012T080000Z
aws s3 cp s3://$OPS_BUCKET/releases/$R.tar.gz /tmp/ && mkdir -p /opt/emandi/boot && tar -xzf /tmp/$R.tar.gz -C /opt/emandi/boot
bash /opt/emandi/boot/scripts/deploy.sh $R
```
**Later deploys**: `sudo bash /opt/emandi/current/scripts/deploy.sh <release|latest>` (or `aws ssm send-command`).
`deploy.sh` verifies the checksum, renders the env, builds, starts, waits until `/health/ready` is `ready` **and** the worker heartbeat is fresh, and
otherwise re-links and restarts the previous release. It keeps the 5 newest releases. Migrations run in the one-shot `migrate` service before the API starts.

> **Migrations are forward-only.** An automatic rollback restores the previous *code*; if a release shipped an incompatible migration, restore the
> database from backup (section 5) or ship a corrective release. Write migrations as expand -> migrate -> contract so the previous release keeps working.

## 4. Verify
```bash
curl -fsS https://api.example.com/health/ready     # {"status":"ready","checks":{"database":"ok","redis":"ok","worker":"ok"}}
```
Then log in as an admin and open `GET /api/v1/admin/workers` (heartbeat age + last result of each sweeper) and `GET /api/v1/admin/agents`.
Payment webhook URL for the provider dashboard: `https://api.example.com/api/v1/payments/webhook`. Google OIDC authorised origin: your frontend origin.

## 5. Backups and restore
* Cron (installed by the stack) runs `scripts/backup_db.sh` daily at 02:15 UTC: `pg_dump | gzip` -> verified -> S3 (SSE) -> prune older than `BACKUP_RETENTION_DAYS`
  -> publishes `EMandi/BackupSuccess`; the alarm e-mails you if no backup succeeded for 26 h. The bucket also has a lifecycle rule and versioning.
* Restore (destructive, asks for `--yes`): `cd /opt/emandi/current && bash scripts/restore_db.sh latest --yes`.
* **Test the restore on a scratch instance before you need it** (restore into a second stack, run `alembic check`, hit `/health/ready`).
* Redis holds only caches, rate limits, voice sessions and the job queue; the sweepers re-enqueue lost agent jobs, so it is not backed up.

## 6. Operations
| Task | Command |
|---|---|
| Logs | `cd /opt/emandi/current && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=100 api worker` |
| Shell on the host | `aws ssm start-session --target <InstanceId>` (no SSH needed) |
| Rotate a secret | `aws ssm put-parameter --overwrite ...` then redeploy the same release (`deploy.sh <current>`); rotating `JWT_SECRET` logs everyone out |
| Disk | probe fails at 85 % used; grow the volume in the console, then `sudo growpart /dev/nvme0n1 1 && sudo xfs_growfs /` |
| OS patching | `sudo dnf -y update && sudo reboot` in a quiet hour; containers restart automatically (`restart: unless-stopped`) |

## Limits (be honest about them)
* One host = a reboot or failure means minutes of downtime (status-check alarm auto-recovers the instance; data is on the encrypted EBS volume, volumes are kept on termination).
* Postgres and Redis share the host's resources; move Postgres to RDS when traffic or recovery objectives demand it (only `DATABASE_URL` changes).
* Backups are daily logical dumps: worst-case data loss is up to ~24 h. Add more frequent runs to `/etc/cron.d/emandi` if that is too much.
* Nothing here replaces a payment-provider settlement process; the payment flow is a sandbox-first marketplace flow, not a regulated escrow.

## Sample data (staging / demos only)
`docker compose run --rm api python -m scripts.seed` creates demo accounts, sample farmers/buyers, ~30 days of **sample** market reports (labelled `SEED-SAMPLE`), listings and requirements; `python -m scripts.reset_seed` removes them. Both refuse to run when `ENVIRONMENT=production`.
