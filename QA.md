# QA

Binding guidance for test work in this repository. Read before adding, deleting, or
auditing tests.

## Test suites and how to run them

Two suites, both under `app/src`:

- **Unit / integration** (`app/src/tests/`, `app/src/project/**/tests/`): fast, hit
  Postgres + Redis, mock the chain. Run with `nox -s test`.
- **End-to-end** (`app/src/tests/e2e/`): drive a real subtensor localnet — sign and
  submit real extrinsics, then assert Sentinel Tower's pipeline recorded the
  consequences. Run with `nox -s test_e2e`.

Prerequisites (manual, per the repo convention that test setup never starts containers):

```bash
docker compose up -d db redis                          # unit + e2e need these
docker compose --profile e2e up -d localnet            # e2e also needs the chain
```

The e2e localnet **must** run runtime specVersion **424** — the image is pinned to
`ghcr.io/opentensor/subtensor-localnet:v3.4.9-424` (the tag suffix is the runtime
version, which matches finney). A newer runtime (e.g. the `raofoundation/...:devnet`
image's 431) types `NetUid` as a composite newtype that bittensor 10.x cannot encode, so
every metagraph/hyperparam call fails with `Invalid type for data`. The e2e conftest
asserts the runtime version up front and fails loudly if it is wrong. Override the node
URL with `E2E_LOCALNET_URL` if needed.

## Unit test assertions

Unit/integration tests must assert real, concrete values — specific field values,
counts, IDs, or content — not just the shape of the response (type, key presence,
non-null, length). A test that only checks shape proves almost nothing.

If a value cannot be asserted concretely because an external service makes it
non-deterministic, that is a gap in the `Contact` boundary, not a reason to settle for
a shape check: add or extend the `Contact` and its mock (per
[engineering-standards.md](engineering-standards.md#value-assertion-rules)), configure
the mock to a known value, and assert exactly that value.

## What deserves an e2e test here

E2e tests exist to prove the seam unit tests cannot: that **real chain data flows
through our parsing and persistence correctly**. Unit tests feed synthetic dicts to
parsers and handlers; only e2e proves the bittensor SDK's actual output shape matches
what the code expects. So an e2e test earns its place when it exercises a real
chain → ingestion → DB/notification path end to end. Anything that is pure DB or pure
formatting logic belongs in a unit test, not here.

The e2e suite drives only the `bittensor` provider, not `pylon` — keeping the two
providers equivalent is the SDK's concern, and this avoids running a pylon instance.

## E2e design rules (learned the hard way)

The localnet is a **single, long-lived, shared** chain with one sudo account (`//Alice`).
That shapes the whole design:

- **Serial only.** Tests share one account; parallel workers collide on nonces. The
  `test_e2e` nox session forces `-n0`. Never run the e2e suite under `-n auto`.
- **Submit once, ingest per-test.** Chain writes are slow and append-only; DB writes roll
  back per test. Module-scoped fixtures submit the extrinsics once; each test re-ingests
  the blocks into a fresh transaction-isolated DB.
- **Self-heal at session start.** The chain accumulates state across runs, and any aborted
  run can leave it poisoned. The `localnet` fixture clears stale coldkey-swap
  announcements and resets the subnet-registration lock cost so the suite is idempotent —
  it passes run after run without manual chain resets.
- **Prove topology, don't assume it.** The fixture asserts the runtime version, that
  `//Alice` really is the sudo key, and that the genesis subnet exists, before any test
  depends on those facts.

## Decision log

- **Metagraph/APY/explorer are covered e2e** against runtime 424 after we found the
  localnet image (not the SDK) was the blocker. `v3.4.9-424` is the required image.
- **Coldkey-swap announcement alerting (§4.2) IS covered e2e.** A real
  `announce_coldkey_swap` locks the signing account until it matures
  (`InitialColdkeySwapAnnouncementDelay` = 50 blocks, ~20s at the localnet's block time).
  The test asserts the alert on the central channel, then waits for the announcement to
  mature and clears it so the account is unlocked for later tests. Two subtleties the
  clear must respect: a pre-maturity clear is *included but fails on-chain* (so check the
  extrinsic's on-chain result, not just that it was submitted), and the session fixture
  best-effort-clears any stale announcement up front so an aborted run self-heals.
- **§4.6 "only successful extrinsics notify" needs a failed extrinsic that _matches a
  handler_.** An earlier version asserted the failed `burned_register`'s hash was absent
  from all webhook content — vacuous, since `burned_register` matches no handler and only
  the registration handler ever emits a hash. The success filter (`base.py`) only runs
  after a handler matches, so the test now submits a **direct** `AdminUtils.sudo_set_tempo`
  (`failed_handled` in the batch): AdminUtils calls require root, so submitted un-wrapped
  it is included-but-failed with `BadOrigin` while still matching `AdminUtilsNotification`.
  A Sudo-_wrapped_ failure would not work — the outer sudo extrinsic succeeds, so its
  recorded `success` is True. Its block is ingested in isolation and the hyperparam
  channel must stay empty.
- **The real assigned netuid is captured via `substrate.get_events(block_hash)`, not the
  receipt.** `register_network` carries no netuid arg; the chain assigns one and reports
  it in the `NetworkAdded` event. `SubmittedExtrinsic.netuid` captures it so tests assert
  the ingested value _equals_ it (not just `> genesis`). The receipt's `triggered_events`
  decode lazily and return `None` right after submission — `substrate.get_events` returns
  fully-decoded events reliably.
- **Per-subnet webhook routing / enable-disable toggle (§4.3/§4.4) stays unit-tested.**
  That is pure DB logic (`DatabaseWebhookChannel` filtering `enabled=True`), thoroughly
  covered in `tests/notifications/test_channels.py`; a real chain adds nothing to it.
- **Lite-vs-full metagraph (§2.3) is not distinguishable e2e** on this localnet: subnet 1
  carries one neuron and no weights/bonds, so both modes yield the same rows. The lite
  path is covered by the metagraph sync-service unit tests.
- **APY (§2.4) is not e2e**: it needs multi-epoch dividend history the localnet does not
  accrue. The APY view is unit-tested (`tests/metagraph/test_apy_epoch_view.py`).
- **Error-code seed was fixed, not just tested.** The e2e failure-decoding test
  (`§1.5`) surfaced that migration 0010 seeded `subtensor_error_codes` from a stale enum
  ordering — off by one from index 23, so 94 of 135 codes decoded to the wrong name.
  Migration 0013 regenerates all 147 codes from the runtime-424 metadata.

## Known pre-existing issues (not introduced by e2e work)

- `nox -s test` passes `project` to pytest, so it collects **only**
  `app/src/project/**/tests/` (43 tests) — the entire `app/src/tests/` tree (the 164
  unit tests) is not run by `nox -s test` or by CI's unit-test job. Flagged, not changed,
  to avoid silently widening the unit-test surface; decide deliberately.
