"""Local development issuer of Cognito-shaped access tokens (D-006). development/test ONLY.

It lets the web app and the driver app run the real OAuth 2.0 authorization-code + PKCE flow on
a laptop without Cognito credentials, and lets tests mint tokens. The API verifies these tokens
with the same TokenVerifier as Cognito tokens; only the key source differs.

Settings refuse AUTH_ISSUER_MODE=local outside development/test, and the URLs are only mounted
in that mode. There is no password: whoever reaches this page can pick any identity, which is
exactly why it must never run in a deployed environment.

Users are matched by their Cognito ``sub``. Locally that sub is derived from the email or phone
number (``local_sub``), and LocalIdentityProvider uses the same derivation when it "creates" a
user, so an invited user can log in here with the address they were invited with.
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from corridor.identity.permissions import ClientKind

_NAMESPACE = uuid.UUID("6f1d3f0e-5a7c-4c1e-9a55-0c0b2b9a3c11")
ACCESS_TTL = 3600
CODE_TTL = 120
REFRESH_TTL = 30 * 24 * 3600
_CODE_SALT = "corridor.local_issuer.code"
_REFRESH_SALT = "corridor.local_issuer.refresh"

# Redirect URIs accepted per client kind (exact match).
REDIRECT_URIS: dict[ClientKind, tuple[str, ...]] = {
    ClientKind.WEB_OFFICE: ("http://localhost:3000/auth/callback",),
    ClientKind.WEB_PORTAL: ("http://localhost:3000/auth/callback",),
    ClientKind.DRIVER_MOBILE: ("corridor-driver://auth/callback",),
}


class _ClientRedirect(HttpResponseRedirect):
    """Redirect back to a registered client. Django only allows http/https/ftp by default, which
    would block the driver app's custom scheme. Safe: the target always exactly matches
    REDIRECT_URIS before this is used."""

    allowed_schemes = ["http", "https", "corridor-driver"]


def _assert_local() -> None:
    if settings.AUTH_ISSUER_MODE != "local" or settings.DJANGO_ENV not in {"development", "test"}:
        raise RuntimeError("The local issuer is disabled outside development/test.")


def local_sub(identifier: str) -> str:
    return f"local-{uuid.uuid5(_NAMESPACE, identifier.strip().lower())}"


# --------------------------------------------------------------------------- keys


def _load_or_create_key(path: Path) -> rsa.RSAPrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise RuntimeError(f"{path} is not an RSA private key")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    # Atomic create: concurrent processes either win the rename or read the winner's file.
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    try:
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        os.unlink(tmp)
    return _load_or_create_key(path)


@lru_cache(maxsize=1)
def _private_key() -> rsa.RSAPrivateKey:
    _assert_local()
    return _load_or_create_key(Path(settings.LOCAL_ISSUER_KEY_FILE))


def _kid(key: rsa.RSAPrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()[:16]


class LocalKeySource:
    def key_for(self, token: str) -> Any:
        return _private_key().public_key()


def jwks() -> dict[str, Any]:
    key = _private_key()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"kid": _kid(key), "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


# --------------------------------------------------------------------------- tokens


def issue_access_token(
    sub: str,
    client_kind: ClientKind = ClientKind.WEB_OFFICE,
    *,
    session_ref: str | None = None,
    mfa: bool = False,
    ttl: int = ACCESS_TTL,
    extra: dict[str, Any] | None = None,
    issued_at: int | None = None,
) -> str:
    _assert_local()
    iat = issued_at if issued_at is not None else int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": settings.COGNITO_ISSUER,
        "client_id": settings.COGNITO_CLIENT_IDS[client_kind.value],
        "token_use": "access",
        "scope": "openid",
        "auth_time": iat,
        "iat": iat,
        "exp": iat + ttl,
        "jti": str(uuid.uuid4()),
        "origin_jti": session_ref or str(uuid.uuid4()),
        "username": sub,
        "dev_mfa": mfa,  # local stand-in for Cognito's TOTP status (read by LocalIdentityProvider)
    }
    if extra:
        claims.update(extra)
    key = _private_key()
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": _kid(key)})


def _client_kind_for(client_id: str) -> ClientKind | None:
    for kind, cid in settings.COGNITO_CLIENT_IDS.items():
        if cid == client_id:
            return ClientKind(kind)
    return None


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


# --------------------------------------------------------------------------- OAuth endpoints

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Corridor local sign-in (development only)</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem}}
label{{display:block;margin:.75rem 0 .25rem}}input[type=text]{{width:100%;padding:.5rem}}
.warn{{background:#fff4ce;border:1px solid #c9a400;padding:.75rem;border-radius:.375rem}}
button{{margin-top:1rem;padding:.5rem 1rem}}</style></head><body>
<h1>Local sign-in</h1>
<p class="warn"><strong>Development only.</strong> This page stands in for Amazon Cognito.
It has no password check and is disabled in staging and production.</p>
<p>Client: <code>{client}</code></p>
<form method="post">{hidden}
<label for="identifier">Email or phone number (E.164)</label>
<input type="text" id="identifier" name="identifier" required autocomplete="username">
<label><input type="checkbox" name="mfa" value="1"> TOTP MFA enrolled</label>
<button type="submit">Sign in</button></form></body></html>"""

