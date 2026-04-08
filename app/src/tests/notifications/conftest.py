import pytest
from sentinel.v1.dto import ExtrinsicDTO

from apps.notifications.handlers.admin_utils import AdminUtilsNotification
from apps.notifications.handlers.coldkey_swap import ColdkeySwapNotification
from apps.notifications.handlers.subnet_dissolution import SubnetDissolutionNotification
from apps.notifications.handlers.subnet_registration import SubnetRegistrationNotification
from apps.notifications.handlers.sudo import SudoNotification


def flatten_extrinsic(dto: ExtrinsicDTO, *, success: bool = True, **overrides) -> dict:
    """Convert an ExtrinsicDTO to the flat dict format notification handlers expect."""
    d = {
        "extrinsic_hash": dto.extrinsic_hash,
        "extrinsic_index": dto.index,
        "call_module": dto.call.call_module,
        "call_function": dto.call.call_function,
        "call_args": [a.model_dump() for a in dto.call.call_args],
        "address": dto.address or "",
        "success": success,
        "netuid": dto.netuid,
    }
    d.update(overrides)
    return d


@pytest.fixture
def admin_handler():
    return AdminUtilsNotification()


@pytest.fixture
def registration_handler():
    return SubnetRegistrationNotification()


@pytest.fixture
def coldkey_handler():
    return ColdkeySwapNotification()


@pytest.fixture
def dissolution_handler():
    return SubnetDissolutionNotification()


@pytest.fixture
def sudo_handler():
    return SudoNotification()
