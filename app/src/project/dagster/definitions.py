"""Dagster definitions for the blockchain data pipeline."""
import os
from pathlib import Path

import dagster as dg

# Configure Django settings before importing Django-dependent modules
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")

import django

django.setup()

from django.conf import settings

from project.dagster.assets import hyperparams_extrinsics, set_weights_extrinsics
from project.dagster.jobs import (
    hourly_ingest_schedule,
    hyperparams_sensor,
    ingest_all_events_job,
    ingest_hyperparams_job,
    ingest_set_weights_job,
    set_weights_sensor,
)
from project.dagster.resources import JsonLinesReader

# Determine base path for JSONL files (use Django's MEDIA_ROOT)
MEDIA_ROOT = str(getattr(settings, "MEDIA_ROOT", Path(__file__).parent.parent.parent / "media"))

defs = dg.Definitions(
    assets=[
        hyperparams_extrinsics,
        set_weights_extrinsics,
    ],
    jobs=[
        ingest_hyperparams_job,
        ingest_set_weights_job,
        ingest_all_events_job,
    ],
    sensors=[
        hyperparams_sensor,
        set_weights_sensor,
    ],
    schedules=[
        hourly_ingest_schedule,
    ],
    resources={
        "jsonl_reader": JsonLinesReader(base_path=MEDIA_ROOT),
    },
)
