# Import all handlers to trigger @register decoration.
from apps.notifications.handlers import admin_utils  # noqa: F401
from apps.notifications.handlers import coldkey_swap  # noqa: F401
from apps.notifications.handlers import subnet_dissolution  # noqa: F401
from apps.notifications.handlers import subnet_registration  # noqa: F401
from apps.notifications.handlers import sudo  # noqa: F401
