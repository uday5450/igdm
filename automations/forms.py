"""
Automations app — Forms for creating and editing automations.
"""
import json
from django import forms
from django.conf import settings
from .models import Automation


class AutomationForm(forms.ModelForm):
    """Form for the automation creation wizard."""

    keywords = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. price, link, info (comma-separated, max 3)',
        }),
        help_text=f'Comma-separated keywords (max {settings.FREE_PLAN_MAX_KEYWORDS}). Leave blank to match all comments.',
    )

    class Meta:
        model = Automation
        fields = ['name', 'template_type', 'target_post_id', 'tag', 'dm_message']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'My Comment Automation',
            }),
            'template_type': forms.Select(attrs={'class': 'form-input'}),
            'target_post_id': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Leave blank for any post, or paste media ID',
            }),
            'tag': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. interested',
                'maxlength': '50',
            }),
            'dm_message': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Hey! Thanks for your comment. Here\'s the link...',
                'maxlength': '80',
            }),
        }

    def clean_keywords(self):
        """Parse and validate keywords."""
        raw = self.cleaned_data.get('keywords', '').strip()
        if not raw:
            return '[]'
        keywords = [kw.strip() for kw in raw.split(',') if kw.strip()]
        if len(keywords) > settings.FREE_PLAN_MAX_KEYWORDS:
            raise forms.ValidationError(
                f'Free plan allows max {settings.FREE_PLAN_MAX_KEYWORDS} keywords.'
            )
        return json.dumps(keywords)

    def clean_dm_message(self):
        """Validate DM message length and link count."""
        msg = self.cleaned_data.get('dm_message', '').strip()
        if len(msg) > settings.FREE_PLAN_MAX_DM_LENGTH:
            raise forms.ValidationError(
                f'DM message must be {settings.FREE_PLAN_MAX_DM_LENGTH} characters or fewer.'
            )
        # Count links (http:// or https://)
        link_count = msg.lower().count('http://') + msg.lower().count('https://')
        if link_count > settings.FREE_PLAN_MAX_LINKS_IN_DM:
            raise forms.ValidationError(
                f'Free plan allows max {settings.FREE_PLAN_MAX_LINKS_IN_DM} link in DM message.'
            )
        return msg

    def clean_tag(self):
        """Validate tag count."""
        tag = self.cleaned_data.get('tag', '').strip()
        return tag

    def save(self, commit=True):
        automation = super().save(commit=False)
        automation.keywords_json = self.cleaned_data.get('keywords', '[]')
        if commit:
            automation.save()
        return automation
