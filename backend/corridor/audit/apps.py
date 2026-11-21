from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "corridor.audit"
    label = "audit"
    default_auto_field = "django.db.models.BigAutoField"
