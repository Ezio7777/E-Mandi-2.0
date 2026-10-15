import base64
import json

import boto3
import pytest
from app.core.config import Settings
from app.core.errors import ProviderError
from app.integrations.aws.s3 import S3Storage
from moto import mock_aws

S = Settings(ENVIRONMENT="test", AWS_S3_BUCKET="emandi-test", AWS_REGION="ap-south-1",
             JWT_SECRET="unit-test-secret-unit-test-secret-000000")


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        client.create_bucket(Bucket="emandi-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        yield S3Storage(S, client=client), client


async def test_head_get_delete_roundtrip(storage):
    s, client = storage
    client.put_object(Bucket="emandi-test", Key="k/a.jpg", Body=b"hello", ContentType="image/jpeg")
    head = await s.head("k/a.jpg")
    assert head and head.size == 5 and head.content_type == "image/jpeg"
    assert await s.get_bytes("k/a.jpg", 100) == b"hello"
    with pytest.raises(ProviderError):
        await s.get_bytes("k/a.jpg", 3)  # cap enforced, never reads unbounded data
    await s.delete("k/a.jpg")
    assert await s.head("k/a.jpg") is None
    await s.delete("k/missing.jpg")  # idempotent


async def test_presigned_post_policy_enforces_size_type_key(storage):
    s, _ = storage
    p = await s.presign_post("e-mandi/listings/x/y.jpg", "image/jpeg", 5 * 1024 * 1024, 300)
    policy = json.loads(base64.b64decode(p.fields["policy"]))
    conds = policy["conditions"]
    assert ["content-length-range", 1, 5 * 1024 * 1024] in conds
    assert {"Content-Type": "image/jpeg"} in conds
    assert {"x-amz-server-side-encryption": "AES256"} in conds
    assert {"key": "e-mandi/listings/x/y.jpg"} in conds
    assert ("emandi-test" in p.url and "AWSAccessKeyId" in p.fields) or "x-amz-credential" in p.fields


async def test_presigned_get_url(storage):
    s, _ = storage
    url = await s.presign_get("e-mandi/listings/x/y.jpg", 900)
    assert "y.jpg" in url and "X-Amz-Expires=900" in url and "X-Amz-Signature" in url
