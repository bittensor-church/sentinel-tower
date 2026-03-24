# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("extrinsics", "0003_subnethyperparamhistory_subnethyperparam"),
    ]

    operations = [
        migrations.AlterField(
            model_name="extrinsic",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name="extrinsic",
            index=models.Index(fields=["created_at"], name="extrinsics_created_f0a498_idx"),
        ),
    ]
