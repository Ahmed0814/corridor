from django.urls import path

from corridor.realtime.consumers import PingConsumer, TrackingConsumer

websocket_urlpatterns = [
    # Unauthenticated liveness check for the realtime process. Carries no data.
    path("ws/v1/ping/", PingConsumer.as_asgi()),
    # Authenticated, tenant-scoped topics (auth in the first message, never in the URL).
    path("ws/v1/tracking/", TrackingConsumer.as_asgi()),
]
