"""Keeps `Coldkey.identity_name` in line with the names owners registered on chain.

Only coldkeys Sentinel already knows are touched; a name the chain no longer has is
cleared. Manual labels live in a separate column and are never written here.
"""

import unicodedata
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from apps.metagraph.models import Coldkey
from apps.metagraph.services.chain_identity import chain_identity_contact

IDENTITY_NAME_MAX_LENGTH = Coldkey._meta.get_field("identity_name").max_length
# A name that is just the start of the key's own address says nothing a shortened
# address would not. Shorter prefixes are left alone: they can be real names.
_ADDRESS_PREFIX_MIN_LENGTH = 8


@dataclass(frozen=True)
class IdentitySyncResult:
    added: int
    changed: int
    cleared: int


def _display_name(coldkey: str, registered_name: str) -> str | None:
    """Return the registered name as it should be displayed, or None when it is not worth showing."""
    printable = "".join(" " if unicodedata.category(char).startswith("C") else char for char in registered_name)
    name = " ".join(printable.split())[:IDENTITY_NAME_MAX_LENGTH].strip()
    if not name:
        return None
    if len(name) >= _ADDRESS_PREFIX_MIN_LENGTH and coldkey.startswith(name):
        return None
    return name


def sync_coldkey_identity_names() -> IdentitySyncResult:
    registered = chain_identity_contact().get_coldkey_identity_names()
    names = {
        coldkey: name
        for coldkey, registered_name in registered.items()
        if (name := _display_name(coldkey, registered_name)) is not None
    }

    added = changed = cleared = 0
    updates = []
    candidates = Coldkey.objects.filter(Q(identity_name__isnull=False) | Q(coldkey__in=names)).only(
        "id", "coldkey", "identity_name"
    )
    for coldkey in candidates:
        name = names.get(coldkey.coldkey)
        if name == coldkey.identity_name:
            continue
        if coldkey.identity_name is None:
            added += 1
        elif name is None:
            cleared += 1
        else:
            changed += 1
        coldkey.identity_name = name
        updates.append(coldkey)

    with transaction.atomic():
        Coldkey.objects.bulk_update(updates, ["identity_name"], batch_size=1000)
    return IdentitySyncResult(added=added, changed=changed, cleared=cleared)
