"""Pins which logger trees may emit DEBUG.

bittensor v11 moved JSON-RPC frame logging from the ``websockets`` logger to
``bittensor.transport.raw_websocket``. The old mute did not cover it, so with
LOG_LEVEL=DEBUG prod wrote every multi-KB hex frame to disk — ~3 GiB/day, which
filled the root filesystem twice (2026-09-23, 2026-09-29).
These tests fail if that mute is dropped or the logger tree is renamed again.
"""

import logging
import logging.config

import pytest
from django.conf import settings


@pytest.fixture
def configured_logging():
    """Apply settings.LOGGING for real, so effective levels can be asserted.

    ``disable_existing_loggers`` is False in settings.LOGGING, so pytest's own
    capture handlers survive this and the logging plugin re-attaches per test.
    """
    logging.config.dictConfig(settings.LOGGING)


@pytest.mark.parametrize(
    "logger_name",
    [
        "bittensor",
        "bittensor.transport",
        "bittensor.transport.raw_websocket",
        "websockets",
    ],
)
def test_chain_transport_loggers_do_not_emit_debug(configured_logging, logger_name):
    assert not logging.getLogger(logger_name).isEnabledFor(logging.DEBUG)
    assert not logging.getLogger(logger_name).isEnabledFor(logging.INFO)


@pytest.mark.parametrize(
    "logger_name",
    [
        "apps.extrinsics.block_tasks",
        "apps.metagraph.block_tasks",
    ],
)
def test_application_loggers_still_emit_warnings(configured_logging, logger_name):
    assert logging.getLogger(logger_name).isEnabledFor(logging.WARNING)


def test_bittensor_still_uses_the_muted_logger_name():
    """Guards against bittensor renaming the frame logger out from under the mute."""
    from bittensor._transport import rpc  # noqa: PLC0415

    assert rpc.raw_logger.name.startswith("bittensor.")
