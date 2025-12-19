from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "project.core"

    def ready(self) -> None:
        from project.core import block_tasks  # noqa: F401
