"""Corridor settings.

One settings module driven by environment variables (12-factor). DJANGO_ENV selects safety
defaults: development | test | staging | production. Secrets are never defaulted outside
development/test (hard rule 6).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import django_stubs_ext
import environ

from corridor.core.logging import configure_logging

django_stubs_ext.monkeypatch()  # allows generic annotations such as ModelAdmin[User] at runtime

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
if os.environ.get("DJANGO_ENV", "development") in {"development", "test"}:
    # Optional local convenience file (git-ignored). Never read in staging/production.
    environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DJANGO_ENV: str = env.str("DJANGO_ENV", default="development")
if DJANGO_ENV not in {"development", "test", "staging", "production"}:
    raise RuntimeError(f"Invalid DJANGO_ENV={DJANGO_ENV!r}")
IS_LOCAL = DJANGO_ENV in {"development", "test"}

# --------------------------------------------------------------------------- core
if IS_LOCAL:
    SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="local-dev-only-insecure-key-not-for-deployment")
else:
    SECRET_KEY = env.str("DJANGO_SECRET_KEY")  # required: raises if missing
DEBUG = env.bool("DJANGO_DEBUG", default=DJANGO_ENV == "development")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "api", "realtime"])

INSTALLED_APPS = [
    "daphne",  # must precede staticfiles so `runserver` serves ASGI/Channels
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "channels",
    # Platform layer
    "corridor.core",
    "corridor.tenants",
    "corridor.identity",
    "corridor.audit",
    "corridor.events",
    # Logistics domain
    "corridor.customers",
    "corridor.containers",
    "corridor.shipments",
    "corridor.fleet",
    "corridor.drivers",
    "corridor.dispatch",
    "corridor.trips",
    "corridor.delivery",
    "corridor.documents",
    # Tracking
    "corridor.tracking",
    "corridor.geofencing",
    "corridor.realtime",
    "corridor.notifications",
]

MIDDLEWARE = [
    "corridor.core.middleware.request_id_middleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corridor.core.middleware.access_log_middleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
AUTH_USER_MODEL = "identity.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- database
# PostGIS. Roles (D-007): DATABASE_URL is the runtime role corridor_app (no table ownership, no
# BYPASSRLS). `manage.py migrate` runs with DATABASE_URL pointing at corridor_migrator instead.
# PLATFORM_DATABASE_URL is the audited Super Admin path (corridor.core.platform). Every request
# runs in a transaction (ATOMIC_REQUESTS) so authentication can SET LOCAL the tenant context.
_LOCAL_DB = "postgis://{role}:{role}_local@localhost:5432/corridor"  # local-only placeholders
if IS_LOCAL:
    DATABASES = {
        "default": env.db_url("DATABASE_URL", default=_LOCAL_DB.format(role="corridor_app")),
        "platform": env.db_url("PLATFORM_DATABASE_URL", default=_LOCAL_DB.format(role="corridor_platform")),
        # Outbox relay (D-051): cross-tenant read of outbox_events only, via its own RLS policy.
        "relay": env.db_url("RELAY_DATABASE_URL", default=_LOCAL_DB.format(role="corridor_relay")),
    }
    # Used only by the test runner to create the test database and run migrations.
    MIGRATOR_DATABASE_URL: str = env.str(
        "MIGRATOR_DATABASE_URL", default=_LOCAL_DB.format(role="corridor_migrator")
    )
else:
    DATABASES = {
        "default": env.db_url("DATABASE_URL"),
        "platform": env.db_url("PLATFORM_DATABASE_URL"),
        "relay": env.db_url("RELAY_DATABASE_URL"),
    }
for _alias, _cfg in DATABASES.items():
    _cfg["ENGINE"] = "django.contrib.gis.db.backends.postgis"
    _cfg["ATOMIC_REQUESTS"] = _alias == "default"
    # Tests: close connections after use, so worker threads (Channels) never hold the test
    # database open at teardown.
    _cfg["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0 if DJANGO_ENV == "test" else 60)
    _cfg["CONN_HEALTH_CHECKS"] = True
DATABASE_ROUTERS = ["corridor.core.platform.DefaultOnlyRouter"]

# --------------------------------------------------------------------------- GPS retention (D-058)
GPS_RETENTION_MONTHS: int = env.int("GPS_RETENTION_MONTHS", default=12)
# Dropping archived partitions deletes data: off unless explicitly enabled (approval, MASTER_PROMPT §0.3).
GPS_RETENTION_DROP_ENABLED: bool = env.bool("GPS_RETENTION_DROP_ENABLED", default=False)
GPS_ARCHIVE_BACKEND: str = env.str("GPS_ARCHIVE_BACKEND", default="local" if IS_LOCAL else "s3")
GPS_ARCHIVE_DIR: str = env.str("GPS_ARCHIVE_DIR", default=str(BASE_DIR / ".gps-archive"))

# --------------------------------------------------------------------------- field encryption
# Application-level encryption of sensitive fields such as driver license numbers (D-019).
# Comma-separated Fernet keys, newest first (rotation: prepend a new key, re-encrypt, drop old).
if IS_LOCAL:
    FIELD_ENCRYPTION_KEYS: list[str] = env.list(
        "FIELD_ENCRYPTION_KEYS",
        default=["bG9jYWwtZGV2LW9ubHktZmVybmV0LWtleS0wMDAwMDA="],  # local-only placeholder
    )
else:
    FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")  # required: from Secrets Manager
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# GeoDjango native libraries (only needed when not on the system path, e.g. Windows dev).
GDAL_LIBRARY_PATH = env.str("GDAL_LIBRARY_PATH", default=None)
GEOS_LIBRARY_PATH = env.str("GEOS_LIBRARY_PATH", default=None)
if sys.platform == "win32" and GDAL_LIBRARY_PATH:  # sys.platform so mypy narrows per OS
    # Python on Windows ignores PATH for dependent DLLs; register the bundle directory.
    os.add_dll_directory(str(Path(GDAL_LIBRARY_PATH).parent))

# --------------------------------------------------------------------------- redis / channels
REDIS_URL: str = env.str("REDIS_URL", default="redis://localhost:6379/0")
CHANNEL_LAYERS: dict[str, dict[str, Any]]
if DJANGO_ENV == "test":
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL], "prefix": "corridor"},
        }
    }

# --------------------------------------------------------------------------- celery (D-009, D-031)
CELERY_BROKER_URL: str = env.str("CELERY_BROKER_URL", default="sqs://")
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "region": env.str("AWS_REGION", default="me-central-1"),
    "visibility_timeout": 900,
    "polling_interval": 1,
    "wait_time_seconds": 10,
    "queue_name_prefix": env.str("SQS_QUEUE_PREFIX", default=f"corridor-{DJANGO_ENV}-"),
    # Locally the broker URL points at ElasticMQ (sqs://x:x@elasticmq:9324) over plain HTTP.
    "is_secure": env.bool("SQS_IS_SECURE", default=not IS_LOCAL),
}
CELERY_TASK_ALWAYS_EAGER = DJANGO_ENV == "test"
CELERY_TASK_EAGER_PROPAGATES = True

# --------------------------------------------------------------------------- identity (D-006)
# Amazon Cognito validates who the user is; tenant_memberships decides what they may do.
# COGNITO_ISSUER: https://cognito-idp.<region>.amazonaws.com/<user pool id>
# COGNITO_CLIENT_IDS: "web-office=<id>,web-portal=<id>,driver-mobile=<id>"
# Locally (development/test only) a built-in issuer signs Cognito-shaped tokens (D-006); a
# system check refuses it anywhere else.
AUTH_ISSUER_MODE: str = env.str("AUTH_ISSUER_MODE", default="local" if IS_LOCAL else "cognito")
if AUTH_ISSUER_MODE not in {"local", "cognito"}:
    raise RuntimeError(f"Invalid AUTH_ISSUER_MODE={AUTH_ISSUER_MODE!r}")
if AUTH_ISSUER_MODE == "local" and not IS_LOCAL:
    raise RuntimeError("AUTH_ISSUER_MODE=local is only allowed in development/test")
LOCAL_ISSUER = "http://localhost:8000/dev-auth"
COGNITO_ISSUER: str = env.str("COGNITO_ISSUER", default=LOCAL_ISSUER if AUTH_ISSUER_MODE == "local" else "")
COGNITO_CLIENT_IDS: dict[str, str] = {
    kind: client_id
    for kind, client_id in (
        item.split("=", 1)
        for item in env.list(
            "COGNITO_CLIENT_IDS",
            default=(
                [
                    "web-office=local-web-office",
                    "web-portal=local-web-portal",
                    "driver-mobile=local-driver-mobile",
                ]
                if AUTH_ISSUER_MODE == "local"
                else []
            ),
        )
    )
}
COGNITO_USER_POOL_ID: str = env.str("COGNITO_USER_POOL_ID", default="")
COGNITO_REGION: str = env.str("COGNITO_REGION", default=env.str("AWS_REGION", default="me-central-1"))
AUTH_JWKS_CACHE_SECONDS: int = env.int("AUTH_JWKS_CACHE_SECONDS", default=3600)
AUTH_LEEWAY_SECONDS = 60
# Private key of the local issuer (generated on first use, git-ignored).
LOCAL_ISSUER_KEY_FILE: str = env.str(
    "LOCAL_ISSUER_KEY_FILE", default=str(BASE_DIR / ".devauth" / "issuer_key.pem")
)
# Browser origins allowed to open WebSockets (non-browser clients send no Origin).
WEB_ALLOWED_ORIGINS: list[str] = env.list("WEB_ALLOWED_ORIGINS", default=["http://localhost:3000"])

# --------------------------------------------------------------------------- i18n / time
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("fr", "Français")]
TIME_ZONE = "UTC"  # store UTC; display EAT in clients (D-020)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if IS_LOCAL:  # serve straight from app directories; collectstatic runs only in the image
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = True
if DJANGO_ENV == "test":  # no collectstatic manifest in tests
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# --------------------------------------------------------------------------- security
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not IS_LOCAL:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz/"]  # ALB health checks hit the task over HTTP
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    if DEBUG:
        raise RuntimeError("DEBUG must be off outside development/test")

# --------------------------------------------------------------------------- logging / sentry
LOG_LEVEL: str = env.str("LOG_LEVEL", default="INFO")
LOG_FORMAT: str = env.str("LOG_FORMAT", default="console" if DJANGO_ENV == "development" else "json")
LOGGING_CONFIG = None  # we configure logging ourselves (structlog + stdlib bridge)
configure_logging(level=LOG_LEVEL, fmt=LOG_FORMAT)

SENTRY_DSN: str | None = env.str("SENTRY_DSN", default=None)
RELEASE: str = env.str("RELEASE", default="dev")
if SENTRY_DSN:
    from corridor.core.sentry import init_sentry

    init_sentry(dsn=SENTRY_DSN, environment=DJANGO_ENV, release=RELEASE)
