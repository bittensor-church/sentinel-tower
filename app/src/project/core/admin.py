from django.contrib import admin
from django.contrib.admin import register

from project.core.models import IngestionCheckpoint

admin.site.site_header = "project Administration"
admin.site.site_title = "project"
admin.site.index_title = "Welcome to project Administration"


@register(IngestionCheckpoint)
class IngestionCheckpointAdmin(admin.ModelAdmin):
    list_display = ["file_path", "last_processed_line", "updated_at"]
    search_fields = ["file_path"]
    readonly_fields = ["updated_at"]
