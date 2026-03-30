import abc
import os

import httpx
import structlog

logger = structlog.get_logger()

_DISABLED_WEBHOOK_PATTERNS = ("disabled", "https://discord.com/api/webhooks/0/disabled")


class NotificationChannel(abc.ABC):
    """Base class for notification delivery channels."""

    @abc.abstractmethod
    def send(self, payload: dict) -> bool:
        """Send a notification payload. Returns True on success."""
        ...


class DiscordWebhookChannel(NotificationChannel):
    """Delivers notifications via Discord webhook."""

    def __init__(self, env_var: str):
        self.env_var = env_var

    def _get_webhook_urls(self) -> list[str]:
        raw = os.environ.get(self.env_var, "")
        if not raw:
            return []
        urls = [u.strip() for u in raw.split(",")]
        return [u for u in urls if u and not any(p in u for p in _DISABLED_WEBHOOK_PATTERNS)]

    def send(self, payload: dict) -> bool:
        urls = self._get_webhook_urls()
        if not urls:
            return False

        any_sent = False
        for url in urls:
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(url, json=payload)
                    response.raise_for_status()
                    any_sent = True
            except httpx.HTTPStatusError as e:
                logger.warning("Discord webhook failed", status_code=e.response.status_code, env_var=self.env_var)
            except Exception as e:  # noqa: BLE001
                logger.warning("Discord webhook error", error=str(e), env_var=self.env_var)
        return any_sent

    def __repr__(self) -> str:
        return f"DiscordWebhookChannel({self.env_var!r})"
