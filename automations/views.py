"""
Automations app — Views for CRUD, toggle, dry-run.
"""
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from instagram.models import InstagramAccount
from instagram.services import decrypt_token, fetch_user_media
from .models import Automation, Contact
from .forms import AutomationForm


def _get_active_ig_account(request):
    """Get the currently active Instagram account for this user."""
    account_id = request.session.get('active_ig_account_id')
    if account_id:
        try:
            ig = InstagramAccount.objects.get(id=account_id)
            # Verify user has active link
            if ig.user_links.filter(user=request.user, is_active=True).exists():
                return ig
        except InstagramAccount.DoesNotExist:
            pass

    # Fallback: get first active linked account
    link = request.user.ig_account_links.filter(is_active=True).first()
    if link:
        request.session['active_ig_account_id'] = link.instagram_account.id
        return link.instagram_account
    return None


@login_required
def automation_list(request):
    """List all automations for the active Instagram account (shared across all users)."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automations = Automation.objects.filter(ig_account=ig_account)

    return render(request, 'automations/list.html', {
        'automations': automations,
        'ig_account': ig_account,
    })


@login_required
def automation_create(request):
    """Create a new automation (wizard flow)."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    # Check limit
    active_count = Automation.objects.filter(
        ig_account=ig_account, is_active=True
    ).count()

    if request.method == 'POST':
        form = AutomationForm(request.POST)
        if form.is_valid():
            automation = form.save(commit=False)
            automation.ig_account = ig_account
            automation.created_by = request.user
            automation.save()
            messages.success(request, f'Automation "{automation.name}" created! Activate it to go live.')
            return redirect('automations:detail', automation_id=automation.id)
    else:
        form = AutomationForm()

    # Fetch recent media for post selection
    media_list = []
    if ig_account.is_token_valid:
        try:
            access_token = decrypt_token(ig_account.access_token_encrypted)
            if access_token:
                media_list = fetch_user_media(access_token, ig_account.ig_user_id)
        except Exception:
            pass

    return render(request, 'automations/create.html', {
        'form': form,
        'ig_account': ig_account,
        'media_list': media_list,
        'active_count': active_count,
        'max_active': settings.FREE_PLAN_MAX_ACTIVE_AUTOMATIONS,
    })


@login_required
def automation_edit(request, automation_id):
    """Edit an existing automation (same wizard flow as create)."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automation = get_object_or_404(
        Automation, id=automation_id, ig_account=ig_account
    )

    if request.method == 'POST':
        form = AutomationForm(request.POST, instance=automation)
        if form.is_valid():
            form.save()
            messages.success(request, f'Automation "{automation.name}" updated!')
            return redirect('automations:detail', automation_id=automation.id)
    else:
        form = AutomationForm(instance=automation)

    # Fetch recent media for post selection
    media_list = []
    if ig_account.is_token_valid:
        try:
            access_token = decrypt_token(ig_account.access_token_encrypted)
            if access_token:
                media_list = fetch_user_media(access_token, ig_account.ig_user_id)
        except Exception:
            pass

    return render(request, 'automations/create.html', {
        'form': form,
        'ig_account': ig_account,
        'media_list': media_list,
        'automation': automation,
        'is_edit': True,
    })


@login_required
def automation_detail(request, automation_id):
    """View automation details and recent contacts."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automation = get_object_or_404(Automation, id=automation_id, ig_account=ig_account)
    contacts = Contact.objects.filter(automation=automation).order_by('-created_at')[:50]

    return render(request, 'automations/detail.html', {
        'automation': automation,
        'contacts': contacts,
    })


@login_required
def automation_toggle(request, automation_id):
    """Activate or deactivate an automation."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automation = get_object_or_404(Automation, id=automation_id, ig_account=ig_account)

    if not automation.is_active:
        # Activating: check limit
        active_count = Automation.objects.filter(
            ig_account=automation.ig_account,
            is_active=True,
        ).exclude(id=automation.id).count()

        if active_count >= settings.FREE_PLAN_MAX_ACTIVE_AUTOMATIONS:
            messages.error(
                request,
                f'Free plan allows only {settings.FREE_PLAN_MAX_ACTIVE_AUTOMATIONS} active automation. '
                'Deactivate another one first.'
            )
            return redirect('automations:detail', automation_id=automation.id)

        # Check token validity
        if not automation.ig_account.is_token_valid:
            messages.error(request, 'Cannot activate: Instagram token has expired. Please reconnect.')
            return redirect('automations:detail', automation_id=automation.id)

        automation.is_active = True
        automation.is_paused = False
        automation.pause_reason = ''
        messages.success(request, f'Automation "{automation.name}" is now LIVE! 🚀')
    else:
        automation.is_active = False
        messages.info(request, f'Automation "{automation.name}" deactivated.')

    automation.save()
    return redirect('automations:detail', automation_id=automation.id)


@login_required
def automation_delete(request, automation_id):
    """Delete an automation."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automation = get_object_or_404(Automation, id=automation_id, ig_account=ig_account)

    if request.method == 'POST':
        name = automation.name
        automation.delete()
        messages.info(request, f'Automation "{name}" deleted.')
        return redirect('automations:list')

    return render(request, 'automations/confirm_delete.html', {
        'automation': automation,
    })


@login_required
def automation_dry_run(request, automation_id):
    """
    Dry run: simulate the automation with sample data.
    Shows what would happen without actually sending DMs.
    """
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    automation = get_object_or_404(Automation, id=automation_id, ig_account=ig_account)

    sample_comments = [
        {'username': 'test_user_1', 'text': 'I want the price please!', 'id': 'sample_001'},
        {'username': 'test_user_2', 'text': 'Great post! 🔥', 'id': 'sample_002'},
        {'username': 'test_user_3', 'text': 'Send me the link', 'id': 'sample_003'},
        {'username': 'test_user_4', 'text': 'Info please', 'id': 'sample_004'},
    ]

    results = []
    for comment in sample_comments:
        matched = automation.matches_keyword(comment['text'])
        results.append({
            'comment': comment,
            'matched': matched,
            'would_dm': matched,
            'dm_message': automation.dm_message if matched else '—',
        })

    return render(request, 'automations/dry_run.html', {
        'automation': automation,
        'results': results,
    })
