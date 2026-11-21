from django.conf import settings
from django.urls import URLPattern, URLResolver, path

from config.api_routes import api
from corridor.core import health

urlpatterns: list[URLPattern | URLResolver] = [
    path("healthz/live", health.live, name="health-live"),
    path("healthz/ready", health.ready, name="health-ready"),
    path("api/v1/", api.urls),
]

if settings.AUTH_ISSUER_MODE == "local":
    # Development/test stand-in for Cognito (D-006). Settings refuse this mode elsewhere.
    from corridor.identity import local_issuer

    urlpatterns += [
        path("dev-auth/authorize", local_issuer.authorize, name="dev-auth-authorize"),
        path("dev-auth/token", local_issuer.token, name="dev-auth-token"),
        path("dev-auth/logout", local_issuer.logout, name="dev-auth-logout"),
        path("dev-auth/.well-known/jwks.json", local_issuer.jwks_view, name="dev-auth-jwks"),
    ]

if settings.DJANGO_ENV == "development":
    # Django admin: local tooling only (D-043). Tenant data is behind RLS, so it cannot browse
    # tenants anyway; platform administration uses the audited /api/v1/platform API.
    from django.contrib import admin

    urlpatterns += [path("platform-admin/", admin.site.urls)]
