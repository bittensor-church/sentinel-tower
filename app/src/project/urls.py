from django.conf import settings
from django.contrib.admin.sites import site
from django.http import HttpResponse
from django.urls import include, path

from apps.metagraph.explorer import get_explorer_urls

from .core.business_metrics import metrics_manager
from .core.metrics import metrics_view

urlpatterns = [
    path("alive/", lambda _: HttpResponse(b"ok")),
    path("admin/", (get_explorer_urls(site) + site.get_urls(), "admin", site.name)),
    path("metrics", metrics_view, name="prometheus-django-metrics"),
    path("business-metrics", metrics_manager.view, name="prometheus-business-metrics"),
    path("", include("django.contrib.auth.urls")),
]


if settings.DEBUG_TOOLBAR:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]
