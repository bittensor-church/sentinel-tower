"""Celery tasks for project.core.

`cleanup_expired_data` runs daily via Celery beat (see CELERY_BEAT_SCHEDULE)
and prunes rows past the retention window. Steady-state runs delete roughly
one day of data; the generous time limit covers post-deploy catch-up. The
orchestrator's advisory lock makes overlapping runs (or a concurrent manual
``prune_retention``) a no-op, which also defuses broker redelivery of
long-running tasks (acks_late is enabled globally). If the hard time limit
kills the worker child, ``reject_on_worker_lost`` + ``acks_late`` requeue the
task; the killed session's advisory lock dies with its connection and
per-batch commits mean the requeued run resumes where the previous one
stopped — this is deliberate, not accidental looping.
"""

from datetime import timedelta

from celery import shared_task

from project.core import retention

CLEANUP_TIME_LIMIT = int(timedelta(hours=4).total_seconds())


@shared_task(time_limit=CLEANUP_TIME_LIMIT, soft_time_limit=CLEANUP_TIME_LIMIT - 60)
def cleanup_expired_data() -> None:
    retention.run()
