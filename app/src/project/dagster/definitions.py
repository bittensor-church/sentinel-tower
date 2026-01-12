"""Dagster definitions for the blockchain data pipeline.

NOTE: Extrinsics and metagraph ingestion have been moved to Celery block tasks.
This file is kept for potential future dagster assets but is currently minimal.
"""

import os
from pathlib import Path

import dagster as dg

# Configure Django settings before importing Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

import django

django.setup()

from django.conf import settings  # noqa: E402

from project.dagster.resources import JsonLinesReader  # noqa: E402

# Determine base path for JSONL files (use Django's MEDIA_ROOT)
MEDIA_ROOT = str(getattr(settings, "MEDIA_ROOT", Path(__file__).parent.parent.parent / "media"))

defs = dg.Definitions(
    assets=[],
    jobs=[],
    sensors=[],
    schedules=[],
    resources={
        "jsonl_reader": JsonLinesReader(base_path=MEDIA_ROOT),
    },
)
