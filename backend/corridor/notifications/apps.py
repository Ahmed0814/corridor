from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "corridor.notifications"
    label = "notifications"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from corridor.events import services as events
        from corridor.notifications import services

        events.register_handler(services.TEMPLATES.keys(), services.handle_event)
