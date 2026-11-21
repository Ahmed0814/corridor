from django.contrib import admin
from django.urls import path

from corridor.core import health
from corridor.core.api import api

# Django admin is for internal platform tools only, never for tenant users (MASTER_PROMPT §3).
urlpatterns = [
    path("healthz/live", health.live, name="health-live"),
    path("healthz/ready", health.ready, name="health-ready"),
    path("api/v1/", api.urls),
    path("platform-admin/", admin.site.urls),
]
