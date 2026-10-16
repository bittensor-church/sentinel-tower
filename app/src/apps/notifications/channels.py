import abc
import contextlib
import os
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()

_DISABLED_WEBHOOK_PATTERNS = ("disabled", "https://discord.com/api/webhooks/0/disabled")

_http_client = httpx.Client(timeout=10.0)


@dataclass(frozen=True)
class DryRunDelivery:
    """A notification captured instead of being posted, see ``dry_run()``."""

    channel: str
    url_count: int
    payload: dict


_dry_run_deliveries: ContextVar[list[DryRunDelivery] | None] = ContextVar("_dry_run_deliveries", default=None)


@contextlib.contextmanager
def dry_run() -> Iterator[list[DryRunDelivery]]:
    """Capture and log every webhook delivery made inside the block instead of posting it.

    A channel still reports success only if it has webhook URLs configured,
    so routing and fallbacks behave as they would for real.
    """
    deliveries: list[DryRunDelivery] = []
    token = _dry_run_deliveries.set(deliveries)
    try:
        yield deliveries
    finally:
        _dry_run_deliveries.reset(token)


class NotificationChannel(abc.ABC):
    """Base class for notification delivery channels."""

    @abc.abstractmethod
    def send(self, payload: dict) -> bool:
        """Send a notification payload. Returns True on success."""
        ...

    @staticmethod
    def _send_to_urls(urls: list[str], payload: dict, *, context: str = "") -> bool:
        """Send a payload to a list of webhook URLs. Returns True if at least one succeeds."""
        deliveries = _dry_run_deliveries.get()
        if deliveries is not None:
            deliveries.append(DryRunDelivery(channel=context, url_count=len(urls), payload=payload))
            logger.info("Dry run: webhook not posted", context=context, url_count=len(urls), payload=payload)
            return bool(urls)

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
        return self._send_to_urls(self._get_webhook_urls(), payload, context=self.env_var)

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
        return self._send_to_urls(self._get_webhook_urls(), payload, context=f"subnet:{self.netuid}")

    def __repr__(self) -> str:
        return f"DatabaseWebhookChannel(netuid={self.netuid})"
