"""Seed `subtensor_error_codes` with the full SubtensorModule error enum.

Source: the authoritative `errors` mapping in `set-weights.md`, which mirrors
the SCALE variant ordering in `pallets/subtensor/src/macros/errors.rs`. This
supersedes the empirical seed in 0009 — notably correcting `0x1d000000` from
the guessed `CommitRevealEnabled` to the actual `IncorrectWeightVersionKey`,
and adding the correct `CommitRevealEnabled` entry at `0x34000000`.

All 135 variants are inserted with `pallet_index = 7` (SubtensorModule).
`category` and `remediation` are left blank — populate them in follow-up
migrations as operator guidance is curated.

Conflict policy: `bulk_create(update_conflicts=True)` overwrites name,
category, description, and remediation on `(pallet_index, error_code)`
collision. This wipes the curated remediation in 0009 for `0x1d000000`,
which was attached to the wrong error name.
"""

from django.db import migrations


ERRORS: list[tuple[str, str, str]] = [
    ("0x00000000", "RootNetworkDoesNotExist", "The root network does not exist."),
    ("0x01000000", "InvalidIpType", "The user is trying to serve an axon which is not of type 4 (IPv4) or 6 (IPv6)."),
    ("0x02000000", "InvalidIpAddress", "An invalid IP address is passed to the serve function."),
    ("0x03000000", "InvalidPort", "An invalid port is passed to the serve function."),
    ("0x04000000", "HotKeyNotRegisteredInSubNet", "The hotkey is not registered in subnet."),
    ("0x05000000", "HotKeyAccountNotExists", "The hotkey does not exist."),
    ("0x06000000", "HotKeyNotRegisteredInNetwork", "The hotkey is not registered in any subnet."),
    ("0x07000000", "NonAssociatedColdKey", "Stake/unstake/subscribe by a coldkey not associated with the hotkey."),
    ("0x08000000", "NotEnoughStake", "The caller does not have enough stake to perform this action."),
    ("0x09000000", "NotEnoughStakeToWithdraw", "Removing more stake than exists in the staking account."),
    ("0x0a000000", "NotEnoughStakeToSetWeights", "Caller has less than WeightsMinStake required to set weights."),
    ("0x0b000000", "NotEnoughStakeToSetChildkeys", "The parent hotkey doesn't have enough own stake to set childkeys."),
    ("0x0c000000", "NotEnoughBalanceToStake", "Adding more stake than exists in the coldkey account."),
    ("0x0d000000", "BalanceWithdrawalError", "Requested amount could not be withdrawn from the coldkey account."),
    ("0x0e000000", "ZeroBalanceAfterWithdrawn", "Withdrawal would leave a zero balance and prevent account existence."),
    ("0x0f000000", "NeuronNoValidatorPermit", "Setting non-self weights without a permitted validator."),
    ("0x10000000", "WeightVecNotEqualSize", "Weight keys and values vectors have different sizes."),
    ("0x11000000", "DuplicateUids", "Duplicate UIDs in the weight matrix."),
    ("0x12000000", "UidVecContainInvalidOne", "At least one UID in the weight vector does not exist in the metagraph."),
    ("0x13000000", "WeightVecLengthIsLow", "Setting weights with fewer elements than allowed."),
    ("0x14000000", "TooManyRegistrationsThisBlock", "Registrations in this block exceed max_regs_per_block."),
    ("0x15000000", "HotKeyAlreadyRegisteredInSubNet", "Registering a neuron that already exists in the active set."),
    ("0x16000000", "NewHotKeyIsSameWithOld", "The new hotkey is the same as the old one."),
    ("0x17000000", "InvalidWorkBlock", "The supplied PoW hash block is in the future or negative."),
    ("0x18000000", "InvalidDifficulty", "The supplied PoW hash block does not meet network difficulty."),
    ("0x19000000", "InvalidSeal", "The supplied PoW hash seal does not match the supplied work."),
    ("0x1a000000", "MaxWeightExceeded", "Weight value exceeds the configured max weight limit (u16::MAX)."),
    ("0x1b000000", "HotKeyAlreadyDelegate", "Hotkey is becoming a delegate but is already a delegate."),
    ("0x1c000000", "SettingWeightsTooFast", "Transactor exceeded the rate limit for setting weights."),
    ("0x1d000000", "IncorrectWeightVersionKey", "Validator is setting weights with an incorrect weight version key."),
    ("0x1e000000", "ServingRateLimitExceeded", "Axon/prometheus serving exceeded the rate limit for a registered neuron."),
    ("0x1f000000", "UidsLengthExceedUidsInSubNet", "Setting weights with more UIDs than allowed."),
    ("0x20000000", "NetworkTxRateLimitExceeded", "Transactor exceeded the rate limit for add network transaction."),
    ("0x21000000", "DelegateTxRateLimitExceeded", "Transactor exceeded the rate limit for delegate transaction."),
    ("0x22000000", "HotKeySetTxRateLimitExceeded", "Transactor exceeded rate limit for setting/swapping hotkey."),
    ("0x23000000", "StakingRateLimitExceeded", "Transactor exceeded the rate limit for staking."),
    ("0x24000000", "SubNetRegistrationDisabled", "Registration is disabled."),
    ("0x25000000", "TooManyRegistrationsThisInterval", "Registration attempts exceeded the allowed number in the interval."),
    ("0x26000000", "TransactorAccountShouldBeHotKey", "The hotkey is required to be the origin."),
    ("0x27000000", "FaucetDisabled", "Faucet is disabled."),
    ("0x28000000", "NotSubnetOwner", "Caller is not the subnet owner."),
    ("0x29000000", "RegistrationNotPermittedOnRootSubnet", "Operation is not permitted on the root subnet."),
    ("0x2a000000", "StakeTooLowForRoot", "A hotkey with too little stake is attempting to join the root subnet."),
    ("0x2b000000", "AllNetworksInImmunity", "All subnets are in the immunity period."),
    ("0x2c000000", "NotEnoughBalanceToPaySwapHotKey", "Not enough balance to pay swapping hotkey."),
    ("0x2d000000", "NotRootSubnet", "Netuid does not match for setting root network weights."),
    ("0x2e000000", "CanNotSetRootNetworkWeights", "Cannot set weights for the root network."),
    ("0x2f000000", "NoNeuronIdAvailable", "No neuron ID is available."),
    ("0x30000000", "DelegateTakeTooLow", "Delegate take is too low."),
    ("0x31000000", "DelegateTakeTooHigh", "Delegate take is too high."),
    ("0x32000000", "NoWeightsCommitFound", "No commit found for the hotkey+netuid when revealing weights."),
    ("0x33000000", "InvalidRevealCommitHashNotMatch", "Committed hash does not equal the hashed reveal data."),
    ("0x34000000", "CommitRevealEnabled", "Calling set_weights while commit/reveal is enabled."),
    ("0x35000000", "CommitRevealDisabled", "Committing/revealing weights while disabled."),
    ("0x36000000", "LiquidAlphaDisabled", "Setting alpha high/low while disabled."),
    ("0x37000000", "AlphaHighTooLow", "Alpha high is too low: alpha_high > 0.8 required."),
    ("0x38000000", "AlphaLowOutOfRange", "Alpha low is out of range: 0 < alpha_low < 0.8 required."),
    ("0x39000000", "ColdKeyAlreadyAssociated", "The coldkey has already been swapped."),
    ("0x3a000000", "NotEnoughBalanceToPaySwapColdKey", "The coldkey balance is not enough to pay for the swap."),
    ("0x3b000000", "InvalidChild", "Setting an invalid child for a hotkey on a network."),
    ("0x3c000000", "DuplicateChild", "Duplicate child when setting children."),
    ("0x3d000000", "ProportionOverflow", "Proportion overflow when setting children."),
    ("0x3e000000", "TooManyChildren", "Too many children (max 5)."),
    ("0x3f000000", "TxRateLimitExceeded", "Default transaction rate limit exceeded."),
    ("0x40000000", "ColdkeySwapAnnouncementNotFound", "Coldkey swap announcement not found."),
    ("0x41000000", "ColdkeySwapTooEarly", "Coldkey swap too early."),
    ("0x42000000", "ColdkeySwapReannouncedTooEarly", "Coldkey swap reannounced too early."),
    ("0x43000000", "AnnouncedColdkeyHashDoesNotMatch", "The announced coldkey hash does not match the new coldkey hash."),
    ("0x44000000", "ColdkeySwapAlreadyDisputed", "Coldkey swap already disputed."),
    ("0x45000000", "NewColdKeyIsHotkey", "New coldkey is a hotkey."),
    ("0x46000000", "InvalidChildkeyTake", "Childkey take is invalid."),
    ("0x47000000", "TxChildkeyTakeRateLimitExceeded", "Childkey take rate limit exceeded."),
    ("0x48000000", "InvalidIdentity", "Invalid identity."),
    ("0x49000000", "MechanismDoesNotExist", "Subnet mechanism does not exist."),
    ("0x4a000000", "CannotUnstakeLock", "Trying to unstake your lock amount."),
    ("0x4b000000", "SubnetNotExists", "Action attempted on non-existent subnet."),
    ("0x4c000000", "TooManyUnrevealedCommits", "Maximum commit limit reached."),
    ("0x4d000000", "ExpiredWeightCommit", "Attempted to reveal weights that are expired."),
    ("0x4e000000", "RevealTooEarly", "Attempted to reveal weights too early."),
    ("0x4f000000", "InputLengthsUnequal", "Batch reveal weights with mismatched vector input lengths."),
    ("0x50000000", "CommittingWeightsTooFast", "Transactor exceeded the rate limit for committing weights."),
    ("0x51000000", "AmountTooLow", "Stake amount is too low."),
    ("0x52000000", "InsufficientLiquidity", "Not enough liquidity."),
    ("0x53000000", "SlippageTooHigh", "Slippage is too high for the transaction."),
    ("0x54000000", "TransferDisallowed", "Subnet disallows transfer."),
    ("0x55000000", "ActivityCutoffTooLow", "Activity cutoff is being set too low."),
    ("0x56000000", "CallDisabled", "Call is disabled."),
    ("0x57000000", "FirstEmissionBlockNumberAlreadySet", "FirstEmissionBlockNumber is already set."),
    ("0x58000000", "NeedWaitingMoreBlocksToStarCall", "Need to wait for more blocks to accept the start call extrinsic."),
    ("0x59000000", "NotEnoughAlphaOutToRecycle", "Not enough AlphaOut on the subnet to recycle."),
    ("0x5a000000", "CannotBurnOrRecycleOnRootSubnet", "Cannot burn or recycle TAO from root subnet."),
    ("0x5b000000", "UnableToRecoverPublicKey", "Public key cannot be recovered."),
    ("0x5c000000", "InvalidRecoveredPublicKey", "Recovered public key is invalid."),
    ("0x5d000000", "SubtokenDisabled", "SubToken is disabled."),
    ("0x5e000000", "HotKeySwapOnSubnetIntervalNotPassed", "Too frequent hotkey swap on subnet."),
    ("0x5f000000", "ZeroMaxStakeAmount", "Zero max stake amount."),
    ("0x60000000", "SameNetuid", "Invalid netuid duplication."),
    ("0x61000000", "InsufficientBalance", "Caller does not have enough balance for the operation."),
    ("0x62000000", "StakingOperationRateLimitExceeded", "Too frequent staking operations."),
    ("0x63000000", "InvalidLeaseBeneficiary", "Invalid lease beneficiary to register the leased network."),
    ("0x64000000", "LeaseCannotEndInThePast", "Lease cannot end in the past."),
    ("0x65000000", "LeaseNetuidNotFound", "Couldn't find the lease netuid."),
    ("0x66000000", "LeaseDoesNotExist", "Lease does not exist."),
    ("0x67000000", "LeaseHasNoEndBlock", "Lease has no end block."),
    ("0x68000000", "LeaseHasNotEnded", "Lease has not ended."),
    ("0x69000000", "Overflow", "An overflow occurred."),
    ("0x6a000000", "BeneficiaryDoesNotOwnHotkey", "Beneficiary does not own hotkey."),
    ("0x6b000000", "ExpectedBeneficiaryOrigin", "Expected beneficiary origin."),
    ("0x6c000000", "AdminActionProhibitedDuringWeightsWindow", "Admin operation is prohibited during the protected weights window."),
    ("0x6d000000", "SymbolDoesNotExist", "Symbol does not exist."),
    ("0x6e000000", "SymbolAlreadyInUse", "Symbol already in use."),
    ("0x6f000000", "IncorrectCommitRevealVersion", "Incorrect commit-reveal version."),
    ("0x70000000", "RevealPeriodTooLarge", "Reveal period is too large."),
    ("0x71000000", "RevealPeriodTooSmall", "Reveal period is too small."),
    ("0x72000000", "InvalidValue", "Generic error for out-of-range parameter value."),
    ("0x73000000", "SubnetLimitReached", "Subnet limit reached and there is no eligible subnet to prune."),
    ("0x74000000", "CannotAffordLockCost", "Insufficient funds to meet the subnet lock cost."),
    ("0x75000000", "EvmKeyAssociateRateLimitExceeded", "Exceeded the rate limit for associating an EVM key."),
    ("0x76000000", "SameAutoStakeHotkeyAlreadySet", "Same auto stake hotkey already set."),
    ("0x77000000", "UidMapCouldNotBeCleared", "The UID map for the subnet could not be cleared."),
    ("0x78000000", "TrimmingWouldExceedMaxImmunePercentage", "Trimming would exceed the max immune neurons percentage."),
    ("0x79000000", "ChildParentInconsistency", "Violating the rules of childkey/parentkey consistency."),
    ("0x7a000000", "InvalidNumRootClaim", "Invalid number of root claims."),
    ("0x7b000000", "InvalidRootClaimThreshold", "Invalid value of root claim threshold."),
    ("0x7c000000", "InvalidSubnetNumber", "Exceeded subnet limit number or zero."),
    ("0x7d000000", "TooManyUIDsPerMechanism", "Maximum allowed UIDs times mechanism count exceeds 256."),
    ("0x7e000000", "VotingPowerTrackingNotEnabled", "Voting power tracking is not enabled for this subnet."),
    ("0x7f000000", "InvalidVotingPowerEmaAlpha", "Invalid voting power EMA alpha (must be <= 10^18)."),
    ("0x80000000", "PrecisionLoss", "Unintended precision loss when unstaking alpha."),
    ("0x81000000", "Deprecated", "Deprecated call."),
    ("0x82000000", "AddStakeBurnRateLimitExceeded", "Add-stake-and-burn exceeded the operation rate limit."),
    ("0x83000000", "ColdkeySwapAnnounced", "A coldkey swap has been announced for this account."),
    ("0x84000000", "ColdkeySwapDisputed", "A coldkey swap for this account is under dispute."),
    ("0x85000000", "ColdkeySwapClearTooEarly", "Coldkey swap clear too early."),
    ("0x86000000", "DisabledTemporarily", "Disabled temporarily."),
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
        ("extrinsics", "0009_subtensor_error_code"),
    ]

    operations = [
        migrations.RunPython(seed_errors, reverse_code=migrations.RunPython.noop),
    ]
