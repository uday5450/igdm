"""
Instagram app — Models for Instagram account management.
Supports many-to-many: one IG account can be linked to multiple users.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class InstagramAccount(models.Model):
    """
    Represents a single Instagram Business/Creator account.
    Can be connected to multiple users via InstagramAccountUser.
    """
    ig_user_id = models.CharField(
        max_length=100, unique=True,
        help_text="Instagram Business Account ID from Graph API"
    )
    username = models.CharField(max_length=150, blank=True, help_text="Instagram username")
    profile_picture_url = models.URLField(blank=True, default='')

    # Encrypted long-lived access token (shared credential for this IG account)
    access_token_encrypted = models.TextField(
        blank=True, default='',
        help_text="Fernet-encrypted long-lived access token"
    )
    token_expires_at = models.DateTimeField(null=True, blank=True)

    # Webhook subscription status
    webhook_subscribed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Many-to-many relationship with users
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='InstagramAccountUser',
        related_name='instagram_accounts',
    )

    class Meta:
        verbose_name = 'Instagram Account'
        verbose_name_plural = 'Instagram Accounts'
        ordering = ['-created_at']

    def __str__(self):
        return f"@{self.username}" if self.username else f"IG:{self.ig_user_id}"

    @property
    def is_token_valid(self):
        """Check if the access token is still valid."""
        if not self.token_expires_at:
            return False
        return timezone.now() < self.token_expires_at

    @property
    def token_expires_soon(self):
        """Check if token will expire within 7 days."""
        if not self.token_expires_at:
            return True
        return timezone.now() + timezone.timedelta(days=7) >= self.token_expires_at


class InstagramAccountUser(models.Model):
    """
    Through model: maps users to Instagram accounts.
    One IG account can be used by multiple users.
    One user can connect multiple IG accounts.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ig_account_links',
    )
    instagram_account = models.ForeignKey(
        InstagramAccount,
        on_delete=models.CASCADE,
        related_name='user_links',
    )
    is_active = models.BooleanField(default=True, help_text="Whether this link is active")
    is_owner = models.BooleanField(
        default=False,
        help_text="Whether this user originally connected the account"
    )
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Instagram Account Link'
        verbose_name_plural = 'Instagram Account Links'
        unique_together = ('user', 'instagram_account')
        ordering = ['-connected_at']

    def __str__(self):
        return f"{self.user.email} ↔ {self.instagram_account}"
