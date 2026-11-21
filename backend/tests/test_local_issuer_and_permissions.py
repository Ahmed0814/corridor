"""The development issuer runs a real authorization-code + PKCE flow, is refused outside
development/test, and the permission matrix in code is mirrored exactly in the database."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client

from corridor.identity.local_issuer import local_sub
from corridor.identity.models import Permission, Role, RolePermission
from corridor.identity.permissions import PERMISSIONS, ROLES
from corridor.identity.tokens import get_verifier
from tests.support import ApiClient, World

BACKEND = Path(__file__).resolve().parent.parent
REDIRECT = "http://localhost:3000/auth/callback"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize(
    client: Client, identifier: str, challenge: str, *, mfa: bool = False, client_id: str = "local-web-office"
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-123",
    }
    page = client.get("/dev-auth/authorize", params)
    assert page.status_code == 200 and b"Development only" in page.content
    resp = client.post(
        "/dev-auth/authorize", {**params, "identifier": identifier, **({"mfa": "1"} if mfa else {})}
    )
    assert resp.status_code == 302
    location = urlparse(resp["Location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
    query = parse_qs(location.query)
    assert query["state"] == ["st-123"]
    return query["code"][0]


@pytest.mark.django_db
def test_authorization_code_flow_with_pkce(world: World) -> None:
    client = Client()
    verifier, challenge = _pkce()
    code = _authorize(client, "dispatcher@alpha.test", challenge)
    resp = client.post(
        "/dev-auth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "local-web-office",
            "redirect_uri": REDIRECT,
        },
    )
    assert resp.status_code == 200
    tokens = resp.json()
    verified = get_verifier().verify(tokens["access_token"])
    assert verified.sub == local_sub("dispatcher@alpha.test")
    assert ApiClient(tokens["access_token"]).get("/me")[0] == 200

    refreshed = client.post(
        "/dev-auth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": "local-web-office",
        },
    ).json()
    # Same Cognito session after a refresh: no second login audit row.
    assert get_verifier().verify(refreshed["access_token"]).session_ref == verified.session_ref


@pytest.mark.django_db
def test_driver_app_flow_redirects_into_the_app_scheme(world: World) -> None:
    """Regression: Django refused the corridor-driver:// redirect, so driver sign-in never completed."""
    client = Client()
    verifier, challenge = _pkce()
    redirect = "corridor-driver://auth/callback"
    resp = client.post(
        "/dev-auth/authorize",
        {
            "client_id": "local-driver-mobile",
            "redirect_uri": redirect,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st-drv",
            "identifier": "+25377000001",
        },
    )
    assert resp.status_code == 302
    location = resp["Location"]
    assert location.startswith(redirect + "?")
    code = parse_qs(urlparse(location).query)["code"][0]
    tokens = client.post(
        "/dev-auth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": "local-driver-mobile",
            "redirect_uri": redirect,
        },
    ).json()
    status, me = ApiClient(tokens["access_token"]).get("/me")
    assert status == 200
    assert me["client"] == "driver-mobile"
    assert me["active_tenant"]["role"] == "driver"


@pytest.mark.django_db
def test_wrong_verifier_or_client_is_rejected(world: World) -> None:
    client = Client()
    verifier, challenge = _pkce()
    code = _authorize(client, "dispatcher@alpha.test", challenge)
    base = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT}
    assert client.post(
        "/dev-auth/token", {**base, "code_verifier": "wrong", "client_id": "local-web-office"}
    ).json() == {"error": "invalid_grant"}
    assert client.post(
        "/dev-auth/token", {**base, "code_verifier": verifier, "client_id": "local-web-portal"}
    ).json() == {"error": "invalid_grant"}
    assert (
        client.post("/dev-auth/token", {**base, "code_verifier": verifier, "client_id": "nope"}).status_code
        == 401
    )


def test_authorize_rejects_unknown_redirects_and_plain_pkce() -> None:
    client = Client()
    _, challenge = _pkce()
    base = {"client_id": "local-web-office", "response_type": "code", "code_challenge": challenge}
    assert (
        client.get(
            "/dev-auth/authorize",
            {**base, "redirect_uri": "https://evil.example/cb", "code_challenge_method": "S256"},
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/dev-auth/authorize", {**base, "redirect_uri": REDIRECT, "code_challenge_method": "plain"}
        ).status_code
        == 400
    )
    # The driver app's redirect is not valid for the office client.
    assert (
        client.get(
            "/dev-auth/authorize",
            {**base, "redirect_uri": "corridor-driver://auth/callback", "code_challenge_method": "S256"},
        ).status_code
        == 400
    )


def test_jwks_is_published() -> None:
    keys = Client().get("/dev-auth/.well-known/jwks.json").json()["keys"]
    assert keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256" and "d" not in keys[0]


def _import_settings(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "DATABASE_URL", "AUTH_", "PLATFORM_"))
    }
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("django_env", ["staging", "production"])
def test_local_issuer_is_refused_in_deployed_environments(django_env: str) -> None:
    result = _import_settings(
        {
            "DJANGO_ENV": django_env,
            "DJANGO_SECRET_KEY": "x" * 50,
            "DATABASE_URL": "postgis://u:p@db/x",
            "PLATFORM_DATABASE_URL": "postgis://u:p@db/x",
            "RELAY_DATABASE_URL": "postgis://u:p@db/x",
            "FIELD_ENCRYPTION_KEYS": "dGVzdC1vbmx5LWZlcm5ldC1rZXktMDAwMDAwMDAwMDA=",
            "AUTH_ISSUER_MODE": "local",
        }
    )
    assert result.returncode != 0
    assert "AUTH_ISSUER_MODE=local is only allowed in development/test" in result.stderr


def test_deployed_environments_default_to_cognito() -> None:
    result = _import_settings(
        {
            "DJANGO_ENV": "production",
            "DJANGO_SECRET_KEY": "x" * 50,
            "DATABASE_URL": "postgis://u:p@db/x",
            "PLATFORM_DATABASE_URL": "postgis://u:p@db/x",
            "RELAY_DATABASE_URL": "postgis://u:p@db/x",
            "FIELD_ENCRYPTION_KEYS": "dGVzdC1vbmx5LWZlcm5ldC1rZXktMDAwMDAwMDAwMDA=",
        }
    )
    assert result.returncode == 0, result.stderr


def test_platform_database_url_is_required_in_production() -> None:
    result = _import_settings(
        {"DJANGO_ENV": "production", "DJANGO_SECRET_KEY": "x" * 50, "DATABASE_URL": "postgis://u:p@db/x"}
    )
    assert result.returncode != 0 and "PLATFORM_DATABASE_URL" in result.stderr


# --------------------------------------------------------------------------- permission matrix


@pytest.mark.django_db
def test_database_mirror_matches_the_code_matrix() -> None:
    assert dict(Permission.objects.values_list("code", "description")) == PERMISSIONS
    assert {r.code: (r.requires_mfa, r.scope) for r in Role.objects.all()} == {
        code: (role.requires_mfa, role.scope.value) for code, role in ROLES.items()
    }
    pairs = set(RolePermission.objects.values_list("role_id", "permission_id"))
    assert pairs == {(code, p) for code, role in ROLES.items() for p in role.permissions}


def test_privileged_roles_require_mfa() -> None:
    for role in ROLES.values():
        if role.permissions & {"users.manage", "roles.assign", "tenant.settings"}:
            assert role.requires_mfa, role.code
    assert {r.code for r in ROLES.values() if r.requires_mfa} == {"owner", "admin", "finance"}


def test_security_model_matrix_is_generated_from_code() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/gen_permission_matrix.py", "--check"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
