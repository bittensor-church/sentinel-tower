from django.core.management.base import BaseCommand

from apps.extrinsics.notifications import send_discord_notification


class Command(BaseCommand):
    help = "Send a test Discord notification."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--type",
            type=str,
            default="sudo",
            choices=["sudo", "admin", "register", "coldkey_swap"],
            help="Type of notification to send (default: sudo)",
        )

    def handle(self, *args, **kwargs):
        notification_type = kwargs["type"]

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
                "block_number": 1234568,
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
                "block_number": 1234569,
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
                "block_number": 1234570,
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

        extrinsic = sample_extrinsics[notification_type]
        self.stdout.write(f"Sending test {notification_type} notification...")

        success = send_discord_notification(extrinsic)

        if success:
            self.stdout.write(self.style.SUCCESS("Notification sent successfully!"))
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Failed to send notification. Check webhook URL configuration."
                )
            )
