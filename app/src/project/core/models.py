"""Django models for core data storage."""

from django.db import models


class IngestionCheckpoint(models.Model):
    """
    Tracks the last processed line number for each JSONL file.

    This allows incremental processing of new records.
    """

    file_path = models.CharField(max_length=255, unique=True)
    last_processed_line = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.file_path}: line {self.last_processed_line}"


class MonitoringProgress(models.Model):
    """Committed progress, independent of worker lifetime and scrape frequency."""

    name = models.CharField(max_length=64, primary_key=True)
    source_block = models.PositiveBigIntegerField(default=0)
    source_timestamp = models.DateTimeField(null=True)
    succeeded_at = models.DateTimeField()


class MonitoringResult(models.Model):
    """Bounded background checks; scrapes only read these small summaries."""

    kind = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    netuid = models.CharField(max_length=16, default="all")
    checked_at = models.DateTimeField()
    source_timestamp = models.DateTimeField(null=True)
    max_age_seconds = models.PositiveIntegerField(default=300)
    success = models.BooleanField(default=False)
    duration_seconds = models.FloatField(default=0)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "name", "netuid"], name="unique_monitoring_result")]
