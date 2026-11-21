from django.contrib import admin

from corridor.identity.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin[User]):
    """Internal platform tooling only. Never exposed to tenant users."""

    list_display = ("id", "email", "phone_e164", "display_name", "is_platform_admin", "is_active")
    search_fields = ("email", "phone_e164", "display_name", "cognito_sub")
    readonly_fields = ("id", "cognito_sub", "created_at", "updated_at", "mfa_verified_at", "last_login")
    exclude = ("password",)
