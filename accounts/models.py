"""
Accounts app — Custom User model.
Extends Django's AbstractUser with email-based login and mobile number.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom User model.
    - Email is the unique identifier for login (not username).
    - Mobile number is required at registration.
    """
    email = models.EmailField(unique=True, help_text="Primary login identifier")
    mobile_number = models.CharField(max_length=20, blank=True, help_text="User's mobile number")

    # Use email as the login field
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email

    @property
    def has_instagram_connected(self):
        """Check if user has at least one active Instagram account."""
        return self.ig_account_links.filter(is_active=True).exists()
