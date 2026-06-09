"""Add dТАО APY data points to Subnet and NeuronSnapshot.

Adds Subnet.tempo and Subnet.moving_price (raw values, no rao conversion) and
NeuronSnapshot.alpha_dividends / tao_dividends (rao integers, matching the
alpha_stake/emissions precision). All columns default to 0 / 0.0 so no backfill
is needed; data is forward-only and gets populated by MetagraphSyncService.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metagraph", "0008_create_validator_apy_windows_view"),
    ]

    operations = [
        migrations.AddField(
            model_name="neuronsnapshot",
            name="alpha_dividends",
            field=models.DecimalField(
                decimal_places=0,
                default=0,
                help_text="Net alpha dividends this epoch in rao (AlphaDividendsPerSubnet, index 71)",
                max_digits=30,
            ),
        ),
        migrations.AddField(
            model_name="neuronsnapshot",
            name="tao_dividends",
            field=models.DecimalField(
                decimal_places=0, default=0, help_text="Net TAO dividends this epoch in rao", max_digits=30
            ),
        ),
        migrations.AddField(
            model_name="subnet",
            name="moving_price",
            field=models.FloatField(default=0.0, help_text="Alpha->TAO moving price (0.0 if not exposed)"),
        ),
        migrations.AddField(
            model_name="subnet",
            name="tempo",
            field=models.PositiveIntegerField(default=0, help_text="Epoch length in blocks (0 if not exposed)"),
        ),
    ]
