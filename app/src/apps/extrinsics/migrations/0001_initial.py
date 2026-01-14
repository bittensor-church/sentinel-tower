"""
Initial migration for apps.extrinsics.

This migration takes ownership of the Extrinsic model from project.core.
The database table already exists, so we only affect Django's state.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0008_move_extrinsic_to_extrinsics_app"),
    ]

    operations = [
        # Add the model to extrinsics app's state, but don't create the table (already exists)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Extrinsic",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("block_number", models.PositiveBigIntegerField(db_index=True)),
                        ("block_hash", models.CharField(blank=True, db_index=True, max_length=66)),
                        ("extrinsic_hash", models.CharField(max_length=66, unique=True)),
                        (
                            "extrinsic_index",
                            models.PositiveIntegerField(
                                blank=True,
                                help_text="Index within the block",
                                null=True,
                            ),
                        ),
                        (
                            "block_timestamp",
                            models.PositiveBigIntegerField(
                                blank=True,
                                help_text="Block timestamp from Timestamp.Now",
                                null=True,
                            ),
                        ),
                        ("call_module", models.CharField(max_length=100)),
                        ("call_function", models.CharField(db_index=True, max_length=100)),
                        (
                            "call_args",
                            models.JSONField(
                                default=dict,
                                help_text="Call arguments from extrinsic",
                            ),
                        ),
                        ("address", models.CharField(blank=True, db_index=True, max_length=66)),
                        ("signature", models.JSONField(blank=True, null=True)),
                        ("nonce", models.PositiveBigIntegerField(blank=True, null=True)),
                        (
                            "tip_rao",
                            models.BigIntegerField(blank=True, help_text="Tip in rao", null=True),
                        ),
                        ("status", models.CharField(blank=True, max_length=20)),
                        ("success", models.BooleanField(db_index=True, default=False)),
                        (
                            "error_data",
                            models.JSONField(
                                blank=True,
                                help_text="Error attributes if failed",
                                null=True,
                            ),
                        ),
                        (
                            "events",
                            models.JSONField(
                                default=list,
                                help_text="Events associated with this extrinsic",
                            ),
                        ),
                        ("netuid", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                    options={
                        "db_table": "extrinsics",
                        "ordering": ["-block_number", "-extrinsic_index"],
                        "indexes": [
                            models.Index(
                                fields=["block_number", "extrinsic_index"],
                                name="extrinsics_block_n_9a1f3e_idx",
                            ),
                            models.Index(
                                fields=["block_hash"],
                                name="extrinsics_block_h_7ae207_idx",
                            ),
                            models.Index(
                                fields=["address", "block_number"],
                                name="extrinsics_address_653e67_idx",
                            ),
                            models.Index(
                                fields=["call_module", "call_function", "success"],
                                name="extrinsics_call_mo_837e16_idx",
                            ),
                            models.Index(
                                fields=["netuid", "call_function"],
                                name="extrinsics_netuid_056ebb_idx",
                            ),
                            models.Index(
                                fields=["block_number", "call_function"],
                                name="extrinsics_block_n_callf_idx",
                            ),
                            models.Index(
                                fields=["address", "call_function"],
                                name="extrinsics_address_callf_idx",
                            ),
                        ],
                    },
                ),
            ],
            database_operations=[],  # No database changes - table already exists
        ),
    ]
