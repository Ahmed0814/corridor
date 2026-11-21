from __future__ import annotations

from unittest import mock

import pytest
from django.test import Client


def test_live_needs_no_dependencies() -> None:
    with mock.patch("corridor.core.health.check_database", side_effect=AssertionError("must not run")):
        response = Client().get("/healthz/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_ok_when_db_and_redis_up() -> None:
    with mock.patch("corridor.core.health.check_redis", return_value=True):
        response = Client().get("/healthz/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": True, "redis": True}}


@pytest.mark.django_db
def test_ready_503_when_redis_down() -> None:
    with mock.patch("corridor.core.health.check_redis", return_value=False):
        response = Client().get("/healthz/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "redis": False}


def test_ready_503_when_db_down() -> None:
    with (
        mock.patch("corridor.core.health.check_database", return_value=False),
        mock.patch("corridor.core.health.check_redis", return_value=True),
    ):
        response = Client().get("/healthz/ready")
    assert response.status_code == 503


@pytest.mark.django_db
def test_database_is_postgis() -> None:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT postgis_lib_version()")
        (version,) = cursor.fetchone()
    assert version.split(".")[0] == "3"


@pytest.mark.requires_redis
def test_redis_check_against_real_redis() -> None:
    from corridor.core.health import check_redis

    assert check_redis() is True
