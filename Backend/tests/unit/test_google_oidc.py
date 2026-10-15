import time

import jwt
import pytest
from app.core.errors import UnauthorizedError
from app.integrations.google.oidc import GoogleOIDCVerifier
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT = "cid.apps.googleusercontent.com"


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verifier(keypair, kid="k1"):
    v = GoogleOIDCVerifier(CLIENT)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(keypair.public_key(), as_dict=True) | {"kid": kid, "alg": "RS256"}
    v._keys, v._fetched_at = {kid: jwk}, time.monotonic()
    return v


def _tok(keypair, kid="k1", **over):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT, "sub": "123", "email": "A@Example.com",
              "email_verified": True, "name": "A", "iat": now, "exp": now + 300} | over
    return jwt.encode(claims, keypair, algorithm="RS256", headers={"kid": kid})


async def test_valid_token(keypair):
    ident = await _verifier(keypair).verify(_tok(keypair))
    assert ident.sub == "123" and ident.email == "a@example.com"


@pytest.mark.parametrize("over", [
    {"aud": "other-client"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 600},
    {"email_verified": False}, {"email": None},
])
async def test_rejects_bad_claims(keypair, over):
    with pytest.raises(UnauthorizedError):
        await _verifier(keypair).verify(_tok(keypair, **over))


async def test_rejects_wrong_signature_and_hs256(keypair):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(UnauthorizedError):
        await _verifier(keypair).verify(_tok(other))
    hs = jwt.encode({"sub": "1"}, "k" * 40, algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(UnauthorizedError):
        await _verifier(keypair).verify(hs)
