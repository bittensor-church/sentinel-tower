from django.apps import AppConfig


class ExtrinsicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.extrinsics"

    def ready(self):
        # Import block_tasks to register Celery tasks with the app
        from apps.extrinsics import block_tasks  # noqa: F401
