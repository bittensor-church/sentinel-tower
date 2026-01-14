from django_business_metrics.v0 import BusinessMetricsManager, active_users, users

from apps.extrinsics.models import Extrinsic


def extrinsics_total():
    """Return total count of extrinsics."""
    return Extrinsic.objects.count()


metrics_manager = BusinessMetricsManager()

metrics_manager.add(users).add(active_users).add(extrinsics_total)
