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
