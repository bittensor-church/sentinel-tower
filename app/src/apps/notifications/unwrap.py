"""Unwrap dispatch wrappers (Sudo, Multisig) down to the call they execute.

Notification handlers and hyperparam enrichment match on the call that
actually ran, not on the wrapper submitted on-chain. Wrappers nest, e.g.
``Multisig.as_multi(Sudo.sudo(AdminUtils.sudo_set_tempo))``, so unwrapping
repeats until no known wrapper is left.
"""

import hashlib
from typing import Any

import structlog
from bittensor.sp_core import ss58_decode, ss58_encode

logger = structlog.get_logger()

BITTENSOR_SS58_FORMAT = 42

# pallet_multisig::multi_account_id: blake2_256(b"modlpy/utilisuba" ++ sorted signatories ++ threshold)
_MULTISIG_ACCOUNT_PREFIX = b"modlpy/utilisuba"
_COMPACT_SINGLE_BYTE_MAX = 0b0011_1111
_COMPACT_TWO_BYTE_MAX = 0b0011_1111_1111_1111


def unwrap_call(extrinsic: dict[str, Any]) -> dict[str, Any]:
    """Return the extrinsic as seen through every Sudo/executed-Multisig wrapper.

    The result keeps all outer fields (hash, index, events, …) and replaces
    ``call_module``/``call_function``/``call_args`` with the innermost call.

    - ``Sudo.sudo`` sets ``_is_sudo``.
    - ``Multisig.as_multi`` is unwrapped only when it was executed (its
      ``MultisigExecuted`` event is present); ``success`` then reflects the
      inner call's dispatch result. Proposals and intermediate approvals are
      returned unchanged.
    - ``Multisig.as_multi_threshold_1`` always executes, so it is always
      unwrapped (with the same event-based result when the runtime emits one).
    - For multisig, ``address`` becomes the multisig account (the call's
      origin) and ``multisig_approver`` holds the account that signed the
      executing extrinsic.

    Returns the input object itself when nothing was unwrapped.
    """
    current = extrinsic
    while (inner := _unwrap_once(current)) is not None:
        current = inner
    return current


def _unwrap_once(extrinsic: dict[str, Any]) -> dict[str, Any] | None:
    call_module = extrinsic.get("call_module", "")
    call_function = extrinsic.get("call_function", "")
    if call_module == "Sudo" and call_function == "sudo":
        return _unwrap_sudo(extrinsic)
    if call_module == "Multisig" and call_function == "as_multi":
        return _unwrap_as_multi(extrinsic)
    if call_module == "Multisig" and call_function == "as_multi_threshold_1":
        return _unwrap_as_multi_threshold_1(extrinsic)
    return None


def _call_arg(extrinsic: dict[str, Any], name: str) -> Any:
    for arg in extrinsic.get("call_args") or []:
        if arg.get("name") == name:
            return arg.get("value")
    return None


def _with_inner_call(extrinsic: dict[str, Any], inner: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    inner_args = inner.get("call_args", [])
    netuid = extrinsic.get("netuid")
    if netuid is None:
        for inner_arg in inner_args:
            if inner_arg.get("name") == "netuid":
                netuid = inner_arg.get("value")
                break
    return {
        **extrinsic,
        "call_module": inner.get("call_module", ""),
        "call_function": inner.get("call_function", ""),
        "call_args": inner_args,
        "netuid": netuid,
        **overrides,
    }


def _unwrap_sudo(extrinsic: dict[str, Any]) -> dict[str, Any] | None:
    inner = _call_arg(extrinsic, "call")
    if not isinstance(inner, dict):
        return None
    return _with_inner_call(extrinsic, inner, _is_sudo=True)


def _unwrap_as_multi(extrinsic: dict[str, Any]) -> dict[str, Any] | None:
    inner = _call_arg(extrinsic, "call")
    if not isinstance(inner, dict):
        return None
    executed = _multisig_executed_attributes(extrinsic, inner.get("call_hash"))
    if executed is None:
        return None
    return _with_multisig_call(extrinsic, inner, executed)


def _unwrap_as_multi_threshold_1(extrinsic: dict[str, Any]) -> dict[str, Any] | None:
    inner = _call_arg(extrinsic, "call")
    if not isinstance(inner, dict):
        return None
    executed = _multisig_executed_attributes(extrinsic, inner.get("call_hash"))
    if executed is not None:
        return _with_multisig_call(extrinsic, inner, executed)
    # Runtimes that emit no MultisigExecuted here fail the extrinsic itself when
    # the inner call fails, so the outer success stands; derive the origin.
    signer = extrinsic.get("address", "")
    other_signatories = _call_arg(extrinsic, "other_signatories") or []
    multisig = _multisig_account([signer, *other_signatories], threshold=1)
    return _with_inner_call(extrinsic, inner, address=multisig or signer, multisig_approver=signer)


def _with_multisig_call(extrinsic: dict[str, Any], inner: dict[str, Any], executed: dict[str, Any]) -> dict[str, Any]:
    result = executed.get("result")
    inner_ok = isinstance(result, dict) and "Ok" in result
    signer = extrinsic.get("address", "")
    return _with_inner_call(
        extrinsic,
        inner,
        success=bool(extrinsic.get("success", False)) and inner_ok,
        address=executed.get("multisig") or signer,
        multisig_approver=executed.get("approving") or signer,
    )


def _multisig_executed_attributes(extrinsic: dict[str, Any], call_hash: Any) -> dict[str, Any] | None:
    """Attributes of the MultisigExecuted event for ``call_hash`` (any, if the hash is unknown)."""
    for event in extrinsic.get("events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("module_id") != "Multisig" or event.get("event_id") != "MultisigExecuted":
            continue
        attrs = event.get("attributes")
        if not isinstance(attrs, dict):
            continue
        if call_hash and attrs.get("call_hash") and attrs["call_hash"] != call_hash:
            continue
        return attrs
    return None


def _multisig_account(signatories: list[str], threshold: int) -> str | None:
    """Derive the SS58 multisig account for ``signatories`` at ``threshold``, as pallet_multisig does.

    Returns None if any signatory is not a decodable SS58 address.
    """
    try:
        keys = sorted({ss58_decode(address) for address in signatories})
    except Exception:  # noqa: BLE001
        logger.debug("Cannot derive multisig account", signatories=signatories, exc_info=True)
        return None
    if not keys or len(keys) > _COMPACT_TWO_BYTE_MAX:
        return None
    count = len(keys)
    length = bytes([count << 2]) if count <= _COMPACT_SINGLE_BYTE_MAX else ((count << 2) | 0b01).to_bytes(2, "little")
    preimage = _MULTISIG_ACCOUNT_PREFIX + length + b"".join(keys) + threshold.to_bytes(2, "little")
    return ss58_encode(hashlib.blake2b(preimage, digest_size=32).digest(), BITTENSOR_SS58_FORMAT)
