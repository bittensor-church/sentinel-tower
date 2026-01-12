from django.apps import AppConfig


class MetagraphConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.metagraph"

    def ready(self):
        # Import block_tasks and tasks to register Celery tasks with the app
        from apps.metagraph import block_tasks  # noqa: F401
        from apps.metagraph import tasks  # noqa: F401
