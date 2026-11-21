"""ASGI entry point shared by the `api` and `realtime` processes.

The ALB routes /api/* and /healthz/* to `api` and /ws/* to `realtime`; both can serve
either protocol, which keeps local development to a single command if desired.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()  # must run before importing consumers

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from corridor.realtime.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Origin and auth checks for real topics are added in Phase 2 (security-model.md §5).
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
