# Subtensor Validator APY — Formula & Definitions

Self-contained reference for **how validator/staker APY is computed** on Subtensor
(dTAO era) and the on-chain data points it depends on. Collection/infrastructure
details live separately in [historical-apy-collection-requirements.md](historical-apy-collection-requirements.md).

---

## TL;DR

Per epoch, a staker's return is `dividends_earned / stake`. Dividends are
auto-re-staked, so the annualized figure compounds:

```
r_epoch = alpha_earned / alpha_staked                       # net return for one epoch

APY  = (∏ over the year (1 + r_epoch)) − 1                   # compounded (what we report)
APR  = (Σ r_epoch) × (seconds_per_year / period_seconds)    # linear (reference only)
```

Use **APY**. `alpha_earned` is already **net** of subnet-owner cut and validator
(delegate) take — no extra multipliers (see [Net vs. gross](#net-vs-gross)).

---

## Data points

Each is a per-epoch, per-hotkey value unless noted. "Source" is the chain storage
item (dTAO era).

| Symbol | Meaning | Source | Units |
|---|---|---|---|
| `alpha_earned` | Net dividends distributed to this hotkey's nominators this epoch | `AlphaDividendsPerSubnet[(netuid, hotkey)]` (= metagraph index 71) | rao (1e-9 alpha) |
| `alpha_staked` | Stake base the dividend was computed against | `TotalHotkeyAlphaLastEpoch[(hotkey, netuid)]` | rao |
| `tempo` | Epoch length parameter | `Tempo[netuid]` | blocks |
| `moving_price` | Alpha→TAO price (only for TAO-denominated APY) | `MovingPrice[netuid]` | TAO/alpha |
| `owner_cut` | Subnet-owner cut fraction (already applied in `alpha_earned`) | `SubnetOwnerCut / 65535` | 0–1 |
| `hotkey_take` | Validator/delegate take fraction (already applied in `alpha_earned`) | `Delegates[hotkey] / 65535` | 0–1 |

`owner_cut` and `hotkey_take` are **not** needed to compute APY from `alpha_earned`
(they're already deducted). Record them only for reproducibility / reconstructing
gross figures.

---

## Per-epoch return

```
r_epoch = alpha_earned / alpha_staked
```

- The return is denominated in **alpha** (the subnet token), not TAO/USD.
- `alpha_staked` is the **last-epoch stake snapshot** (`TotalHotkeyAlphaLastEpoch`,
  set at `run_coinbase.rs:606-607`) — the exact base the chain used, preferable to
  "stake at query time".
- Guard `alpha_staked == 0` (registration edge) → treat `r_epoch = 0`.

### Epoch timing

```
period_blocks   = tempo + 1
epoch_seconds   = (tempo + 1) × 12      # block time = 12s
```

An epoch fires when `(block + netuid + 1) % (tempo + 1) == tempo`
(`run_coinbase.rs:946`). `AlphaDividendsPerSubnet` is cleared and rewritten each
epoch, so it holds **only the latest epoch's** value — every epoch is a distinct
data point and cannot be recovered later if skipped.

---

## APY (compounded — the reported figure)

Dividends are re-staked each epoch, so returns compound. Over an arbitrary window:

```
window_growth = ∏ over epochs in window (1 + r_epoch) − 1     # realized growth
APY%          = ((1 + window_growth) ^ (seconds_per_year / window_seconds) − 1) × 100
```

- `window_seconds = Σ epoch_seconds` over the epochs in the window.
- The annualization exponent `seconds_per_year / window_seconds` rescales any
  window (hourly / daily / monthly) to a full year — change only the grouping.
- Numerically use `exp(Σ ln(1 + r_epoch))` for the product.

## APR (linear — reference / sanity check only)

```
APR% = (Σ alpha_earned / avg(alpha_staked)) × (seconds_per_year / Σ period_seconds) × 100
```

No compounding. Always ≤ APY. Keep it only to show the compounding gap.

---

## Net vs. gross

This is the one detail that's easy to get wrong.

Per block the chain splits each subnet's `alpha_out` emission
(`run_coinbase.rs:184-218`):

```
owner_cut  = alpha_out × (SubnetOwnerCut / 65535)     # to subnet owner
remaining  = alpha_out − owner_cut
validators = remaining × 0.5                          # dividend pool (0.5 is hardcoded)
miners     = remaining × 0.5                          # incentive pool
```

Then, distributing the validator pool to each hotkey, the **delegate take** is
removed and credited to the validator's own coldkey; the rest goes to nominators
(`run_coinbase.rs:585-602`):

```
validator_take = hotkey_pool × (Delegates[hotkey] / 65535)
nominator_pool = hotkey_pool − validator_take
```

**`AlphaDividendsPerSubnet` (index 71) records the `nominator_pool` — net of both
owner cut and validator take** (`rpc_info/metagraph.rs:649`). So:

| `alpha_earned` source | owner cut | delegate take | correction needed |
|---|---|---|---|
| `AlphaDividendsPerSubnet` (dTAO era) | already applied | already applied | **none** |
| reconstructed from normalized scores (pre-dTAO) | no | no | `× (1 − owner_cut) × 0.5 × (1 − hotkey_take)` |

Do **not** apply the correction factors to dTAO-era data — it double-counts.

### `(1 − owner_cut) × 0.5 = 0.41` shortcut

Valid only as today's default: `SubnetOwnerCut` is **chain-configurable storage**
(default `11_796 / 65535 = 0.18`, settable via governance), so `(1 − 0.18) × 0.5 = 0.41`.
The `0.5` is hardcoded. For historical accuracy in the reconstruction path, read
`SubnetOwnerCut` per block rather than hardcoding `0.41`.

---

## Constants

| Constant | Value | Note |
|---|---|---|
| Block time | 12 s | |
| `seconds_per_year` | 31_557_600 | 365.25 days |
| `blocks_per_year` | 2_629_800 | 31_557_600 / 12 |
| u16 normalization | 65535 | for `SubnetOwnerCut`, `Delegates`, `Dividends` |

---

## Notes / caveats

- **Denomination:** APY above is in **alpha**. For TAO-denominated APY, weight each
  epoch's earned/staked alpha by `moving_price` (alpha→TAO) at that epoch.
  Pre-dTAO blocks have no `moving_price`.
- **Per-validator vs per-nominator:** `alpha_earned` is the nominators' net pool.
  A specific delegator earns their pro-rata share of it; the validator-operator
  additionally receives `validator_take`.
- **Configurable parameters:** `owner_cut` and `hotkey_take` can change over time;
  for long historical windows read them per block if you need exact reconstruction.
- **Sampling:** because the dividend storage is overwritten each epoch, a true APY
  needs every epoch. Sampling (e.g. one epoch/day) yields only an approximation.
