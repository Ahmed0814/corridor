"""Operator command: create a company and invite its owner (platform path, audited).

    python manage.py create_tenant --slug acme --name "Acme Logistics" \
        --owner-email owner@acme.example --reason "pilot onboarding ticket OPS-12"

Uses the PLATFORM_DATABASE_URL role. With Cognito configured this creates the owner in the
user pool, which sends them an invitation email: needs approval with real addresses.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from corridor.core.platform import PlatformActor
from corridor.identity.services import platform_create_tenant


class Command(BaseCommand):
    help = "Create a tenant and invite its owner (audited platform action)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-name", default="")
        parser.add_argument("--reason", required=True, help="Why (ticket id); stored in the audit log")
        parser.add_argument("--demo", action="store_true", help="Flag the tenant as demo data")

    def handle(self, *args: Any, **opts: Any) -> None:
        out = platform_create_tenant(
            PlatformActor(user_id=None, reason=opts["reason"]),
            slug=opts["slug"],
            name=opts["name"],
            owner_email=opts["owner_email"],
            owner_display_name=opts["owner_name"],
            is_demo=opts["demo"],
        )
        self.stdout.write(f"created tenant {out.slug} ({out.id}); owner membership {out.owner_membership_id}")
