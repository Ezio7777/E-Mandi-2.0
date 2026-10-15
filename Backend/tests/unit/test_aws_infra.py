"""Stage 21: guard the AWS template and ops scripts (no AWS access needed)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class L(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):  # CloudFormation short-form intrinsics -> plain data
    v = loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else (
        loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node, deep=True))
    return {suffix: v}


L.add_multi_constructor("!", _tag)
T = yaml.load((ROOT / "infra/cloudformation.yaml").read_text(), Loader=L)  # noqa: S506  (SafeLoader subclass that only adds CloudFormation tags)
R = T["Resources"]


def of(type_):
    return {k: v for k, v in R.items() if v["Type"] == type_}


def test_cfn_lint_clean_when_available():
    exe = shutil.which("cfn-lint") or str(Path(os.sys.executable).parent / "cfn-lint")
    if not Path(exe).exists():
        pytest.skip("cfn-lint not installed")
    r = subprocess.run([exe, str(ROOT / "infra/cloudformation.yaml")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_buckets_private_encrypted_versioned_and_retained():
    buckets = of("AWS::S3::Bucket")
    assert len(buckets) == 2
    for name, b in buckets.items():
        p = b["Properties"]
        assert all(p["PublicAccessBlockConfiguration"].values()), name
        assert p["BucketEncryption"] and p["VersioningConfiguration"]["Status"] == "Enabled"
        assert b["DeletionPolicy"] == "Retain"
    assert len(of("AWS::S3::BucketPolicy")) == 2
    for pol in of("AWS::S3::BucketPolicy").values():
        s = pol["Properties"]["PolicyDocument"]["Statement"][0]
        assert s["Effect"] == "Deny" and s["Condition"]["Bool"]["aws:SecureTransport"] == "false"


def test_uploads_cors_is_restricted_to_the_frontend_origin():
    rules = R["UploadsBucket"]["Properties"]["CorsConfiguration"]["CorsRules"]
    for r in rules:
        assert "*" not in r["AllowedOrigins"] and r["AllowedOrigins"] == [{"Ref": "FrontendOrigin"}]
        assert set(r["AllowedMethods"]) <= {"GET", "HEAD", "POST"}


def test_instance_role_is_least_privilege():
    stmts = R["InstanceRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    for s in stmts:
        actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        assert not any(a == "*" or a.endswith(":*") for a in actions), s["Sid"]
        if s["Resource"] == "*":  # only the namespaced metric call and SMS publish (no ARN exists for phone numbers) may be unscoped
            if s["Sid"] == "SmsPublish":
                assert s["Action"] == "sns:Publish"
            else:
                assert s["Action"] == "cloudwatch:PutMetricData" and s["Condition"]["StringEquals"]["cloudwatch:namespace"] == "EMandi"
    assert R["InstanceRole"]["Properties"]["ManagedPolicyArns"] == ["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"]


def test_network_and_host_hardening():
    ing = R["SecurityGroup"]["Properties"]["SecurityGroupIngress"]
    plain = [i for i in ing if isinstance(i, dict) and "IpProtocol" in i]
    assert {i["FromPort"] for i in plain} == {80, 443}  # SSH rule only exists behind the OpenSsh condition
    ssh = next(i for i in ing if isinstance(i, dict) and "If" in i)["If"]
    assert ssh[1]["FromPort"] == 22 and ssh[1]["CidrIp"] == {"Ref": "SshCidr"}
    inst = R["Instance"]["Properties"]
    assert inst["MetadataOptions"]["HttpTokens"] == "required"
    assert inst["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] is True
    assert inst["BlockDeviceMappings"][0]["Ebs"]["DeleteOnTermination"] is False


def test_alarms_cover_health_backup_and_host():
    names = {a["Properties"]["MetricName"] for a in of("AWS::CloudWatch::Alarm").values()}
    assert {"StatusCheckFailed_System", "CPUUtilization", "HealthFailure", "BackupSuccess"} <= names
    assert R["AppUnhealthyAlarm"]["Properties"]["TreatMissingData"] == "breaching"
    assert R["BackupMissingAlarm"]["Properties"]["TreatMissingData"] == "breaching"


def test_scripts_parse_and_have_strict_mode():
    for n in ("release.sh", "deploy.sh", "render_env.sh", "healthcheck.sh", "backup_db.sh", "restore_db.sh"):
        p = ROOT / "scripts" / n
        assert subprocess.run(["bash", "-n", str(p)]).returncode == 0, n
        assert "set -" in p.read_text()
    assert "sha256sum -c" in (ROOT / "scripts/deploy.sh").read_text()
    assert "release.sh" not in (ROOT / ".dockerignore").read_text()
    assert "--exclude='.env'" in (ROOT / "scripts/release.sh").read_text()


def _run_render(tmp_path, params):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "host.env").write_text("AWS_REGION=ap-south-1\nOPS_BUCKET=ops\nUPLOADS_BUCKET=up\nPARAM_PREFIX=/emandi/prod\nAPI_DOMAIN=api.example.com\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "aws").write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps([[f"/emandi/prod/{k}", v] for k, v in params.items()]) + "\nEOF\n")
    (bin_ / "aws").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "SHARED_DIR": str(shared)}
    return subprocess.run(["bash", str(ROOT / "scripts/render_env.sh")], capture_output=True, text=True, env=env), shared / ".env"


GOOD = {"POSTGRES_PASSWORD": "pw", "REDIS_PASSWORD": "rp", "JWT_SECRET": "j" * 40, "CORS_ORIGINS": "https://app.example.com",
        "FRONTEND_URL": "https://app.example.com", "ACME_EMAIL": "ops@example.com"}


def test_render_env_builds_private_env_file(tmp_path):
    r, out = _run_render(tmp_path, GOOD)
    assert r.returncode == 0, r.stderr
    text = out.read_text()
    for line in ("ENVIRONMENT=production", "AWS_S3_BUCKET=up", "BACKUP_S3_BUCKET=ops", "JWT_SECRET=" + "j" * 40, "API_DOMAIN=api.example.com"):
        assert line in text.splitlines()
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    assert "j" * 40 not in r.stdout + r.stderr


@pytest.mark.parametrize("mutate,msg", [
    (lambda p: p.pop("JWT_SECRET"), "missing required"),
    (lambda p: p.update(JWT_SECRET="short"), ">= 32"),
    (lambda p: p.update(CORS_ORIGINS="*"), "must not contain"),
    (lambda p: p.update(REDIS_PASSWORD="a\nb"), "newline"),
])
def test_render_env_refuses_unsafe_configuration(tmp_path, mutate, msg):
    params = dict(GOOD)
    mutate(params)
    r, out = _run_render(tmp_path, params)
    assert r.returncode != 0 and msg in r.stderr
    assert not out.exists()


def test_explicit_parameters_override_derived_values(tmp_path):
    r, out = _run_render(tmp_path, {**GOOD, "ENVIRONMENT": "staging", "AWS_S3_BUCKET": "custom"})
    assert r.returncode == 0
    lines = out.read_text().splitlines()
    assert "ENVIRONMENT=staging" in lines and "AWS_S3_BUCKET=custom" in lines and "ENVIRONMENT=production" not in lines
