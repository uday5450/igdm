"""
Automations app — Models for automation rules and captured contacts.
"""
import json
from django.conf import settings
from django.db import models
from django.core.validators import MaxLengthValidator


class Automation(models.Model):
    """
    An automation rule: when a comment/story/DM matches criteria → send a DM.
    """
    TEMPLATE_CHOICES = [
        ('comment_dm', 'Instant DM from Comments'),
        ('story_dm', 'Instant DM from Stories'),
        ('dm_reply', 'Respond to all DMs'),
    ]

    # Ownership
    ig_account = models.ForeignKey(
        'instagram.InstagramAccount',
        on_delete=models.CASCADE,
        related_name='automations',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='automations',
    )

    # Automation config
    name = models.CharField(max_length=100, help_text="Automation name")
    template_type = models.CharField(max_length=20, choices=TEMPLATE_CHOICES, default='comment_dm')
    target_post_id = models.CharField(
        max_length=200, blank=True, default='',
        help_text="Instagram post/reel media ID (blank = any post)"
    )
    target_post_permalink = models.URLField(blank=True, default='', help_text="Post permalink for display")

    # Keyword matching (stored as JSON list, max 3 for free plan)
    keywords_json = models.TextField(
        default='[]',
        help_text="JSON list of keywords to match (max 3 for free plan)"
    )

    # Tag for captured contacts (max 1 for free plan)
    tag = models.CharField(max_length=50, blank=True, default='', help_text="Tag for contacts captured by this automation")

    # DM message (max 80 chars, max 1 link for free plan)
    dm_message = models.CharField(
        max_length=1000,
        help_text="DM message to send"
    )

    # DM CTA buttons (JSON array of {title, url} objects)
    dm_buttons_json = models.TextField(
        default='[]',
        help_text="JSON list of CTA buttons [{title, url}, ...]"
    )

    @property
    def dm_buttons(self):
        """Return DM buttons as a Python list of dicts."""
        try:
            return json.loads(self.dm_buttons_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @dm_buttons.setter
    def dm_buttons(self, value):
        """Set DM buttons from a Python list of dicts."""
        self.dm_buttons_json = json.dumps(value)

    # Public reply to comments
    public_reply_enabled = models.BooleanField(
        default=False,
        help_text="Whether to publicly reply to comments before sending DM"
    )
    public_replies_json = models.TextField(
        default='[]',
        help_text="JSON list of public reply variants (one picked randomly)"
    )

    # Status
    is_active = models.BooleanField(default=False, help_text="Whether this automation is live")
    is_paused = models.BooleanField(default=False, help_text="System-paused (token expired, webhook down, etc.)")
    pause_reason = models.TextField(blank=True, default='')

    # Stats
    total_triggers = models.PositiveIntegerField(default=0)
    total_dms_sent = models.PositiveIntegerField(default=0)
    total_failures = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Automation'
        verbose_name_plural = 'Automations'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"

    @property
    def keywords(self):
        """Return keywords as a Python list."""
        try:
            return json.loads(self.keywords_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @keywords.setter
    def keywords(self, value):
        """Set keywords from a Python list."""
        self.keywords_json = json.dumps(value[:settings.FREE_PLAN_MAX_KEYWORDS])

    def matches_keyword(self, text: str) -> bool:
        """
        Check if the given text matches any of the automation's keywords.
        Case-insensitive matching. Empty keywords list = match all.
        """
        kw_list = self.keywords
        if not kw_list:
            return True  # No keywords = match everything
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in kw_list)

    @property
    def public_replies(self):
        """Return public replies as a Python list."""
        try:
            return json.loads(self.public_replies_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @public_replies.setter
    def public_replies(self, value):
        """Set public replies from a Python list."""
        self.public_replies_json = json.dumps(value)

    def get_random_reply(self):
        """Pick a random public reply variant."""
        import random
        replies = self.public_replies
        if not replies:
            return None
        return random.choice(replies)


class Contact(models.Model):
    """
    A captured contact — someone who triggered an automation and received a DM.
    """
    ig_account = models.ForeignKey(
        'instagram.InstagramAccount',
        on_delete=models.CASCADE,
        related_name='contacts',
    )
    automation = models.ForeignKey(
        Automation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contacts',
    )

    # Contact info
    ig_user_id = models.CharField(max_length=100, help_text="Commenter/sender IG user ID")
    username = models.CharField(max_length=150, blank=True, default='')
    comment_id = models.CharField(max_length=200, blank=True, default='')
    comment_text = models.TextField(blank=True, default='')

    # Tag from automation
    tag = models.CharField(max_length=50, blank=True, default='')

    # DM status
    dm_sent = models.BooleanField(default=False)
    dm_sent_at = models.DateTimeField(null=True, blank=True)
    dm_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Contact'
        verbose_name_plural = 'Contacts'
        ordering = ['-created_at']

    def __str__(self):
        return f"@{self.username}" if self.username else f"IG:{self.ig_user_id}"
