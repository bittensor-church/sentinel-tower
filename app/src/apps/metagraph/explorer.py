"""
Metagraph Explorer - Admin view for exploring metagraph data.

To remove this feature:
1. Delete this file (explorer.py)
2. Delete templates/admin/metagraph/explorer.html
3. Remove the import and registration from admin.py:
   - Remove: from .explorer import MetagraphExplorerAdmin, metagraph_explorer_site
   - Remove: admin.site.register(MetagraphExplorerAdmin) or similar registration
"""

from django.contrib import admin
from django.db.models import Max
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import path

from .models import Block, MechanismMetrics, NeuronSnapshot, Subnet


class MetagraphExplorerAdmin(admin.ModelAdmin):
    """
    Custom admin view for exploring metagraph data by subnet and block.
    """

    class Meta:
        app_label = "metagraph"

    def has_module_permission(self, request):
        return True

    def has_view_permission(self, request, obj=None):
        return True


class MetagraphExplorer:
    """
    Metagraph Explorer view handler.
    Provides subnet/block selection and metagraph data visualization.
    """

    def __init__(self, admin_site):
        self.admin_site = admin_site

    def get_urls(self):
        return [
            path(
                "metagraph/explorer/",
                self.admin_site.admin_view(self.explorer_view),
                name="metagraph_explorer",
            ),
            path(
                "metagraph/explorer/api/blocks/",
                self.admin_site.admin_view(self.api_blocks),
                name="metagraph_explorer_api_blocks",
            ),
            path(
                "metagraph/explorer/api/data/",
                self.admin_site.admin_view(self.api_data),
                name="metagraph_explorer_api_data",
            ),
        ]

    def explorer_view(self, request):
        """Main explorer view with subnet and block selectors."""
        subnets = Subnet.objects.all().order_by("netuid")
        latest_block = Block.objects.aggregate(max_block=Max("number"))["max_block"]

        context = {
            **self.admin_site.each_context(request),
            "title": "Metagraph Explorer",
            "subnets": subnets,
            "latest_block": latest_block,
        }
        return TemplateResponse(
            request, "admin/metagraph/explorer.html", context
        )

    def api_blocks(self, request):
        """API endpoint to get available blocks for a subnet."""
        subnet_id = request.GET.get("subnet_id")
        if not subnet_id:
            return JsonResponse({"error": "subnet_id required"}, status=400)

        # Get blocks that have snapshots for this subnet
        blocks = (
            NeuronSnapshot.objects.filter(neuron__subnet_id=subnet_id)
            .values("block_id", "block__timestamp")
            .distinct()
            .order_by("-block_id")[:100]
        )

        return JsonResponse(
            {
                "blocks": [
                    {
                        "number": b["block_id"],
                        "timestamp": (
                            b["block__timestamp"].isoformat()
                            if b["block__timestamp"]
                            else None
                        ),
                    }
                    for b in blocks
                ]
            }
        )

    def api_data(self, request):
        """API endpoint to get metagraph data for a subnet and block."""
        subnet_id = request.GET.get("subnet_id")
        block_number = request.GET.get("block_number")
        mech_id = request.GET.get("mech_id", "0")

        if not subnet_id or not block_number:
            return JsonResponse(
                {"error": "subnet_id and block_number required"}, status=400
            )

        try:
            mech_id = int(mech_id)
        except ValueError:
            mech_id = 0

        # If block_number is "latest", get the latest block
        if block_number == "latest":
            block_number = Block.objects.aggregate(max_block=Max("number"))["max_block"]

        snapshots = (
            NeuronSnapshot.objects.filter(
                neuron__subnet_id=subnet_id, block_id=block_number
            )
            .select_related("neuron", "neuron__hotkey", "block")
            .prefetch_related("mechanism_metrics")
            .order_by("-total_stake")
        )

        data = []
        for snap in snapshots:
            hotkey = snap.neuron.hotkey
            metrics = snap.mechanism_metrics.filter(mech_id=mech_id).first()  # type: ignore[attr-defined]

            data.append(
                {
                    "uid": snap.uid,
                    "hotkey": hotkey.hotkey[:16] + "..." if hotkey else "N/A",
                    "hotkey_full": hotkey.hotkey if hotkey else "N/A",
                    "label": hotkey.label if hotkey and hotkey.label else "",
                    "stake_tao": float(snap.total_stake) / 1e9,
                    "rank": snap.rank,
                    "trust": snap.trust,
                    "emissions": float(snap.emissions) / 1e9,
                    "is_active": snap.is_active,
                    "is_validator": snap.is_validator,
                    "is_immune": snap.is_immune,
                    "has_any_weights": snap.has_any_weights,
                    "incentive": metrics.incentive if metrics else 0,
                    "dividend": metrics.dividend if metrics else 0,
                    "consensus": metrics.consensus if metrics else 0,
                    "validator_trust": metrics.validator_trust if metrics else 0,
                    "last_update": metrics.last_update if metrics else None,
                }
            )

        block_info = Block.objects.filter(number=block_number).first()

        return JsonResponse(
            {
                "block": {
                    "number": block_number,
                    "timestamp": (
                        block_info.timestamp.isoformat()
                        if block_info and block_info.timestamp
                        else None
                    ),
                },
                "mech_id": mech_id,
                "neurons": data,
                "summary": {
                    "total_neurons": len(data),
                    "validators": sum(1 for d in data if d["is_validator"]),
                    "miners": sum(1 for d in data if not d["is_validator"]),
                    "active": sum(1 for d in data if d["is_active"]),
                },
            }
        )


# Singleton instance for URL registration
explorer_instance = None


def get_explorer_urls(admin_site):
    """Get explorer URLs for registration with admin site."""
    global explorer_instance
    if explorer_instance is None:
        explorer_instance = MetagraphExplorer(admin_site)
    return explorer_instance.get_urls()
