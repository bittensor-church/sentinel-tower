from django.contrib import admin

from apps.extrinsics.models import Extrinsic


@admin.register(Extrinsic)
class ExtrinsicAdmin(admin.ModelAdmin):
    list_display = [
        "block_number",
        "extrinsic_index",
        "call_module",
        "call_function",
        "success",
        "address",
    ]
    list_filter = ["call_module", "success", "netuid"]
    search_fields = ["extrinsic_hash", "address", "call_function"]
    readonly_fields = [
        "block_number",
        "block_hash",
        "extrinsic_hash",
        "extrinsic_index",
        "block_timestamp",
        "call_module",
        "call_function",
        "call_args",
        "address",
        "signature",
        "nonce",
        "tip_rao",
        "status",
        "success",
        "error_data",
        "events",
        "netuid",
        "created_at",
    ]
    ordering = ["-block_number", "-extrinsic_index"]
