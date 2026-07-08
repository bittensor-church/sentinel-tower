from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("metagraph", "0012_neuronsnapshot_subnet_id"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="weight",
            index=models.Index(fields=["block"], name="idx_weight_block"),
        ),
        AddIndexConcurrently(
            model_name="bond",
            index=models.Index(fields=["block"], name="idx_bond_block"),
        ),
    ]
