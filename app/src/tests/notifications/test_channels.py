from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.notifications.channels import DiscordWebhookChannel


@pytest.fixture
def channel():
    return DiscordWebhookChannel("TEST_WEBHOOK_URL")


# ── _get_webhook_urls() ──────────────────────────────────────────────


def test_get_webhook_urls_single(channel, monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")
    assert channel._get_webhook_urls() == ["https://discord.com/api/webhooks/123/abc"]


def test_get_webhook_urls_multiple(channel, monkeypatch):
    monkeypatch.setenv(
        "TEST_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123/abc,https://discord.com/api/webhooks/456/def",
    )
    assert channel._get_webhook_urls() == [
        "https://discord.com/api/webhooks/123/abc",
        "https://discord.com/api/webhooks/456/def",
    ]


def test_get_webhook_urls_returns_empty_when_missing(channel, monkeypatch):
    monkeypatch.delenv("TEST_WEBHOOK_URL", raising=False)
    assert channel._get_webhook_urls() == []


def test_get_webhook_urls_returns_empty_when_empty(channel, monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_URL", "")
    assert channel._get_webhook_urls() == []


@pytest.mark.parametrize(
    "url",
    [
        "disabled",
        "https://discord.com/api/webhooks/0/disabled",
    ],
)
def test_get_webhook_urls_filters_disabled(channel, monkeypatch, url):
    monkeypatch.setenv("TEST_WEBHOOK_URL", url)
    assert channel._get_webhook_urls() == []


def test_get_webhook_urls_filters_disabled_from_list(channel, monkeypatch):
    monkeypatch.setenv(
        "TEST_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123/abc,disabled,https://discord.com/api/webhooks/456/def",
    )
    assert channel._get_webhook_urls() == [
        "https://discord.com/api/webhooks/123/abc",
        "https://discord.com/api/webhooks/456/def",
    ]


# ── send() ─────────────────────────────────────────────────────────────


def test_send_returns_false_when_no_url(channel, monkeypatch):
    monkeypatch.delenv("TEST_WEBHOOK_URL", raising=False)
    assert channel.send({"content": "test"}) is False


@patch("apps.notifications.channels.httpx.Client")
def test_send_posts_to_webhook(mock_client_cls, channel, monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = channel.send({"content": "hello"})

    assert result is True
    mock_client.post.assert_called_once_with(
        "https://discord.com/api/webhooks/123/abc",
        json={"content": "hello"},
    )


@patch("apps.notifications.channels.httpx.Client")
def test_send_posts_to_multiple_webhooks(mock_client_cls, channel, monkeypatch):
    monkeypatch.setenv(
        "TEST_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123/abc,https://discord.com/api/webhooks/456/def",
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = channel.send({"content": "hello"})

    assert result is True
    assert mock_client.post.call_count == 2
    mock_client.post.assert_any_call("https://discord.com/api/webhooks/123/abc", json={"content": "hello"})
    mock_client.post.assert_any_call("https://discord.com/api/webhooks/456/def", json={"content": "hello"})


@patch("apps.notifications.channels.httpx.Client")
def test_send_partial_failure_still_returns_true(mock_client_cls, channel, monkeypatch):
    """If one URL fails but another succeeds, send() returns True."""
    monkeypatch.setenv(
        "TEST_WEBHOOK_URL",
        "https://discord.com/api/webhooks/123/abc,https://discord.com/api/webhooks/456/def",
    )

    mock_response_ok = MagicMock()
    mock_response_ok.raise_for_status = MagicMock()

    mock_response_fail = MagicMock()
    mock_response_fail.status_code = 429
    mock_response_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited", request=MagicMock(), response=mock_response_fail
    )

    mock_client = MagicMock()
    mock_client.post.side_effect = [mock_response_fail, mock_response_ok]
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    assert channel.send({"content": "hello"}) is True


@patch("apps.notifications.channels.httpx.Client")
def test_send_returns_false_on_http_error(mock_client_cls, channel, monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited", request=MagicMock(), response=mock_response
    )
    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    assert channel.send({"content": "hello"}) is False


@patch("apps.notifications.channels.httpx.Client")
def test_send_returns_false_on_connection_error(mock_client_cls, channel, monkeypatch):
    monkeypatch.setenv("TEST_WEBHOOK_URL", "https://discord.com/api/webhooks/123/abc")

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectError("connection failed")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = mock_client

    assert channel.send({"content": "hello"}) is False


# ── repr ───────────────────────────────────────────────────────────────


def test_repr(channel):
    assert repr(channel) == "DiscordWebhookChannel('TEST_WEBHOOK_URL')"
