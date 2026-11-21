"""Access-token verification (D-006): only well-formed Cognito access tokens from an allowed
client are accepted. Every rejection is a 401 with the standard error envelope."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings

from corridor.identity.local_issuer import issue_access_token, local_sub
from corridor.identity.permissions import ClientKind
from tests.support import ApiClient, World, token_for

pytestmark = pytest.mark.django_db

DISPATCHER = "dispatcher@alpha.test"


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": local_sub(DISPATCHER),
        "iss": settings.COGNITO_ISSUER,
        "client_id": settings.COGNITO_CLIENT_IDS["web-office"],
        "token_use": "access",
        "iat": now,
        "auth_time": now,
        "exp": now + 600,
        "origin_jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _foreign_key_token(**overrides: object) -> str:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return jwt.encode(_claims(**overrides), other, algorithm="RS256")


def _assert_401(status: int, body: dict[str, object]) -> None:
    assert status == 401
    assert body["error"]["code"] == "unauthenticated"  # type: ignore[index]


def test_valid_token_is_accepted(world: World) -> None:
    status, body = ApiClient(token_for(DISPATCHER)).get("/me")
    assert status == 200, body
    assert body["active_tenant"]["tenant_slug"] == "alpha"


def test_missing_authorization_header() -> None:
    _assert_401(*ApiClient(None).get("/me"))


@pytest.mark.parametrize("raw", ["not-a-jwt", "a.b.c", ""])
def test_malformed_token(world: World, raw: str) -> None:
    client = ApiClient(None)
    _assert_401(*client.request("GET", "/me", headers={"Authorization": f"Bearer {raw}"}))


def test_token_signed_by_another_key(world: World) -> None:
    _assert_401(*ApiClient(_foreign_key_token()).get("/me"))


def test_hs256_token_using_public_material_is_rejected(world: World) -> None:
    token = jwt.encode(_claims(), "a-guessed-shared-secret-that-is-32-bytes-long", algorithm="HS256")
    _assert_401(*ApiClient(token).get("/me"))


def test_unsigned_token_is_rejected(world: World) -> None:
    token = jwt.encode(_claims(), key="", algorithm="none")
    _assert_401(*ApiClient(token).get("/me"))


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "https://cognito-idp.me-central-1.amazonaws.com/other-pool"},
        {"token_use": "id"},
        {"client_id": "some-other-app"},
        {"exp": int(time.time()) - 3600},
        {"origin_jti": None, "auth_time": None},
        {"sub": None},
        {"sub": 12345},
    ],
    ids=["wrong-issuer", "id-token", "unknown-client", "expired", "no-session-marker", "null-sub", "int-sub"],
)
def test_claim_checks(world: World, override: dict[str, object]) -> None:
    # Signed with the real local key, so only the claim under test is wrong.
    token = issue_access_token(local_sub(DISPATCHER), ClientKind.WEB_OFFICE, extra=override)
    _assert_401(*ApiClient(token).get("/me"))


def test_empty_sub_is_rejected(world: World) -> None:
    _assert_401(*ApiClient(issue_access_token("", ClientKind.WEB_OFFICE)).get("/me"))


def test_expiry_leeway_is_bounded(world: World) -> None:
    # 30 s past expiry is within the 60 s leeway; 120 s is not.
    ok = issue_access_token(
        local_sub(DISPATCHER), ClientKind.WEB_OFFICE, ttl=600, issued_at=int(time.time()) - 630
    )
    assert ApiClient(ok).get("/me")[0] == 200
    late = issue_access_token(
        local_sub(DISPATCHER), ClientKind.WEB_OFFICE, ttl=600, issued_at=int(time.time()) - 720
    )
    _assert_401(*ApiClient(late).get("/me"))


def test_valid_token_for_unknown_user_has_no_access(world: World) -> None:
    status, body = ApiClient(token_for("stranger@nowhere.test")).get("/me")
    assert status == 403
    assert body["error"]["code"] == "no_access"


def test_error_envelope_carries_request_id(world: World) -> None:
    client = ApiClient(_foreign_key_token())
    status, body = client.request("GET", "/me", headers={"X-Request-ID": "auth-test-0001"})
    assert status == 401
    assert body["error"]["request_id"] == "auth-test-0001"
