from django_business_metrics.v0 import BusinessMetricsManager, active_users, users

from project.core.models import HyperparamEvent


def hyperparam_events_total():
    """Return total count of hyperparameter events."""
    return HyperparamEvent.objects.count()


metrics_manager = BusinessMetricsManager()

metrics_manager.add(users).add(active_users).add(hyperparam_events_total)
