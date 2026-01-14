"""Management command to load hotkey and coldkey labels from fixtures."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.metagraph.models import Coldkey, Hotkey


class Command(BaseCommand):
    help = "Load hotkey and coldkey labels from fixture files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--hotkeys",
            type=str,
            help="Path to hotkey labels JSON file",
        )
        parser.add_argument(
            "--coldkeys",
            type=str,
            help="Path to coldkey labels JSON file",
        )

    def handle(self, *args, **options):
        fixtures_dir = Path(__file__).resolve().parent.parent.parent / "fixtures"

        hotkeys_file = options["hotkeys"] or fixtures_dir / "hotkey_labels.json"
        coldkeys_file = options["coldkeys"] or fixtures_dir / "coldkey_labels.json"

        if Path(coldkeys_file).exists():
            self._load_coldkey_labels(coldkeys_file)

        if Path(hotkeys_file).exists():
            self._load_hotkey_labels(hotkeys_file)

    def _load_coldkey_labels(self, filepath):
        with open(filepath) as f:
            data = json.load(f)

        updated = 0
        for item in data:
            coldkey = item["coldkey"]
            label = item.get("label") or item.get("name", "")
            count = Coldkey.objects.filter(coldkey=coldkey).update(label=label)
            if count:
                updated += count
                self.stdout.write(f"Updated coldkey {coldkey[:12]}... -> {label}")
            else:
                self.stdout.write(self.style.WARNING(f"Coldkey not found: {coldkey[:12]}..."))

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} coldkey labels"))

    def _load_hotkey_labels(self, filepath):
        with open(filepath) as f:
            data = json.load(f)

        updated = 0
        for item in data:
            hotkey = item["hotkey"]
            label = item.get("label") or item.get("name", "")
            count = Hotkey.objects.filter(hotkey=hotkey).update(label=label)
            if count:
                updated += count
                self.stdout.write(f"Updated hotkey {hotkey[:12]}... -> {label}")
            else:
                self.stdout.write(self.style.WARNING(f"Hotkey not found: {hotkey[:12]}..."))

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} hotkey labels"))
