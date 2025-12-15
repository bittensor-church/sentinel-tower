"""Dagster definitions for the blockchain data pipeline."""

import os
from pathlib import Path

import dagster as dg

# Configure Django settings before importing Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

import django

django.setup()

from django.conf import settings  # noqa: E402

from project.dagster.assets import hyperparams_extrinsics  # noqa: E402
from project.dagster.jobs import (  # noqa: E402
    extrinsics_sensor,
    hourly_ingest_schedule,
    hyperparams_sensor,
    ingest_all_events_job,
    ingest_extrinsics_job,
    ingest_hyperparams_job,
)
from project.dagster.resources import JsonLinesReader  # noqa: E402

# Determine base path for JSONL files (use Django's MEDIA_ROOT)
MEDIA_ROOT = str(getattr(settings, "MEDIA_ROOT", Path(__file__).parent.parent.parent / "media"))

defs = dg.Definitions(
    assets=[
        hyperparams_extrinsics,
    ],
    jobs=[
        ingest_hyperparams_job,
        ingest_extrinsics_job,
        ingest_all_events_job,
    ],
    sensors=[
        hyperparams_sensor,
        extrinsics_sensor,
    ],
    schedules=[
        hourly_ingest_schedule,
    ],
    resources={
        "jsonl_reader": JsonLinesReader(base_path=MEDIA_ROOT),
    },
)
