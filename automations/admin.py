"""Automations app — Admin configuration."""
from django.contrib import admin
from .models import Automation, Contact


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = ('name', 'template_type', 'ig_account', 'created_by', 'is_active', 'is_paused',
                    'total_triggers', 'total_dms_sent', 'created_at')
    list_filter = ('template_type', 'is_active', 'is_paused', 'created_at')
    search_fields = ('name', 'ig_account__username', 'created_by__email')
    readonly_fields = ('total_triggers', 'total_dms_sent', 'total_failures', 'created_at', 'updated_at')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('username', 'ig_user_id', 'tag', 'dm_sent', 'dm_sent_at', 'automation', 'created_at')
    list_filter = ('dm_sent', 'tag', 'created_at')
    search_fields = ('username', 'ig_user_id', 'tag')
    readonly_fields = ('created_at',)
