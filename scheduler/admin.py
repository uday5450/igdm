"""Scheduler app — Admin configuration."""
from django.contrib import admin
from .models import ScheduledPost


@admin.register(ScheduledPost)
class ScheduledPostAdmin(admin.ModelAdmin):
    list_display = ('caption_short', 'post_type', 'status', 'scheduled_at', 'ig_account', 'created_by')
    list_filter = ('post_type', 'status', 'scheduled_at')
    search_fields = ('caption', 'ig_account__username')
    ordering = ('-scheduled_at',)

    def caption_short(self, obj):
        return obj.caption[:50] + '...' if len(obj.caption) > 50 else obj.caption
    caption_short.short_description = 'Caption'
