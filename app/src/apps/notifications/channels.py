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

    def _get_webhook_url(self) -> str | None:
        url = os.environ.get(self.env_var, "")
        if not url or any(p in url for p in _DISABLED_WEBHOOK_PATTERNS):
            return None
        return url

    def send(self, payload: dict) -> bool:
        url = self._get_webhook_url()
        if not url:
            return False

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Discord webhook failed", status_code=e.response.status_code, env_var=self.env_var)
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning("Discord webhook error", error=str(e), env_var=self.env_var)
            return False
        return True

    def __repr__(self) -> str:
        return f"DiscordWebhookChannel({self.env_var!r})"
