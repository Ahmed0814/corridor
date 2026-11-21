from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from corridor.core.platform import PLATFORM_DB, PlatformActor, platform_session
from corridor.identity.models import User
from tests.support import World


@pytest.mark.django_db(databases=["default", "platform"])
def test_tenant_users_have_no_usable_password(world: World) -> None:
    with platform_session(PlatformActor(None, "test")):
        user = User.objects.using(PLATFORM_DB).get(id=world.m("alpha_admin").user_id)
        assert not user.has_usable_password()


@pytest.mark.django_db(databases=["default", "platform"])
def test_driver_exists_with_phone_only(world: World) -> None:
    with platform_session(PlatformActor(None, "test")):
        user = User.objects.using(PLATFORM_DB).get(id=world.m("alpha_driver").user_id)
        assert user.email is None and user.phone_e164 == "+25377000001"


@pytest.mark.django_db(databases=["default", "platform"])
def test_user_needs_email_or_phone() -> None:
    with (
        platform_session(PlatformActor(None, "test")),
        pytest.raises(IntegrityError),
        transaction.atomic(using=PLATFORM_DB),
    ):
        User(cognito_sub="x-no-identifier").save(using=PLATFORM_DB)
