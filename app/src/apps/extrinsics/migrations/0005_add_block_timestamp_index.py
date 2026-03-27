# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("extrinsics", "0004_add_created_at_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="extrinsic",
            name="block_timestamp",
            field=models.PositiveBigIntegerField(
                blank=True, db_index=True, help_text="Block timestamp from Timestamp.Now", null=True
            ),
        ),
    ]
