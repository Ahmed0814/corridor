"""Operator command: make a user a Platform Super Admin (audited).

    python manage.py grant_platform_admin --email ops@corridor.example --reason "ticket OPS-3"

The user still needs TOTP MFA in Cognito before any platform endpoint accepts them.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from corridor.core.platform import PlatformActor
from corridor.identity.services import platform_grant_admin


class Command(BaseCommand):
    help = "Grant the Platform Super Admin flag (audited platform action)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", default="")
        parser.add_argument("--reason", required=True)

    def handle(self, *args: Any, **opts: Any) -> None:
        user_id = platform_grant_admin(
            PlatformActor(user_id=None, reason=opts["reason"]), email=opts["email"], display_name=opts["name"]
        )
        self.stdout.write(f"platform admin granted to user {user_id}")
