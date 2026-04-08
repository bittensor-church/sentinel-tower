import pytest
from sentinel.v1.testing import AnnounceColdkeySwapExtrinsicDTOFactory

from apps.notifications.handlers.coldkey_swap import ColdkeySwapNotification
from tests.factories.metagraph import ColdkeyFactory
from tests.notifications.conftest import flatten_extrinsic


@pytest.mark.django_db
def test_coldkey_swap_basic():
    label = "test-key"
    coldkey = ColdkeyFactory(label=label)
    assert coldkey.coldkey.startswith("5C")

    dto = AnnounceColdkeySwapExtrinsicDTOFactory.build_for_hash("0xabc123")
    flat = flatten_extrinsic(dto, address=coldkey.coldkey)

    notification = ColdkeySwapNotification()
    notification.format_message(0, [flat])
