from django.contrib import admin
from django.contrib.admin import register

from project.core.models import HyperparamEvent, IngestionCheckpoint, SetWeightsEvent

admin.site.site_header = "project Administration"
admin.site.site_title = "project"
admin.site.index_title = "Welcome to project Administration"


@register(HyperparamEvent)
class HyperparamEventAdmin(admin.ModelAdmin):
    list_display = ["block_number", "timestamp", "call_function", "netuid", "address", "status"]
    list_filter = ["call_function", "call_module", "status", "netuid"]
    search_fields = ["extrinsic_hash", "address", "call_function"]
    ordering = ["-block_number"]
    readonly_fields = ["timestamp", "created_at"]


@register(SetWeightsEvent)
class SetWeightsEventAdmin(admin.ModelAdmin):
    list_display = ["block_number", "timestamp", "netuid", "address", "status"]
    list_filter = ["netuid", "status"]
    search_fields = ["extrinsic_hash", "address"]
    ordering = ["-block_number"]
    readonly_fields = ["timestamp", "created_at"]


@register(IngestionCheckpoint)
class IngestionCheckpointAdmin(admin.ModelAdmin):
    list_display = ["file_path", "last_processed_line", "updated_at"]
    search_fields = ["file_path"]
    readonly_fields = ["updated_at"]
