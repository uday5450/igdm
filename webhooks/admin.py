"""Webhooks app — Admin configuration."""
from django.contrib import admin
from .models import WebhookEventLog


@admin.register(WebhookEventLog)
class WebhookEventLogAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'ig_account', 'processed', 'process_result', 'received_at')
    list_filter = ('event_type', 'processed', 'received_at')
    search_fields = ('process_result', 'error_message')
    readonly_fields = ('received_at', 'payload')
