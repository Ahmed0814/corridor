"""Identity provider interface (MASTER_PROMPT §0.5: interface + test adapter).

``CognitoIdentityProvider`` calls the Cognito admin API with the task's IAM role. It is NOT
live: it needs a user pool and credentials (PROGRESS.md "Needs credentials"). Creating a user in
Cognito sends an invitation email or SMS, so enabling it in any environment with real addresses
needs human approval (MASTER_PROMPT §0.3).

``LocalIdentityProvider`` is the development/test adapter. It talks to nothing and derives subs
the same way as the local issuer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings


class IdentityProviderError(Exception):
    pass


class IdentityProvider(Protocol):
    def ensure_user(self, *, email: str | None, phone_e164: str | None, display_name: str) -> str:
        """Create the user in the identity provider if needed and return their stable ``sub``."""
        ...

    def mfa_enabled(self, sub: str, token_claims: dict[str, Any]) -> bool:
        """True only if the provider confirms TOTP MFA is active for this user."""
        ...

    def global_sign_out(self, sub: str) -> None:
        """Revoke refresh tokens (used on suspension)."""
        ...


class LocalIdentityProvider:
    def __init__(self) -> None:
        if settings.DJANGO_ENV not in {"development", "test"}:
            raise RuntimeError("LocalIdentityProvider is for development/test only.")

    def ensure_user(self, *, email: str | None, phone_e164: str | None, display_name: str) -> str:
        from corridor.identity.local_issuer import local_sub

        identifier = email or phone_e164
        if not identifier:
            raise IdentityProviderError("email or phone required")
        return local_sub(identifier)

    def mfa_enabled(self, sub: str, token_claims: dict[str, Any]) -> bool:
        return token_claims.get("dev_mfa") is True

    def global_sign_out(self, sub: str) -> None:
        return None


class CognitoIdentityProvider:
    def __init__(self, user_pool_id: str, region: str) -> None:
        if not user_pool_id:
            raise RuntimeError("COGNITO_USER_POOL_ID is not configured")
        import boto3

        self.pool = user_pool_id
        self.client: Any = boto3.client("cognito-idp", region_name=region)

    def _sub_of(self, user: dict[str, Any]) -> str:
        attrs = user.get("Attributes") or user.get("UserAttributes") or []
        for attr in attrs:
            if attr["Name"] == "sub":
                return str(attr["Value"])
        raise IdentityProviderError("Cognito user has no sub")

    def ensure_user(self, *, email: str | None, phone_e164: str | None, display_name: str) -> str:
        username = email or phone_e164
        if not username:
            raise IdentityProviderError("email or phone required")
        attributes = [{"Name": "name", "Value": display_name or username}]
        if email:
            attributes += [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}]
        if phone_e164:
            attributes += [
                {"Name": "phone_number", "Value": phone_e164},
                {"Name": "phone_number_verified", "Value": "true"},
            ]
        try:
            created = self.client.admin_create_user(
                UserPoolId=self.pool,
                Username=username,
                UserAttributes=attributes,
                DesiredDeliveryMediums=["EMAIL"] if email else ["SMS"],
            )
            return self._sub_of(created["User"])
        except self.client.exceptions.UsernameExistsException:
            existing = self.client.admin_get_user(UserPoolId=self.pool, Username=username)
            return self._sub_of(existing)
        except Exception as exc:  # botocore ClientError and friends
            raise IdentityProviderError(str(exc)) from exc

    def mfa_enabled(self, sub: str, token_claims: dict[str, Any]) -> bool:
        username = str(token_claims.get("username") or sub)
        try:
            user = self.client.admin_get_user(UserPoolId=self.pool, Username=username)
        except Exception as exc:
            raise IdentityProviderError(str(exc)) from exc
        return "SOFTWARE_TOKEN_MFA" in (user.get("UserMFASettingList") or [])

    def global_sign_out(self, sub: str) -> None:
        try:
            self.client.admin_user_global_sign_out(UserPoolId=self.pool, Username=sub)
        except Exception as exc:
            raise IdentityProviderError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_provider() -> IdentityProvider:
    if settings.AUTH_ISSUER_MODE == "local":
        return LocalIdentityProvider()
    return CognitoIdentityProvider(settings.COGNITO_USER_POOL_ID, settings.COGNITO_REGION)
