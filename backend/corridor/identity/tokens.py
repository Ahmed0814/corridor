"""Cognito access-token verification (D-006, security-model.md §2).

Checks: RS256 signature against the issuer's JWKS, ``iss``, ``token_use == "access"``,
``client_id`` in the configured allowlist (mapped to a ClientKind), ``exp`` (60 s leeway),
presence of ``sub``. The same code path verifies tokens from the local development issuer; only
the key source differs.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import jwt
from django.conf import settings

from corridor.identity.permissions import ClientKind


class InvalidToken(Exception):
    """The token is not acceptable. The message is for logs, never for the client."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    sub: str
    client_kind: ClientKind
    client_id: str
    session_ref: str  # origin_jti when present (stable across refreshes), else auth_time
    expires_at: int
    claims: dict[str, Any]


class KeySource(Protocol):
    def key_for(self, token: str) -> Any: ...


class JwksKeySource:
    """Cognito JWKS (https://<issuer>/.well-known/jwks.json), cached in-process."""

    def __init__(self, jwks_url: str, lifespan: int) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=lifespan, timeout=5)

    def key_for(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            raise InvalidToken(f"signing key not found: {exc}") from exc


class TokenVerifier:
    def __init__(self, issuer: str, client_ids: dict[str, str], keys: KeySource, leeway: int) -> None:
        if not issuer:
            raise RuntimeError("COGNITO_ISSUER is not configured")
        self.issuer = issuer
        self.keys = keys
        self.leeway = leeway
        self._client_kinds: dict[str, ClientKind] = {}
        for kind, client_id in client_ids.items():
            self._client_kinds[client_id] = ClientKind(kind)

    def verify(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"malformed token: {exc}") from exc
        if header.get("alg") != "RS256":
            raise InvalidToken(f"unexpected alg {header.get('alg')!r}")
        key = self.keys.key_for(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=self.leeway,
                options={
                    "require": ["exp", "iat", "iss", "sub", "client_id", "token_use"],
                    "verify_aud": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"rejected: {exc}") from exc
        if claims.get("token_use") != "access":
            raise InvalidToken("not an access token")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise InvalidToken("empty or non-string sub")
        client_id = str(claims["client_id"])
        kind = self._client_kinds.get(client_id)
        if kind is None:
            raise InvalidToken("client_id not allowed")
        session_ref = str(claims.get("origin_jti") or claims.get("auth_time") or "")
        if not session_ref:
            raise InvalidToken("no session marker (origin_jti/auth_time)")
        return VerifiedToken(
            sub=str(claims["sub"]),
            client_kind=kind,
            client_id=client_id,
            session_ref=session_ref,
            expires_at=int(claims["exp"]),
            claims=claims,
        )


_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_verifier() -> TokenVerifier:
    with _lock:
        keys: KeySource
        if settings.AUTH_ISSUER_MODE == "local":
            from corridor.identity.local_issuer import LocalKeySource

            keys = LocalKeySource()
        else:
            keys = JwksKeySource(
                f"{settings.COGNITO_ISSUER}/.well-known/jwks.json", settings.AUTH_JWKS_CACHE_SECONDS
            )
        return TokenVerifier(
            settings.COGNITO_ISSUER, settings.COGNITO_CLIENT_IDS, keys, settings.AUTH_LEEWAY_SECONDS
        )


def now() -> int:
    return int(time.time())
