from django.core.management.base import BaseCommand

from apps.extrinsics.hyperparam_service import enrich_extrinsics_with_previous_values
from apps.extrinsics.notifications import send_block_notifications


class Command(BaseCommand):
    help = "Send a test Discord notification with aggregated extrinsics per block."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--type",
            type=str,
            default="sudo",
            choices=["sudo", "admin", "register", "coldkey_swap", "all"],
            help="Type of notification to send (default: sudo, use 'all' for grouped test)",
        )
        parser.add_argument(
            "--failed",
            action="store_true",
            help="Simulate a failed extrinsic (useful for testing success_only filtering)",
        )

    def handle(self, *args, **kwargs):
        notification_type = kwargs["type"]
        simulate_failed = kwargs["failed"]

        sample_extrinsics = {
            "sudo": {
                "call_module": "Sudo",
                "call_function": "sudo",
                "block_number": 1234567,
                "extrinsic_index": 1,
                "address": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "extrinsic_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                "success": True,
                "netuid": 1,
                "call_args": [
                    {"name": "call", "value": "set_weights"},
                ],
            },
            "admin": {
                "call_module": "AdminUtils",
                "call_function": "sudo_set_default_take",
                "block_number": 1234567,
                "extrinsic_index": 2,
                "address": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "extrinsic_hash": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "success": True,
                "netuid": 5,
                "call_args": [
                    {"name": "default_take", "value": 11796},
                ],
            },
            "register": {
                "call_module": "SubtensorModule",
                "call_function": "register_network",
                "block_number": 1234567,
                "extrinsic_index": 3,
                "address": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
                "extrinsic_hash": "0x9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba",
                "success": True,
                "netuid": 42,
                "call_args": [
                    {"name": "immunity_period", "value": 5000},
                    {"name": "netuid", "value": 42},
                ],
            },
            "coldkey_swap": {
                "call_module": "SubtensorModule",
                "call_function": "schedule_coldkey_swap",
                "block_number": 1234567,
                "extrinsic_index": 4,
                "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy",
                "extrinsic_hash": "0xfedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
                "success": True,
                "call_args": [
                    {"name": "new_coldkey", "value": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"},
                    {"name": "old_coldkey", "value": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"},
                ],
            },
        }

        # Additional extrinsics for grouped notification testing
        grouped_extrinsics = [
            {
                "call_module": "AdminUtils",
                "call_function": "sudo_set_tempo",
                "block_number": 1234567,
                "extrinsic_index": 5,
                "address": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "extrinsic_hash": "0x1111111111111111111111111111111111111111111111111111111111111111",
                "success": True,
                "netuid": 1,
                "call_args": [
                    {"name": "tempo", "value": 360},
                ],
            },
            {
                "call_module": "AdminUtils",
                "call_function": "sudo_set_weights_set_rate_limit",
                "block_number": 1234567,
                "extrinsic_index": 6,
                "address": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                "extrinsic_hash": "0x2222222222222222222222222222222222222222222222222222222222222222",
                "success": True,
                "netuid": 1,
                "call_args": [
                    {"name": "rate_limit", "value": 100},
                ],
            },
        ]

        block_number = 1234567

        if notification_type == "all":
            # Send all extrinsics as a grouped notification (includes multiple AdminUtils for grouping demo)
            extrinsics = list(sample_extrinsics.values()) + grouped_extrinsics
            self.stdout.write(
                f"Sending grouped notification with {len(extrinsics)} extrinsics for block {block_number}..."
            )
        else:
            extrinsics = [sample_extrinsics[notification_type]]
            self.stdout.write(f"Sending test {notification_type} notification for block {block_number}...")

        if simulate_failed:
            for ext in extrinsics:
                ext["success"] = False
            self.stdout.write(self.style.WARNING("Simulating FAILED extrinsics (will be filtered out)"))

        # Enrich with previous hyperparam values
        enriched = enrich_extrinsics_with_previous_values(extrinsics)
        notified_count = send_block_notifications(block_number, enriched)

        if notified_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"Notification sent successfully! ({notified_count} extrinsics notified)")
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Failed to send notification. Check webhook URL configuration."
                )
            )
