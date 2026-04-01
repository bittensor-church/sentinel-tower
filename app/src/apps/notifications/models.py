from django.db import models


class SubnetWebhook(models.Model):
    """Webhook URL configuration for per-subnet notification routing."""

    netuid = models.PositiveIntegerField(db_index=True)
    url = models.URLField(max_length=500)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subnet_webhooks"
        unique_together = [["netuid", "url"]]

    def __str__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"Subnet {self.netuid} → {self.url} ({status})"
