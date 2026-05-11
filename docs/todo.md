# TODO

## Seed remaining `subtensor_error_codes` entries

Migration `0009_subtensor_error_code` introduced the `subtensor_error_codes` lookup table powering the **Top Error Types** panel on the Weight Setting dashboard. Only the highest-confidence entry is seeded so far:

- `0x1d000000` → `CommitRevealEnabled`

The next-most-frequent codes still showing as raw hex in the panel:

| code | empirical narrowing (which dispatchables emit it) | candidate names from `set-weights.md` |
|---|---|---|
| `0x4d000000` | timelock only (`commit_timelocked_*`) | `TooManyUnrevealedCommits` or `CommitRevealV3Disabled` |
| `0x51000000` | timelock only | the other of the above pair |
| `0x04000000` | direct + timelock (shared check) | likely `NotRegistered` |
| `0x4a000000` | timelock-mechanism only | mechanism-specific check |
| `0x0a000000` | mechanism-direct only | likely `MechanismDoesNotExist` |
| `0x0f000000` | mechanism-direct only | unknown |
| `0x35000000` | mechanism-direct only (single occurrence) | unknown |

**Action:** confirm each variant index against `pallets/subtensor/src/errors.rs` in the [opentensor/subtensor](https://github.com/opentensor/subtensor) repo, then add a follow-up Django migration that `INSERT … ON CONFLICT … DO UPDATE`s each row. Once the bulk are seeded, consider promoting to **Option C** (decode at ingestion using runtime metadata) so new variants don't require a migration with each chain upgrade.

## Batch weight-setting extrinsics: per-subnet attribution

The `bittensor-metrics` Grafana dashboard ("Weight-Setting Calls Analysis" row) groups by `extrinsics.netuid`, but three of the twelve weight-setting dispatchables carry a `Vec<NetUid>` rather than a single netuid:

- `batch_set_weights` (call index 80)
- `batch_commit_weights` (call index 100)
- `batch_reveal_weights` (call index 98)

The `extrinsics` table stores a single `netuid` per row, so when these batch calls land on chain their per-subnet attribution will be missing or collapsed in the dashboard panels.

**Action:** audit the extrinsic extractor in `apps.extrinsics` to confirm what it writes for batch calls (NULL? first netuid? row-per-netuid?). If a single batch row maps to many subnets, decide whether to:

1. Expand batch extrinsics into one row per `(extrinsic, netuid)` at ingest time, or
2. Add a side table (e.g. `extrinsic_netuids`) and join it from the dashboard queries.

Reference: [set-weights.md](../set-weights.md), dashboard [grafana/provisioning/dashboards/bittensor-metrics.json](../grafana/provisioning/dashboards/bittensor-metrics.json).

## Per-client read-only postgres role provisioning

Issuing a client cert via `db_access_certs/issue-client.sh` only gates *transport* — anyone with a valid client cert still needs a postgres role + password to actually query. Today this is a manual step on the prod host.

**Action:** add a companion `db_access_certs/create-readonly-user.sh` (run on the prod host, separate from `issue-client.sh`) that takes a CN, creates `r_<cn>` with a generated password, grants `CONNECT` + appropriate `USAGE`/`SELECT`, and prints the password once. Update [docs/postgres-mtls.md](postgres-mtls.md) to make the two gates explicit: cert proves "you reach the proxy," postgres role proves "you are this DB user."

**Why separate from `issue-client.sh`:** that script runs on a workstation holding the offline CA key; it must not need network access to prod or DB admin credentials. Coupling cert issuance with live-DB role creation mixes two trust domains.
