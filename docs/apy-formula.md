# Validator APY — formula reference

How Sentinel Tower computes per-validator APY for Bittensor subnets, what each
input means, and where the values come from.

## Formula

Two related APYs answer different questions; the dashboard shows both:

```
delegator_apy% = dividend × (alpha_out_emission / total_stake) × (1 − owner_cut) × 0.5 × BLOCKS_PER_YEAR × 100
alpha_only_apy% = dividend × (alpha_out_emission / alpha_stake) × (1 − owner_cut) × 0.5 × BLOCKS_PER_YEAR × 100
```

`BLOCKS_PER_YEAR = 2_629_800` — derived from `31_557_600 s/yr ÷ 12 s/block` (Julian year, 12-second blocks).

The two views differ only in the denominator:

- **Delegator view (`total_stake`):** What a delegator's TAO-equivalent stake earns. Matches taostats' convention; comparable across validators regardless of alpha-vs-root mix. See [Why two denominators](#why-two-denominators) below.
- **Alpha-only view (`alpha_stake`):** Yield on alpha exposure only. Higher for root-heavy validators (rewards attributed to a small alpha base); useful when reasoning about alpha-denominated returns.

Both produce per-validator, per-block APY at a single snapshot. Dashboards average per-block APY over a time window (1h / 1d / 1w / 1m).

## Inputs

| Symbol | Meaning | DB column | Unit | Source |
|---|---|---|---|---|
| `dividend` | Validator's share of the subnet's dividend pool at this block, normalised to `[0, 1]` and summing to ~1 across the subnet's validators | `metagraph_mechanism_metrics.dividend` (per `(snapshot, mech_id)`) | dimensionless | `metagraph.dividends[i]` per mechanism |
| `alpha_out_emission` | Per-block alpha emission of the subnet, in TAO equivalent | `metagraph_subnet.alpha_out_emission`; dashboards fall back to `1e9` rao (= 1 TAO/block) when the column is `0` — see [Fallback for `alpha_out_emission`](#fallback-for-alpha_out_emission) | rao (after `_to_rao()`); on chain it's TAO | `metagraph.emissions.alpha_out_emission` |
| `total_stake` | Validator's total effective stake (alpha + root TAO equivalent) | `metagraph_neuron_snapshot.total_stake` (per `(block, neuron)`) | rao | `metagraph.S[i]` |
| `owner_cut` | Fraction the subnet owner skims before the validator/miner split | `metagraph_subnet.owner_cut` | `[0, 1]` | not synced from chain today; falls back to `settings.SUBNET_OWNER_CUT = 0.09` for every subnet |
| `0.5` | Validator/miner split (chain constant) | — | — | encoded by Yuma consensus, applied after the owner cut |

The `alpha_out_emission / total_stake` ratio is unit-safe: both sides are stored in rao, so the rao→TAO conversion factor (10⁹) cancels.

## Why two denominators

In dynamic TAO, a validator's effective consensus stake is `alpha_stake + tao_weight × root_stake` (with `tao_weight ≈ 0.18`). Their dividend share reflects that effective stake — but the rewards are paid in alpha and accrue to the hotkey regardless of which staking source backed them.

This means there are two valid questions, and the dashboard answers both:

- **Delegator view (divide by `total_stake`)** — "what does a TAO-equivalent staker earn here?" Aligns with [taostats' convention][taostats]; APYs are in the same range across validators with similar consensus performance regardless of their alpha-vs-root mix.
- **Alpha-only view (divide by `alpha_stake`)** — "what does my alpha stake earn here?" Validators with significant root TAO stake show *inflated* APYs vs. the delegator view — that's intentional: rewards (paid in alpha) divided by a smaller alpha base. Useful for alpha-denominated yield comparisons.

For a validator with no root stake, the two views collapse to the same number. The bigger the root component, the more they diverge.

## What the formula does **not** account for

These are deliberate omissions worth knowing about:

- **Validator take (commission).** Per-hotkey on chain. Not collected today. To compute *delegator-net* APY rather than gross, multiply by `(1 − validator_take)`. Historically capped at ~0.18; varies per validator.
- **Per-subnet `owner_cut`.** We use a constant `0.09` for every subnet. Real per-subnet cuts vary; absolute APY is biased per-subnet, relative ranking inside a subnet is fine.
- **Historical accuracy of `alpha_out_emission` and `owner_cut`.** Both stored as a single mutable column on `metagraph_subnet`, overwritten on every sync. APYs computed for past blocks use *today's* emission, not the emission that was actually in effect at that block. For windows < a few weeks the error is small; for multi-month windows it can be material.
- **Multi-mechanism subnets.** The dashboard joins `mech_id = 0`. For subnets with >1 mechanism whose dividends are split across them, this under-counts. Most subnets run one mechanism today.

## Practical observations on the inputs

- **`alpha_out_emission` is effectively a chain constant.** For active subnets in dynamic TAO it's `1.0 TAO/block`; for halted/dissolved subnets it's `0`. We verified this across multiple netuids and historical offsets; it does not vary materially per subnet or over time.
- **`dividend` is stored normalised** (`0..1`) on prod. The dashboard's `CASE WHEN mm.dividend > 1 THEN mm.dividend / 65535.0` guard handles the raw-u16 edge case (some SDK paths return `[0, 65535]`) but is a no-op against current data.
- **`is_validator = true` filter** is required: only validators (not miners) earn dividends.

### Fallback for `alpha_out_emission`

Both dashboard panels evaluate `COALESCE(NULLIF(s.alpha_out_emission, 0), 1e9)` instead of using the column directly. The reason is operational:

- `Subnet.alpha_out_emission` is a single mutable column, populated by `MetagraphSyncService` only when the SDK returns a non-zero value (`if alpha_out_emission_rao and ...`).
- The historical-backfill code path hits an upstream Bittensor SDK bug on every block and falls back to a legacy workaround that calls `get_metagraph_info` without `block=`. When `get_metagraph_info` returns `None` or its result fails to apply, `metagraph.emissions` stays empty and `_read_alpha_out_emission` returns `0` — which the sync then refuses to write. Result: the column stays at `0` indefinitely on backfill-only deployments.
- Since the value is a chain invariant (`1 TAO/block` for active subnets), the dashboard substitutes `1e9` rao when the column is `0`. This keeps the panel useful without depending on the column being correctly populated.

For halted/dissolved subnets the column may legitimately be `0`, but those subnets have no validator earning activity anyway, so the substituted value doesn't change the dashboard output meaningfully.

## Reading the dashboard

Two panels share the same shape; they differ only in denominator:

- **"Subnet Validators APY (delegator view / total stake)"** — divides by `total_stake`. Use this for taostats-style cross-validator comparison.
- **"Subnet Validators APY (alpha-only view / yield on alpha exposure)"** — divides by `alpha_stake`. Use this for alpha-denominated yield.

Each panel computes per-block APY for every snapshot in the last month, then aggregates with `AVG(...) FILTER (WHERE block_ts >= start_NN)` to produce 1h / 1d / 1w / 1m windows. Each row is one validator on the selected subnet. Sort defaults to alpha stake descending.

A 0% APY row means either no `dividend > 0` rows in the window (validator wasn't earning during the period) or the denominator (`total_stake` or `alpha_stake` depending on view) is `0`. A non-zero APY in the 50–200% range is typical for an active dTAO subnet in the delegator view — alpha emission is high relative to total subnet stake and that's by design. The alpha-only view will sit higher for root-heavy validators.

## Sanity-check against external data

To validate the formula against an external reference, compute APY for a few well-known validators on a busy subnet and compare with [taostats' validator APY][taostats]. They should agree within a few % relative; systematic discrepancy points at the missing `validator_take`, the hardcoded `owner_cut`, or a normalisation issue.

## Related models / files

- `apps.metagraph.models.NeuronSnapshot` — `alpha_stake`, `total_stake` per (block, neuron)
- `apps.metagraph.models.MechanismMetrics` — `dividend` per (snapshot, mech_id)
- `apps.metagraph.models.Subnet` — `alpha_out_emission`, `owner_cut`
- `apps.metagraph.services.metagraph_sync_service.MetagraphSyncService` — writes the snapshot fields each block
- `grafana/provisioning/dashboards/subnet-apy.json` — the live "Subnet Validators APY" panel that implements this formula

[taostats]: https://docs.taostats.io/docs/some-of-the-math-behind-taostats
