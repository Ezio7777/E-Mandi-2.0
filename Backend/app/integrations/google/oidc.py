"""Google ID-token verification: signature (JWKS), issuer, audience, expiry, verified email."""
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import jwt

from app.core.errors import AppError, ProviderError, UnauthorizedError
from app.core.logging import get_logger

log = get_logger(__name__)
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class GoogleNotConfigured(AppError):
    status_code, code, message = 503, "google_not_configured", "Google login is not configured"


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


class GoogleIdentityVerifier(Protocol):
    async def verify(self, credential: str) -> GoogleIdentity: ...


class GoogleOIDCVerifier:
    def __init__(self, client_id: str, *, jwks_ttl: int = 3600, http: httpx.AsyncClient | None = None) -> None:
        self.client_id = client_id
        self.jwks_ttl = jwks_ttl
        self._http = http
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at = 0.0

    async def _refresh_keys(self) -> None:
        try:
            client = self._http or httpx.AsyncClient(timeout=5.0)
            try:
                resp = await client.get(GOOGLE_JWKS_URL)
                resp.raise_for_status()
            finally:
                if self._http is None:
                    await client.aclose()
            self._keys = {k["kid"]: k for k in resp.json()["keys"]}
            self._fetched_at = time.monotonic()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.error("google_jwks_fetch_failed", error=str(exc))
            raise ProviderError("Could not verify Google credential right now") from exc

    async def _key_for(self, kid: str) -> Any:
        if not self._keys or time.monotonic() - self._fetched_at > self.jwks_ttl:
            await self._refresh_keys()
        if kid not in self._keys:  # key rotation: one forced refresh
            await self._refresh_keys()
        if kid not in self._keys:
            raise UnauthorizedError("Invalid Google credential")
        return jwt.PyJWK.from_dict(self._keys[kid]).key

    async def verify(self, credential: str) -> GoogleIdentity:
        if not self.client_id:
            raise GoogleNotConfigured()
        try:
            header = jwt.get_unverified_header(credential)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise UnauthorizedError("Invalid Google credential")
            key = await self._key_for(header["kid"])
            claims = jwt.decode(
                credential, key, algorithms=["RS256"], audience=self.client_id, issuer=GOOGLE_ISSUERS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=10)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid Google credential") from exc
        if not claims.get("email") or claims.get("email_verified") is not True:
            raise UnauthorizedError("Google account email is not verified")
        return GoogleIdentity(sub=claims["sub"], email=claims["email"].lower(), email_verified=True,
                              name=claims.get("name"), picture=claims.get("picture"))
