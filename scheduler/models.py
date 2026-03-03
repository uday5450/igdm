"""
Scheduler app — Models for scheduled Instagram posts and reels.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


def scheduler_media_path(instance, filename):
    """Upload media to: media/scheduler/<ig_account_id>/<filename>"""
    return f'scheduler/{instance.ig_account_id}/{filename}'


def scheduler_thumbnail_path(instance, filename):
    """Upload thumbnails to: media/scheduler/<ig_account_id>/thumbs/<filename>"""
    return f'scheduler/{instance.ig_account_id}/thumbs/{filename}'


class ScheduledPost(models.Model):
    """
    A scheduled Instagram post or reel to be published at a future time.
    """
    POST_TYPE_CHOICES = [
        ('image_post', 'Image Post'),
        ('reel', 'Reel'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('publishing', 'Publishing'),
        ('published', 'Published'),
        ('failed', 'Failed'),
    ]

    # Ownership
    ig_account = models.ForeignKey(
        'instagram.InstagramAccount',
        on_delete=models.CASCADE,
        related_name='scheduled_posts',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scheduled_posts',
    )

    # Content
    post_type = models.CharField(
        max_length=20,
        choices=POST_TYPE_CHOICES,
        default='image_post',
        help_text="Type of content to publish"
    )

    # File uploads
    media_file = models.FileField(
        upload_to=scheduler_media_path,
        help_text="Upload image (JPEG) or video (MP4/MOV) file"
    )
    thumbnail_file = models.FileField(
        upload_to=scheduler_thumbnail_path,
        blank=True,
        null=True,
        help_text="Upload reel cover/thumbnail image (optional, only for reels)"
    )

    # Public URLs (auto-generated from uploaded files)
    media_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text="Public URL to the media file (auto-generated)"
    )
    thumbnail_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text="Public URL to the thumbnail (auto-generated)"
    )

    caption = models.TextField(
        blank=True,
        default='',
        help_text="Post caption (supports hashtags and mentions)"
    )
    share_to_feed = models.BooleanField(
        default=True,
        help_text="For reels: also share to the main feed"
    )

    # Scheduling
    scheduled_at = models.DateTimeField(
        help_text="When to publish this post (UTC)"
    )

    # Publishing status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    ig_container_id = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Instagram container ID (after container creation)"
    )
    ig_media_id = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Published Instagram media ID"
    )
    error_message = models.TextField(
        blank=True,
        default='',
        help_text="Error details if publishing failed"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Scheduled Post'
        verbose_name_plural = 'Scheduled Posts'
        ordering = ['scheduled_at']

    def __str__(self):
        caption_short = self.caption[:40] + '...' if len(self.caption) > 40 else self.caption
        return f"{self.get_post_type_display()} — {caption_short or 'No caption'}"

    def generate_public_url(self, file_field):
        """Generate a public URL from a file field using BASE_URL."""
        if file_field and file_field.name:
            base = settings.BASE_URL.rstrip('/')
            media_url = settings.MEDIA_URL
            return f"{base}{media_url}{file_field.name}"
        return ''

    @property
    def is_due(self):
        """Check if this post is due for publishing."""
        return self.status == 'pending' and self.scheduled_at <= timezone.now()

    @property
    def is_editable(self):
        """Only pending posts can be edited or deleted."""
        return self.status == 'pending'

    @property
    def time_until_publish(self):
        """Returns timedelta until scheduled publish time, or None if past."""
        now = timezone.now()
        if self.scheduled_at > now:
            return self.scheduled_at - now
        return None
