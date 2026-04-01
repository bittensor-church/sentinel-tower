"""Service for caching and managing blockchain key objects (coldkeys, hotkeys, EVM keys)."""

from typing import Any

from django.utils import timezone

from apps.metagraph.models import Coldkey, EvmKey, Hotkey


class KeyCacheService:
    """Manages get_or_create with in-memory caching for Coldkey, Hotkey, and EvmKey."""

    def __init__(self) -> None:
        self._coldkey_cache: dict[str, Coldkey] = {}
        self._hotkey_cache: dict[str, Hotkey] = {}
        self._evmkey_cache: dict[str, EvmKey] = {}
        self._hotkeys_to_update: set[int] = set()

    def get_cached_hotkey(self, hotkey_address: str) -> Hotkey | None:
        """Look up a hotkey in the cache without creating it."""
        return self._hotkey_cache.get(hotkey_address)

    def get_or_create_coldkey(self, coldkey_address: str) -> Coldkey:
        """Get or create a Coldkey, using cache."""
        if coldkey_address in self._coldkey_cache:
            return self._coldkey_cache[coldkey_address]

        coldkey, _ = Coldkey.objects.get_or_create(coldkey=coldkey_address)
        self._coldkey_cache[coldkey_address] = coldkey
        return coldkey

    def get_or_create_hotkey(
        self,
        hotkey_address: str,
        coldkey_data: dict[str, Any] | None,
    ) -> Hotkey:
        """Get or create a Hotkey, using cache."""
        if hotkey_address in self._hotkey_cache:
            hotkey = self._hotkey_cache[hotkey_address]
            self._hotkeys_to_update.add(hotkey.id)
            return hotkey

        coldkey = None
        if coldkey_data:
            coldkey = self.get_or_create_coldkey(coldkey_data["coldkey"])

        hotkey, created = Hotkey.objects.get_or_create(
            hotkey=hotkey_address,
            defaults={"coldkey": coldkey, "last_seen": timezone.now()},
        )
        if not created:
            if coldkey and hotkey.coldkey_id != coldkey.id:
                hotkey.coldkey = coldkey
                hotkey.save(update_fields=["coldkey"])
            self._hotkeys_to_update.add(hotkey.id)

        self._hotkey_cache[hotkey_address] = hotkey
        return hotkey

    def get_or_create_evmkey(self, evm_address: str) -> EvmKey:
        """Get or create an EvmKey, using cache."""
        if evm_address in self._evmkey_cache:
            return self._evmkey_cache[evm_address]

        evmkey, _ = EvmKey.objects.get_or_create(evm_address=evm_address)
        self._evmkey_cache[evm_address] = evmkey
        return evmkey

    def flush_hotkey_last_seen(self) -> int:
        """Bulk update last_seen for all hotkeys touched during this sync."""
        if not self._hotkeys_to_update:
            return 0

        now = timezone.now()
        count = Hotkey.objects.filter(id__in=self._hotkeys_to_update).update(last_seen=now)
        self._hotkeys_to_update.clear()
        return count
