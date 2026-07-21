"""Re-seed `subtensor_error_codes` from the live runtime error enum (specVersion 424).

Migration 0010 seeded names from `set-weights.md`, whose ordering had drifted from
the deployed runtime: the runtime inserts `NewHotKeyNotCleanForRootSwap` at index 23,
which shifts every later variant by one, so 94 of the 135 previously-seeded codes
decoded to the wrong `Error<T>` name (e.g. `0x4c000000` resolved to
`TooManyUnrevealedCommits` when the runtime means `SubnetNotExists`). The dashboards
that join this table (`weight-setting.json`) therefore showed operators confidently
wrong error names.

This list is generated directly from `state_getMetadata` on a runtime-424 node
(finney's version) — the authoritative SCALE variant ordering — and covers all 147
variants, including the 12 that were missing entirely. Regenerate against the runtime
metadata when the deployed spec version changes.

Conflict policy matches 0010: `bulk_create(update_conflicts=True)` overwrites
name/category/description/remediation on `(pallet_index, error_code)` collision, so
this cleanly supersedes the drifted rows.
"""

from django.db import migrations

# (error_code, Error<T> name, documentation) for pallet 7 (SubtensorModule),
# generated from runtime specVersion 424. error_code is the little-endian hex of the
# SCALE variant index, matching `error_data.dispatch_error.Module.error` on-chain.
ERRORS: list[tuple[str, str, str]] = [
    ("0x00000000", "RootNetworkDoesNotExist", "The root network does not exist."),
    ("0x01000000", "InvalidIpType", "The user is trying to serve an axon which is not of type 4 (IPv4) or 6 (IPv6)."),
    ("0x02000000", "InvalidIpAddress", "An invalid IP address is passed to the serve function."),
    ("0x03000000", "InvalidPort", "An invalid port is passed to the serve function."),
    ("0x04000000", "HotKeyNotRegisteredInSubNet", "The hotkey is not registered in subnet"),
    ("0x05000000", "HotKeyAccountNotExists", "The hotkey does not exists"),
    ("0x06000000", "HotKeyNotRegisteredInNetwork", "The hotkey is not registered in any subnet."),
    (
        "0x07000000",
        "NonAssociatedColdKey",
        "Request to stake, unstake or subscribe is made by a coldkey that is not associated with\nthe hotkey account.",
    ),
    (
        "0x08000000",
        "NotEnoughStake",
        "DEPRECATED: Stake amount to withdraw is zero.\nThe caller does not have enough stake to perform this action.",
    ),
    (
        "0x09000000",
        "NotEnoughStakeToWithdraw",
        'The caller is requesting removing more stake than there exists in the staking account.\nSee: \\"[remove_stake()]\\".',
    ),
    (
        "0x0a000000",
        "NotEnoughStakeToSetWeights",
        "The caller is requesting to set weights but the caller has less than minimum stake\nrequired to set weights (less than WeightsMinStake).",
    ),
    ("0x0b000000", "NotEnoughStakeToSetChildkeys", "The parent hotkey doesn't have enough own stake to set childkeys."),
    (
        "0x0c000000",
        "NotEnoughBalanceToStake",
        'The caller is requesting adding more stake than there exists in the coldkey account.\nSee: \\"[add_stake()]\\"',
    ),
    (
        "0x0d000000",
        "BalanceWithdrawalError",
        "The caller is trying to add stake, but for some reason the requested amount could not be\nwithdrawn from the coldkey account.",
    ),
    (
        "0x0e000000",
        "ZeroBalanceAfterWithdrawn",
        "Unsuccessfully withdraw, balance could be zero (can not make account exist) after\nwithdrawal.",
    ),
    (
        "0x0f000000",
        "NeuronNoValidatorPermit",
        "The caller is attempting to set non-self weights without being a permitted validator.",
    ),
    (
        "0x10000000",
        "WeightVecNotEqualSize",
        "The caller is attempting to set the weight keys and values but these vectors have\ndifferent size.",
    ),
    (
        "0x11000000",
        "DuplicateUids",
        "The caller is attempting to set weights with duplicate UIDs in the weight matrix.",
    ),
    (
        "0x12000000",
        "UidVecContainInvalidOne",
        "The caller is attempting to set weight to at least one UID that does not exist in the\nmetagraph.",
    ),
    (
        "0x13000000",
        "WeightVecLengthIsLow",
        "The dispatch is attempting to set weights on chain with fewer elements than are allowed.",
    ),
    (
        "0x14000000",
        "TooManyRegistrationsThisBlock",
        'Number of registrations in this block exceeds the allowed number (i.e., exceeds the\nsubnet hyperparameter \\"max_regs_per_block\\").',
    ),
    (
        "0x15000000",
        "HotKeyAlreadyRegisteredInSubNet",
        "The caller is requesting registering a neuron which already exists in the active set.",
    ),
    ("0x16000000", "NewHotKeyIsSameWithOld", "The new hotkey is the same as old one"),
    (
        "0x17000000",
        "NewHotKeyNotCleanForRootSwap",
        "The new hotkey has outstanding root claimable or non-zero root stake,\nso the root rate-book cannot be merged without misallocating dividends.",
    ),
    ("0x18000000", "InvalidWorkBlock", "The supplied PoW hash block is in the future or negative."),
    ("0x19000000", "InvalidDifficulty", "The supplied PoW hash block does not meet the network difficulty."),
    ("0x1a000000", "InvalidSeal", "The supplied PoW hash seal does not match the supplied work."),
    (
        "0x1b000000",
        "MaxWeightExceeded",
        "The dispatch is attempting to set weights on chain with weight value exceeding the\nconfigured max weight limit (currently `u16::MAX`).",
    ),
    (
        "0x1c000000",
        "HotKeyAlreadyDelegate",
        "The hotkey is attempting to become a delegate when the hotkey is already a delegate.",
    ),
    ("0x1d000000", "SettingWeightsTooFast", "A transactor exceeded the rate limit for setting weights."),
    (
        "0x1e000000",
        "IncorrectWeightVersionKey",
        "A validator is attempting to set weights from a validator with incorrect weight version.",
    ),
    (
        "0x1f000000",
        "ServingRateLimitExceeded",
        "An axon or prometheus serving exceeded the rate limit for a registered neuron.",
    ),
    (
        "0x20000000",
        "UidsLengthExceedUidsInSubNet",
        "The caller is attempting to set weights with more UIDs than allowed.",
    ),
    ("0x21000000", "NetworkTxRateLimitExceeded", "A transactor exceeded the rate limit for add network transaction."),
    ("0x22000000", "DelegateTxRateLimitExceeded", "A transactor exceeded the rate limit for delegate transaction."),
    (
        "0x23000000",
        "HotKeySetTxRateLimitExceeded",
        "A transactor exceeded the rate limit for setting or swapping hotkey.",
    ),
    ("0x24000000", "StakingRateLimitExceeded", "A transactor exceeded the rate limit for staking."),
    ("0x25000000", "SubNetRegistrationDisabled", "Registration is disabled."),
    (
        "0x26000000",
        "TooManyRegistrationsThisInterval",
        "The number of registration attempts exceeded the allowed number in the interval.",
    ),
    ("0x27000000", "TransactorAccountShouldBeHotKey", "The hotkey is required to be the origin."),
    ("0x28000000", "FaucetDisabled", "Faucet is disabled."),
    ("0x29000000", "NotSubnetOwner", "Not a subnet owner."),
    ("0x2a000000", "RegistrationNotPermittedOnRootSubnet", "Operation is not permitted on the root subnet."),
    ("0x2b000000", "StakeTooLowForRoot", "A hotkey with too little stake is attempting to join the root subnet."),
    ("0x2c000000", "AllNetworksInImmunity", "All subnets are in the immunity period."),
    ("0x2d000000", "NotEnoughBalanceToPaySwapHotKey", "Not enough balance to pay swapping hotkey."),
    ("0x2e000000", "NotRootSubnet", "Netuid does not match for setting root network weights."),
    ("0x2f000000", "CanNotSetRootNetworkWeights", "Can not set weights for the root network."),
    ("0x30000000", "NoNeuronIdAvailable", "No neuron ID is available."),
    ("0x31000000", "DelegateTakeTooLow", "Delegate take is too low."),
    ("0x32000000", "DelegateTakeTooHigh", "Delegate take is too high."),
    (
        "0x33000000",
        "NoWeightsCommitFound",
        "No commit found for the provided hotkey+netuid combination when attempting to reveal the\nweights.",
    ),
    ("0x34000000", "InvalidRevealCommitHashNotMatch", "Committed hash does not equal the hashed reveal data."),
    ("0x35000000", "CommitRevealEnabled", "Attempting to call set_weights when commit/reveal is enabled"),
    ("0x36000000", "CommitRevealDisabled", "Attempting to commit/reveal weights when disabled."),
    ("0x37000000", "LiquidAlphaDisabled", "Attempting to set alpha high/low while disabled"),
    ("0x38000000", "AlphaHighTooLow", "Alpha high is too low: alpha_high > 0.8"),
    ("0x39000000", "AlphaLowOutOfRange", "Alpha low is out of range: alpha_low > 0 && alpha_low < 0.8"),
    ("0x3a000000", "ColdKeyAlreadyAssociated", "The coldkey has already been swapped"),
    ("0x3b000000", "NotEnoughBalanceToPaySwapColdKey", "The coldkey balance is not enough to pay for the swap"),
    ("0x3c000000", "InvalidChild", "Attempting to set an invalid child for a hotkey on a network."),
    ("0x3d000000", "DuplicateChild", "Duplicate child when setting children."),
    ("0x3e000000", "ProportionOverflow", "Proportion overflow when setting children."),
    ("0x3f000000", "TooManyChildren", "Too many children MAX 5."),
    ("0x40000000", "TxRateLimitExceeded", "Default transaction rate limit exceeded."),
    ("0x41000000", "ColdkeySwapAnnouncementNotFound", "Coldkey swap announcement not found"),
    ("0x42000000", "ColdkeySwapTooEarly", "Coldkey swap too early."),
    ("0x43000000", "ColdkeySwapReannouncedTooEarly", "Coldkey swap reannounced too early."),
    (
        "0x44000000",
        "AnnouncedColdkeyHashDoesNotMatch",
        "The announced coldkey hash does not match the new coldkey hash.",
    ),
    ("0x45000000", "ColdkeySwapAlreadyDisputed", "Coldkey swap already disputed"),
    ("0x46000000", "NewColdKeyIsHotkey", "New coldkey is hotkey"),
    ("0x47000000", "InvalidChildkeyTake", "Childkey take is invalid."),
    ("0x48000000", "TxChildkeyTakeRateLimitExceeded", "Childkey take rate limit exceeded."),
    ("0x49000000", "InvalidIdentity", "Invalid identity."),
    ("0x4a000000", "MechanismDoesNotExist", "Subnet mechanism does not exist."),
    ("0x4b000000", "StakeUnavailable", "Trying to unstake or re-lock the locked amount."),
    ("0x4c000000", "SubnetNotExists", "Trying to perform action on non-existent subnet."),
    ("0x4d000000", "TooManyUnrevealedCommits", "Maximum commit limit reached"),
    ("0x4e000000", "ExpiredWeightCommit", "Attempted to reveal weights that are expired."),
    ("0x4f000000", "RevealTooEarly", "Attempted to reveal weights too early."),
    ("0x50000000", "InputLengthsUnequal", "Attempted to batch reveal weights with mismatched vector input lengths."),
    ("0x51000000", "CommittingWeightsTooFast", "A transactor exceeded the rate limit for setting weights."),
    ("0x52000000", "AmountTooLow", "Stake amount is too low."),
    ("0x53000000", "InsufficientLiquidity", "Not enough liquidity."),
    ("0x54000000", "SlippageTooHigh", "Slippage is too high for the transaction."),
    ("0x55000000", "TransferDisallowed", "Subnet disallows transfer."),
    ("0x56000000", "ActivityCutoffTooLow", "Activity cutoff is being set too low."),
    ("0x57000000", "CallDisabled", "Call is disabled"),
    ("0x58000000", "FirstEmissionBlockNumberAlreadySet", "FirstEmissionBlockNumber is already set."),
    ("0x59000000", "NeedWaitingMoreBlocksToStarCall", "need wait for more blocks to accept the start call extrinsic."),
    ("0x5a000000", "NotEnoughAlphaOutToRecycle", "Not enough AlphaOut on the subnet to recycle"),
    ("0x5b000000", "CannotBurnOrRecycleOnRootSubnet", "Cannot burn or recycle TAO from root subnet"),
    ("0x5c000000", "UnableToRecoverPublicKey", "Public key cannot be recovered."),
    ("0x5d000000", "InvalidRecoveredPublicKey", "Recovered public key is invalid."),
    ("0x5e000000", "SubtokenDisabled", "SubToken disabled now"),
    ("0x5f000000", "HotKeySwapOnSubnetIntervalNotPassed", "Too frequent hotkey swap on subnet"),
    ("0x60000000", "SameNetuid", "Invalid netuid duplication"),
    ("0x61000000", "InsufficientBalance", "The caller does not have enough balance for the operation."),
    ("0x62000000", "InvalidLeaseBeneficiary", "Invalid lease beneficiary to register the leased network."),
    ("0x63000000", "LeaseCannotEndInThePast", "Lease cannot end in the past."),
    ("0x64000000", "LeaseNetuidNotFound", "Couldn't find the lease netuid."),
    ("0x65000000", "LeaseDoesNotExist", "Lease does not exist."),
    ("0x66000000", "LeaseHasNoEndBlock", "Lease has no end block."),
    ("0x67000000", "LeaseHasNotEnded", "Lease has not ended."),
    ("0x68000000", "Overflow", "An overflow occurred."),
    ("0x69000000", "BeneficiaryDoesNotOwnHotkey", "Beneficiary does not own hotkey."),
    ("0x6a000000", "ExpectedBeneficiaryOrigin", "Expected beneficiary origin."),
    (
        "0x6b000000",
        "AdminActionProhibitedDuringWeightsWindow",
        "Admin operation is prohibited during the protected weights window",
    ),
    ("0x6c000000", "SymbolDoesNotExist", "Symbol does not exist."),
    ("0x6d000000", "SymbolAlreadyInUse", "Symbol already in use."),
    ("0x6e000000", "IncorrectCommitRevealVersion", "Incorrect commit-reveal version."),
    ("0x6f000000", "InvalidRevealRound", "Reveal round is older than the most recently stored DRAND round."),
    ("0x70000000", "RevealPeriodTooLarge", "Reveal period is too large."),
    ("0x71000000", "RevealPeriodTooSmall", "Reveal period is too small."),
    ("0x72000000", "InvalidValue", "Generic error for out-of-range parameter value"),
    ("0x73000000", "SubnetLimitReached", "Subnet limit reached & there is no eligible subnet to prune"),
    ("0x74000000", "CannotAffordLockCost", "Insufficient funds to meet the subnet lock cost"),
    ("0x75000000", "EvmKeyAssociateRateLimitExceeded", "exceeded the rate limit for associating an EVM key."),
    ("0x76000000", "SameAutoStakeHotkeyAlreadySet", "Same auto stake hotkey already set"),
    ("0x77000000", "UidMapCouldNotBeCleared", "The UID map for the subnet could not be cleared"),
    ("0x78000000", "TrimmingWouldExceedMaxImmunePercentage", "Trimming would exceed the max immune neurons percentage"),
    ("0x79000000", "ChildParentInconsistency", "Violating the rules of Childkey-Parentkey consistency"),
    ("0x7a000000", "InvalidNumRootClaim", "Invalid number of root claims"),
    ("0x7b000000", "InvalidRootClaimThreshold", "Invalid value of root claim threshold"),
    ("0x7c000000", "InvalidSubnetNumber", "Exceeded subnet limit number or zero."),
    ("0x7d000000", "TooManyUIDsPerMechanism", "The maximum allowed UIDs times mechanism count should not exceed 256."),
    ("0x7e000000", "VotingPowerTrackingNotEnabled", "Voting power tracking is not enabled for this subnet."),
    ("0x7f000000", "InvalidVotingPowerEmaAlpha", "Invalid voting power EMA alpha value (must be <= 10^18)."),
    ("0x80000000", "Deprecated", "Deprecated call."),
    ("0x81000000", "AddStakeBurnRateLimitExceeded", '\\"Add stake and burn\\" exceeded the operation rate limit'),
    ("0x82000000", "ColdkeySwapAnnounced", "A coldkey swap has been announced for this account."),
    ("0x83000000", "ColdkeySwapDisputed", "A coldkey swap for this account is under dispute."),
    ("0x84000000", "ColdkeySwapClearTooEarly", "Coldkey swap clear too early."),
    ("0x85000000", "DisabledTemporarily", "Disabled temporarily."),
    ("0x86000000", "RegistrationPriceLimitExceeded", "Registration Price Limit Exceeded"),
    ("0x87000000", "LockHotkeyMismatch", "Lock hotkey mismatch: existing lock is for a different hotkey."),
    ("0x88000000", "InsufficientStakeForLock", "Insufficient stake on subnet to cover the lock amount."),
    ("0x89000000", "NoExistingLock", "No existing lock found for the given coldkey and subnet."),
    ("0x8a000000", "ActiveLockExists", "There is already an active lock for the given coldkey."),
    ("0x8b000000", "CannotUseSystemAccount", "A system account cannot be used in this operation"),
    ("0x8c000000", "UnlockAmountTooHigh", "Trying to unlock more than locked"),
    ("0x8d000000", "TempoOutOfBounds", "The supplied tempo is outside the allowed range."),
    (
        "0x8e000000",
        "ActivityCutoffFactorMilliOutOfBounds",
        "The supplied activity-cutoff factor is outside the allowed range.",
    ),
    (
        "0x8f000000",
        "EpochTriggerAlreadyPending",
        "An epoch trigger is already pending for this subnet; wait for it to fire\nbefore triggering again.",
    ),
    (
        "0x90000000",
        "AutoEpochAlreadyImminent",
        "The next automatic epoch is already imminent; a manual trigger would have\nno effect.",
    ),
    (
        "0x91000000",
        "DynamicTempoBlockedByCommitReveal",
        "`trigger_epoch` is blocked because commit-reveal is enabled for this subnet:\nan out-of-band epoch would desync the CRv3 reveal window from the wall-clock\nDrand schedule and silently drop committed weights.",
    ),
    ("0x92000000", "AccountRejectsLockedAlpha", "The destination coldkey rejects incoming locked alpha."),
]

SUBTENSOR_PALLET_INDEX = 7


def seed_errors(apps, schema_editor):
    SubtensorErrorCode = apps.get_model("extrinsics", "SubtensorErrorCode")
    rows = [
        SubtensorErrorCode(
            pallet_index=SUBTENSOR_PALLET_INDEX,
            error_code=code,
            name=name,
            category="",
            description=description,
            remediation="",
        )
        for code, name, description in ERRORS
    ]
    SubtensorErrorCode.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["pallet_index", "error_code"],
        update_fields=["name", "category", "description", "remediation"],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("extrinsics", "0012_alter_subtensorerrorcode_id"),
    ]

    operations = [
        migrations.RunPython(seed_errors, reverse_code=migrations.RunPython.noop),
    ]