_AUTHZ_PARAMS = (
    "client_id",
    "redirect_uri",
    "state",
    "code_challenge",
    "code_challenge_method",
    "response_type",
)


@transaction.non_atomic_requests  # no database access (D-040)
@csrf_exempt
@require_http_methods(["GET", "POST"])
def authorize(request: HttpRequest) -> HttpResponse:
    _assert_local()
    params = request.GET if request.method == "GET" else request.POST
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    kind = _client_kind_for(client_id)
    if kind is None or redirect_uri not in REDIRECT_URIS[kind]:
        return HttpResponseBadRequest("unknown client_id or redirect_uri")
    if params.get("response_type") != "code" or params.get("code_challenge_method") != "S256":
        return HttpResponseBadRequest("only response_type=code with PKCE S256 is supported")
    if not params.get("code_challenge"):
        return HttpResponseBadRequest("code_challenge required")

    if request.method == "GET":
        hidden = "".join(
            f'<input type="hidden" name="{name}" value="{html.escape(params.get(name, ""))}">'
            for name in _AUTHZ_PARAMS
        )
        return HttpResponse(_PAGE.format(client=html.escape(kind.value), hidden=hidden))

    identifier = params.get("identifier", "").strip()
    if not identifier:
        return HttpResponseBadRequest("identifier required")
    code = signing.dumps(
        {
            "sub": local_sub(identifier),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "challenge": params["code_challenge"],
            "mfa": params.get("mfa") == "1",
        },
        salt=_CODE_SALT,
    )
    query = urlencode({"code": code, "state": params.get("state", "")})
    return _ClientRedirect(f"{redirect_uri}?{query}")


def _token_error(error: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": error}, status=status)


@transaction.non_atomic_requests  # no database access (D-040)
@csrf_exempt
@require_http_methods(["POST"])
def token(request: HttpRequest) -> JsonResponse:
    _assert_local()
    grant_type = request.POST.get("grant_type")
    client_id = request.POST.get("client_id", "")
    kind = _client_kind_for(client_id)
    if kind is None:
        return _token_error("invalid_client", 401)

    if grant_type == "authorization_code":
        try:
            data = signing.loads(request.POST.get("code", ""), salt=_CODE_SALT, max_age=CODE_TTL)
        except signing.BadSignature:
            return _token_error("invalid_grant")
        if data["client_id"] != client_id or data["redirect_uri"] != request.POST.get("redirect_uri"):
            return _token_error("invalid_grant")
        if _s256(request.POST.get("code_verifier", "")) != data["challenge"]:
            return _token_error("invalid_grant")
        session_ref = str(uuid.uuid4())
        sub, mfa = data["sub"], bool(data["mfa"])
    elif grant_type == "refresh_token":
        try:
            data = signing.loads(
                request.POST.get("refresh_token", ""), salt=_REFRESH_SALT, max_age=REFRESH_TTL
            )
        except signing.BadSignature:
            return _token_error("invalid_grant")
        if data["client_id"] != client_id:
            return _token_error("invalid_grant")
        session_ref, sub, mfa = data["session_ref"], data["sub"], bool(data["mfa"])
    else:
        return _token_error("unsupported_grant_type")

    refresh = signing.dumps(
        {"sub": sub, "client_id": client_id, "session_ref": session_ref, "mfa": mfa}, salt=_REFRESH_SALT
    )
    return JsonResponse(
        {
            "access_token": issue_access_token(sub, kind, session_ref=session_ref, mfa=mfa),
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL,
        }
    )


@transaction.non_atomic_requests  # no database access (D-040)
@require_http_methods(["GET"])
def jwks_view(request: HttpRequest) -> JsonResponse:
    _assert_local()
    return JsonResponse(jwks())


@transaction.non_atomic_requests  # no database access (D-040)
@csrf_exempt
@require_http_methods(["GET", "POST"])
def logout(request: HttpRequest) -> HttpResponse:
    """Mirrors Cognito's /logout: stateless locally, so just redirect back."""
    _assert_local()
    target = request.GET.get("logout_uri") or "http://localhost:3000/"
    allowed = {uri.rsplit("/auth/", 1)[0] + "/" for uris in REDIRECT_URIS.values() for uri in uris}
    return HttpResponseRedirect(target if target in allowed else "http://localhost:3000/")
