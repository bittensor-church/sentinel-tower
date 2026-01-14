"""
Migration to move Extrinsic model from project.core to apps.extrinsics.

This migration only affects Django's state - the database table remains unchanged.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_remove_hyperparamevent_setweightsevent"),
    ]

    # Disable atomicity since we're using SeparateDatabaseAndState
    atomic = False

    operations = [
        # Remove the model from core app's state, but don't touch the database
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Extrinsic"),
            ],
            database_operations=[],  # No database changes
        ),
    ]
