"""Add `subtensor_error_codes` lookup table.

Maps `(pallet_index, error_code)` → friendly error name + category +
description + operator remediation. Used by Grafana panels (notably the
Top Error Types panel on the Weight Setting dashboard) to translate
raw `dispatch_error.Module` hex codes into actionable labels.

The initial seed contains only the high-confidence mapping for
`0x1d000000` → `CommitRevealEnabled`, which we narrowed empirically:
the code appears exclusively on direct `set_weights` /
`set_mechanism_weights` extrinsics, and `CommitRevealEnabled` is the
only direct-only error per `set-weights.md` that fits the chain-wide
volume. Other variants (`0x4d`, `0x51`, `0x04`, …) need cross-checking
against `pallets/subtensor/src/errors.rs` in the bittensor-subtensor
repo before being seeded; tracked in `docs/todo.md`.
"""

from django.db import migrations, models

SEED_SQL = """
INSERT INTO subtensor_error_codes (pallet_index, error_code, name, category, description, remediation) VALUES
(7, '0x1d000000', 'CommitRevealEnabled', 'commit_reveal',
 'Direct set_weights / set_mechanism_weights submitted to a subnet where commit-reveal is enabled. The chain only accepts commit_weights (CR-v1) or commit_timelocked_weights (CR-v3/drand) on those subnets.',
 'Switch the validator to the commit-reveal flow that matches the subnet (commit_weights for CR-v1, commit_timelocked_weights for CR-v3 / drand timelock).');
"""


class Migration(migrations.Migration):
    dependencies = [
        ("extrinsics", "0008_add_block_timestamp_brin_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubtensorErrorCode",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "pallet_index",
                    models.SmallIntegerField(help_text="Substrate pallet index (e.g. 7 = SubtensorModule)"),
                ),
                (
                    "error_code",
                    models.CharField(
                        help_text="Hex `dispatch_error.Module.error` field, e.g. '0x1d000000'",
                        max_length=20,
                    ),
                ),
                (
                    "name",
                    models.CharField(help_text="The `Error<T>` enum variant name", max_length=100),
                ),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        help_text="e.g. commit_reveal, validation, addressing",
                        max_length=50,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "remediation",
                    models.TextField(blank=True, help_text="Operator action when this error occurs"),
                ),
            ],
            options={
                "db_table": "subtensor_error_codes",
                "unique_together": {("pallet_index", "error_code")},
            },
        ),
        migrations.RunSQL(sql=SEED_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
