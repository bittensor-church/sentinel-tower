from django.contrib import admin
from django.contrib.admin import register

from project.core.models import Extrinsic, IngestionCheckpoint

admin.site.site_header = "project Administration"
admin.site.site_title = "project"
admin.site.index_title = "Welcome to project Administration"


@register(Extrinsic)
class ExtrinsicAdmin(admin.ModelAdmin):
    list_display = ["block_number", "extrinsic_index", "call_module", "call_function", "netuid", "success", "address"]
    list_filter = ["call_module", "call_function", "success", "netuid"]
    search_fields = ["extrinsic_hash", "address", "call_function"]
    ordering = ["-block_number", "-extrinsic_index"]
    readonly_fields = ["created_at"]


@register(IngestionCheckpoint)
class IngestionCheckpointAdmin(admin.ModelAdmin):
    list_display = ["file_path", "last_processed_line", "updated_at"]
    search_fields = ["file_path"]
    readonly_fields = ["updated_at"]
