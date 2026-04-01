from django.contrib import admin

from apps.notifications.models import SubnetWebhook


@admin.register(SubnetWebhook)
class SubnetWebhookAdmin(admin.ModelAdmin):
    list_display = ["netuid", "url", "enabled", "updated_at"]
    list_filter = ["enabled", "netuid"]
    search_fields = ["url"]
    list_editable = ["enabled"]
    ordering = ["netuid"]
