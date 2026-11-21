"""Deployed environments must refuse insecure or missing configuration (hard rule 6)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _import_settings(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    stripped = ("DJANGO_", "DATABASE_URL", "PLATFORM_", "AUTH_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(stripped)}
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
def test_missing_secret_key_is_fatal(django_env: str) -> None:
    result = _import_settings({"DJANGO_ENV": django_env, "DATABASE_URL": "postgis://u:p@db/x"})
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_missing_database_url_is_fatal_in_production() -> None:
    result = _import_settings({"DJANGO_ENV": "production", "DJANGO_SECRET_KEY": "x" * 50})
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_debug_is_refused_in_production() -> None:
    result = _import_settings(
        {
            "DJANGO_ENV": "production",
            "DJANGO_SECRET_KEY": "x" * 50,
            "DATABASE_URL": "postgis://u:p@db/x",
            "PLATFORM_DATABASE_URL": "postgis://u:p@db/x",
            "DJANGO_DEBUG": "true",
        }
    )
    assert result.returncode != 0
    assert "DEBUG must be off" in result.stderr


def test_invalid_environment_name_is_fatal() -> None:
    result = _import_settings({"DJANGO_ENV": "prod"})
    assert result.returncode != 0
    assert "Invalid DJANGO_ENV" in result.stderr
