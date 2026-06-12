from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metagraph", "0011_optimize_apy_refresh"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="neuronsnapshot",
            index=models.Index(fields=["block_id"], name="idx_nsnapshot_block"),
        ),
        migrations.CreateModel(
            name="SnapshotHealthMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("netuid", models.PositiveIntegerField()),
                ("window", models.CharField(max_length=16)),
                ("missing_blocks", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "metagraph_snapshot_health_metric",
            },
        ),
        migrations.AddConstraint(
            model_name="snapshothealthmetric",
            constraint=models.UniqueConstraint(
                fields=["netuid", "window"],
                name="unique_snapshot_health_metric",
            ),
        ),
    ]
