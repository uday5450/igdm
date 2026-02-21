"""
Dashboard app — Views for home, contacts, and settings.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from instagram.models import InstagramAccount, InstagramAccountUser
from automations.models import Automation, Contact
from webhooks.models import WebhookEventLog


def _get_active_ig_account(request):
    """Get the currently active Instagram account for this user."""
    account_id = request.session.get('active_ig_account_id')
    if account_id:
        try:
            ig = InstagramAccount.objects.get(id=account_id)
            if ig.user_links.filter(user=request.user, is_active=True).exists():
                return ig
        except InstagramAccount.DoesNotExist:
            pass
    link = request.user.ig_account_links.filter(is_active=True).first()
    if link:
        request.session['active_ig_account_id'] = link.instagram_account.id
        return link.instagram_account
    return None


@login_required
def home(request):
    """Dashboard home — overview stats."""
    ig_account = _get_active_ig_account(request)

    if not ig_account:
        return redirect('instagram:connect')

    # Stats for this IG account
    now = timezone.now()
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)

    automations = Automation.objects.filter(ig_account=ig_account, created_by=request.user)
    contacts = Contact.objects.filter(ig_account=ig_account)

    stats = {
        'total_automations': automations.count(),
        'active_automations': automations.filter(is_active=True).count(),
        'paused_automations': automations.filter(is_paused=True).count(),
        'total_contacts': contacts.count(),
        'contacts_7d': contacts.filter(created_at__gte=last_7_days).count(),
        'dms_sent': contacts.filter(dm_sent=True).count(),
        'dms_sent_7d': contacts.filter(dm_sent=True, dm_sent_at__gte=last_7_days).count(),
        'total_triggers': automations.aggregate(s=Sum('total_triggers'))['s'] or 0,
        'total_failures': automations.aggregate(s=Sum('total_failures'))['s'] or 0,
    }

    # Recent contacts
    recent_contacts = contacts.order_by('-created_at')[:10]

    # Recent events
    recent_events = WebhookEventLog.objects.filter(
        ig_account=ig_account
    ).order_by('-received_at')[:10]

    # Token status
    token_warning = not ig_account.is_token_valid or ig_account.token_expires_soon

    # All linked IG accounts for this user (for account switcher)
    user_ig_accounts = InstagramAccount.objects.filter(
        user_links__user=request.user,
        user_links__is_active=True,
    )

    return render(request, 'dashboard/home.html', {
        'ig_account': ig_account,
        'stats': stats,
        'recent_contacts': recent_contacts,
        'recent_events': recent_events,
        'token_warning': token_warning,
        'user_ig_accounts': user_ig_accounts,
    })


@login_required
def contacts_view(request):
    """List all captured contacts with filtering."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        return redirect('instagram:connect')

    contacts = Contact.objects.filter(ig_account=ig_account)

    # Filters
    tag_filter = request.GET.get('tag', '')
    dm_filter = request.GET.get('dm_sent', '')
    search = request.GET.get('search', '')

    if tag_filter:
        contacts = contacts.filter(tag=tag_filter)
    if dm_filter == 'yes':
        contacts = contacts.filter(dm_sent=True)
    elif dm_filter == 'no':
        contacts = contacts.filter(dm_sent=False)
    if search:
        contacts = contacts.filter(
            Q(username__icontains=search) | Q(comment_text__icontains=search)
        )

    # Get unique tags for filter dropdown
    tags = Contact.objects.filter(ig_account=ig_account).values_list('tag', flat=True).distinct()

    return render(request, 'dashboard/contacts.html', {
        'contacts': contacts[:100],
        'ig_account': ig_account,
        'tags': [t for t in tags if t],
        'filters': {
            'tag': tag_filter,
            'dm_sent': dm_filter,
            'search': search,
        },
    })


@login_required
def settings_view(request):
    """Account settings page."""
    ig_account = _get_active_ig_account(request)

    user_ig_accounts = InstagramAccount.objects.filter(
        user_links__user=request.user,
        user_links__is_active=True,
    )

    return render(request, 'dashboard/settings.html', {
        'ig_account': ig_account,
        'user_ig_accounts': user_ig_accounts,
    })
