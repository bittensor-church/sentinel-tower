from django.apps import AppConfig


class MetagraphConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.metagraph"

    def ready(self) -> None:
        # from apps.metagraph import block_tasks  # noqa: F401
        pass

