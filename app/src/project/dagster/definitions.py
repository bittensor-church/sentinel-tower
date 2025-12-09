"""Dagster definitions for the blockchain data pipeline."""
import os
from pathlib import Path

import dagster as dg

# Configure Django settings before importing Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

import django

django.setup()

from django.conf import settings

from project.dagster.assets import (
    available_netuids,
    hyperparams_extrinsics,
    netuid_assets,
    set_weights_extrinsics,
)
from project.dagster.resources import JsonLinesReader

# Determine base path for JSONL files (use Django's MEDIA_ROOT)
MEDIA_ROOT = str(getattr(settings, "MEDIA_ROOT", Path(__file__).parent.parent.parent / "media"))

# Core assets that work with aggregated data
core_assets = [
    hyperparams_extrinsics,
    available_netuids,
    set_weights_extrinsics,
]

# All assets including per-netuid granular assets
all_assets = core_assets + netuid_assets

defs = dg.Definitions(
    assets=all_assets,
    resources={
        "jsonl_reader": JsonLinesReader(base_path=MEDIA_ROOT),
    },
)
