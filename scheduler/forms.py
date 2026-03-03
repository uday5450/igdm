"""
Scheduler app — Forms for creating/editing scheduled posts.
"""
from django import forms
from django.utils import timezone
from datetime import timedelta
from .models import ScheduledPost


class ScheduledPostForm(forms.ModelForm):
    class Meta:
        model = ScheduledPost
        fields = [
            'post_type', 'media_file', 'thumbnail_file',
            'caption', 'share_to_feed', 'scheduled_at',
        ]
        widgets = {
            'caption': forms.Textarea(attrs={
                'placeholder': 'Write your caption here... #hashtags @mentions',
                'rows': 4,
                'class': 'form-input',
            }),
            'scheduled_at': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-input',
            }),
        }

    def clean_media_file(self):
        media_file = self.cleaned_data.get('media_file')
        if media_file:
            # Check file size (max 100MB for videos, 8MB for images)
            max_size = 100 * 1024 * 1024  # 100MB
            if media_file.size > max_size:
                raise forms.ValidationError('File is too large. Maximum size is 100MB.')

            # Validate file extension
            name = media_file.name.lower()
            allowed = ['.jpg', '.jpeg', '.mp4', '.mov']
            if not any(name.endswith(ext) for ext in allowed):
                raise forms.ValidationError(
                    'Invalid file type. Allowed: JPEG images (.jpg, .jpeg) or videos (.mp4, .mov)'
                )
        return media_file

    def clean_thumbnail_file(self):
        thumbnail_file = self.cleaned_data.get('thumbnail_file')
        if thumbnail_file:
            # Max 8MB for thumbnails
            if thumbnail_file.size > 8 * 1024 * 1024:
                raise forms.ValidationError('Thumbnail is too large. Maximum size is 8MB.')

            name = thumbnail_file.name.lower()
            if not any(name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                raise forms.ValidationError(
                    'Invalid thumbnail type. Allowed: .jpg, .jpeg, .png'
                )
        return thumbnail_file

    def clean_scheduled_at(self):
        scheduled_at = self.cleaned_data.get('scheduled_at')
        if scheduled_at:
            min_time = timezone.now() + timedelta(minutes=10)
            if scheduled_at < min_time:
                raise forms.ValidationError(
                    'Schedule time must be at least 10 minutes in the future.'
                )
        return scheduled_at

    def clean(self):
        cleaned_data = super().clean()
        post_type = cleaned_data.get('post_type')

        # Clear thumbnail for image posts
        if post_type == 'image_post':
            cleaned_data['thumbnail_file'] = None

        return cleaned_data
