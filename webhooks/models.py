"""
Webhooks app — Models for webhook event logging.
"""
from django.db import models


class WebhookEventLog(models.Model):
    """
    Log of all incoming webhook events from Instagram.
    """
    EVENT_TYPES = [
        ('comment', 'Comment'),
        ('story_reply', 'Story Reply'),
        ('dm', 'Direct Message'),
        ('other', 'Other'),
    ]

    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='other')
    ig_account = models.ForeignKey(
        'instagram.InstagramAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='webhook_events',
    )
    ig_user_id = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Raw IG user ID from webhook (stored even if account not in DB)"
    )

    # Raw payload
    payload = models.JSONField(default=dict, help_text="Raw webhook payload")

    # Processing status
    processed = models.BooleanField(default=False)
    process_result = models.CharField(max_length=50, blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Webhook Event Log'
        verbose_name_plural = 'Webhook Event Logs'
        ordering = ['-received_at']

    def __str__(self):
        return f"{self.event_type} @ {self.received_at.strftime('%Y-%m-%d %H:%M')}"
