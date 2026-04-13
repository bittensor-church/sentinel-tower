import abc
import os

import httpx
import structlog

logger = structlog.get_logger()

_DISABLED_WEBHOOK_PATTERNS = ("disabled", "https://discord.com/api/webhooks/0/disabled")

_http_client = httpx.Client(timeout=10.0)


class NotificationChannel(abc.ABC):
    """Base class for notification delivery channels."""

    @abc.abstractmethod
    def send(self, payload: dict) -> bool:
        """Send a notification payload. Returns True on success."""
        ...

    @staticmethod
    def _send_to_urls(urls: list[str], payload: dict, *, context: str = "") -> bool:
        """Send a payload to a list of webhook URLs. Returns True if at least one succeeds."""
        any_sent = False
        for url in urls:
            try:
                response = _http_client.post(url, json=payload)
                response.raise_for_status()
                any_sent = True
            except httpx.HTTPStatusError as e:
                logger.warning("Webhook failed", status_code=e.response.status_code, context=context)
            except httpx.TimeoutException:
                logger.warning("Webhook timeout", context=context)
            except httpx.ConnectError:
                logger.warning("Webhook connection error", context=context)
            except Exception as e:  # noqa: BLE001
                logger.warning("Webhook error", error=str(e), context=context, exc_info=True)
        return any_sent


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
        return self._send_to_urls(urls, payload, context=self.env_var)

    def __repr__(self) -> str:
        return f"DiscordWebhookChannel({self.env_var!r})"


class DatabaseWebhookChannel(NotificationChannel):
    """Delivers notifications via webhook URLs stored in the database, keyed by subnet."""

    def __init__(self, netuid: int):
        self.netuid = netuid

    def _get_webhook_urls(self) -> list[str]:
        from apps.notifications.models import SubnetWebhook

        return list(
            SubnetWebhook.objects.filter(
                netuid=self.netuid,
                enabled=True,
            ).values_list("url", flat=True)
        )

    def send(self, payload: dict) -> bool:
        urls = self._get_webhook_urls()
        if not urls:
            return False
        return self._send_to_urls(urls, payload, context=f"subnet:{self.netuid}")

    def __repr__(self) -> str:
        return f"DatabaseWebhookChannel(netuid={self.netuid})"
