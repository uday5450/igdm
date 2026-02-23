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
            'placeholder': 'e.g. price, link, info (comma-separated)',
        }),
        help_text='Comma-separated keywords. Leave blank to match all comments.',
    )

    public_replies = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-input',
            'placeholder': 'One reply per line (a random variant will be selected)',
            'rows': 3,
        }),
    )

    dm_buttons = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = Automation
        fields = ['name', 'template_type', 'target_post_id', 'tag', 'dm_message', 'public_reply_enabled', 'opening_message_enabled', 'opening_message', 'opening_message_button_text', 'ask_follow_enabled', 'ask_follow_message']
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
                'maxlength': '1000',
            }),
            'opening_message': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Hey there! Click below and I\'ll send the link ✨',
                'maxlength': '1000',
            }),
            'opening_message_button_text': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Send me the link',
                'maxlength': '100',
            }),
            'ask_follow_message': forms.Textarea(attrs={
                'class': 'form-input',
                'placeholder': "Oh no! It seems you're not following me \ud83d\ude3f...",
                'maxlength': '1000',
                'rows': 4,
            }),
        }

    def clean_keywords(self):
        """Parse and validate keywords."""
        raw = self.cleaned_data.get('keywords', '').strip()
        if not raw:
            return '[]'
        keywords = [kw.strip() for kw in raw.split(',') if kw.strip()]
        return json.dumps(keywords)

    def clean_dm_message(self):
        """Validate DM message length."""
        msg = self.cleaned_data.get('dm_message', '').strip()
        if len(msg) > settings.FREE_PLAN_MAX_DM_LENGTH:
            raise forms.ValidationError(
                f'DM message must be {settings.FREE_PLAN_MAX_DM_LENGTH} characters or fewer.'
            )
        return msg

    def clean_opening_message(self):
        msg = self.cleaned_data.get('opening_message', '').strip()
        if len(msg) > settings.FREE_PLAN_MAX_DM_LENGTH:
            raise forms.ValidationError(
                f'Opening message must be {settings.FREE_PLAN_MAX_DM_LENGTH} characters or fewer.'
            )
        return msg

    def clean_ask_follow_message(self):
        msg = self.cleaned_data.get('ask_follow_message', '').strip()
        if len(msg) > settings.FREE_PLAN_MAX_DM_LENGTH:
            raise forms.ValidationError(
                f'Ask-to-follow message must be {settings.FREE_PLAN_MAX_DM_LENGTH} characters or fewer.'
            )
        return msg

    def clean_dm_buttons(self):
        """Validate DM buttons JSON."""
        raw = self.cleaned_data.get('dm_buttons', '').strip()
        if not raw:
            return '[]'
        try:
            buttons = json.loads(raw)
            if not isinstance(buttons, list):
                return '[]'
            # Filter out empty entries
            valid = []
            for b in buttons:
                title = b.get('title', '').strip()
                url = b.get('url', '').strip()
                if title and url:
                    valid.append({'title': title, 'url': url})
            return json.dumps(valid)
        except (json.JSONDecodeError, AttributeError):
            return '[]'

    def clean_tag(self):
        """Validate tag."""
        tag = self.cleaned_data.get('tag', '').strip()
        return tag

    def save(self, commit=True):
        automation = super().save(commit=False)
        automation.keywords_json = self.cleaned_data.get('keywords', '[]')
        automation.dm_buttons_json = self.cleaned_data.get('dm_buttons', '[]')
        # Save public replies
        raw_replies = self.cleaned_data.get('public_replies', '').strip()
        if raw_replies:
            replies = [r.strip() for r in raw_replies.split('\n') if r.strip()]
            automation.public_replies_json = json.dumps(replies)
        else:
            automation.public_replies_json = '[]'
        if commit:
            automation.save()
        return automation

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-fill from instance when editing
        if self.instance and self.instance.pk:
            # Keywords
            kw_list = self.instance.keywords
            if kw_list:
                self.fields['keywords'].initial = ','.join(kw_list)
            # DM Buttons
            buttons = self.instance.dm_buttons
            if buttons:
                self.fields['dm_buttons'].initial = json.dumps(buttons)
            # Public replies
            replies = self.instance.public_replies
            if replies:
                self.fields['public_replies'].initial = '\n'.join(replies)
