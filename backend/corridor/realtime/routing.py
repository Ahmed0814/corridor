from django.urls import path

from corridor.realtime.consumers import PingConsumer

websocket_urlpatterns = [
    # Unauthenticated liveness check for the realtime process. Carries no data.
    # /ws/v1/tracking/ (authenticated, tenant-scoped) arrives in Phase 2/4.
    path("ws/v1/ping/", PingConsumer.as_asgi()),
]
