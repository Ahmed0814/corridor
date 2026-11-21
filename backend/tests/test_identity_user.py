from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from corridor.identity.models import User


@pytest.mark.django_db
def test_tenant_users_have_no_usable_password() -> None:
    user = User.objects.create_user(email="Ops@Example.com")
    assert not user.has_usable_password()
    assert user.email == "Ops@example.com"  # domain normalised


@pytest.mark.django_db
def test_driver_can_be_created_with_phone_only() -> None:
    user = User.objects.create_user(phone_e164="+25377123456")
    assert user.pk is not None


@pytest.mark.django_db
def test_user_needs_email_or_phone() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user()
