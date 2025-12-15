# Generated manually - remove deprecated HyperparamEvent and SetWeightsEvent models

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_hyperparamevent_timestamp_setweightsevent_timestamp"),
    ]

    operations = [
        migrations.DeleteModel(
            name="HyperparamEvent",
        ),
        migrations.DeleteModel(
            name="SetWeightsEvent",
        ),
    ]
