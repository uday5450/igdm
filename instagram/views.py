"""
Instagram app — Views for OAuth, account management, and switching.
"""
import uuid
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import InstagramAccount, InstagramAccountUser
from . import services

logger = logging.getLogger(__name__)


@login_required
def connect_instagram(request):
    """
    Show the Connect Instagram page with OAuth button.
    Explains required permissions before redirect.
    """
    # Generate a state parameter for CSRF protection in OAuth
    state = str(uuid.uuid4())
    request.session['oauth_state'] = state
    # oauth_url = services.get_oauth_url(state=state)
    oauth_url = "https://www.instagram.com/oauth/authorize?force_reauth=true&client_id=3334676316687781&redirect_uri=https://60a6-2401-4900-8fec-f3f8-702b-5393-c450-19de.ngrok-free.app/instagram/callback/&response_type=code&scope=instagram_business_basic%2Cinstagram_business_manage_messages%2Cinstagram_business_manage_comments%2Cinstagram_business_content_publish%2Cinstagram_business_manage_insights"
    print("oauth_url ::: ", oauth_url)
    return render(request, 'instagram/connect.html', {
        'oauth_url': oauth_url,
        'ig_accounts': request.user.instagram_accounts.all(),
    })


@login_required
def instagram_callback(request):
    """
    Handle the OAuth callback from Instagram.
    - Exchange code for tokens
    - Create or link InstagramAccount
    - Redirect to dashboard
    """
    code = request.GET.get('code')
    print("code ::: ", code)
    error = request.GET.get('error')
    error_reason = request.GET.get('error_reason', '')

    if error:
        logger.warning(f"OAuth denied: {error} — {error_reason}")
        messages.error(request, f'Instagram authorization was denied: {error_reason}')
        return redirect('instagram:connect')

    if not code:
        messages.error(request, 'No authorization code received. Please try again.')
        return redirect('instagram:connect')

    # Complete the full OAuth flow
    result = services.complete_oauth_flow(code)

    if not result['success']:
        messages.error(request, result.get('error', 'OAuth flow failed. Please try again.'))
        return redirect('instagram:connect')

    # Create or update the InstagramAccount
    ig_account, created = InstagramAccount.objects.update_or_create(
        ig_user_id=result['ig_user_id'],
        defaults={
            'username': result['username'],
            'profile_picture_url': result.get('profile_picture_url', ''),
            'access_token_encrypted': services.encrypt_token(result['access_token']),
            'token_expires_at': result['expires_at'],
        }
    )

    # Link this IG account to the current user (M2M through model)
    link, link_created = InstagramAccountUser.objects.get_or_create(
        user=request.user,
        instagram_account=ig_account,
        defaults={
            'is_active': True,
            'is_owner': created,  # First connector is owner
        }
    )

    if not link_created:
        # Re-activate if previously disconnected
        link.is_active = True
        link.save()

    # Set as active account in session
    request.session['active_ig_account_id'] = ig_account.id

    action = 'connected' if created else 'reconnected'
    messages.success(request, f'Instagram account @{ig_account.username} {action} successfully!')
    return redirect('dashboard:home')


@login_required
def disconnect_instagram(request, account_id):
    """
    Disconnect an Instagram account from the current user.
    - Deactivates the link (does not delete the IG account from DB, since other users may use it)
    - Pauses all automations for this user on that account
    """
    ig_account = get_object_or_404(InstagramAccount, id=account_id)
    link = get_object_or_404(InstagramAccountUser, user=request.user, instagram_account=ig_account)

    # Deactivate the link
    link.is_active = False
    link.save()

    # Pause all automations on this account for this user
    from automations.models import Automation
    Automation.objects.filter(
        ig_account=ig_account,
        created_by=request.user,
        is_active=True,
    ).update(is_active=False, is_paused=True, pause_reason='Instagram account disconnected')

    # Clear session if this was the active account
    if request.session.get('active_ig_account_id') == ig_account.id:
        # Try to switch to another active account
        other_link = InstagramAccountUser.objects.filter(
            user=request.user, is_active=True
        ).exclude(instagram_account=ig_account).first()

        if other_link:
            request.session['active_ig_account_id'] = other_link.instagram_account.id
        else:
            request.session.pop('active_ig_account_id', None)

    messages.info(request, f'Instagram account @{ig_account.username} disconnected.')
    return redirect('instagram:connect')


@login_required
def switch_account(request, account_id):
    """Switch the active Instagram account in the session."""
    ig_account = get_object_or_404(InstagramAccount, id=account_id)

    # Verify user has an active link to this account
    link = InstagramAccountUser.objects.filter(
        user=request.user,
        instagram_account=ig_account,
        is_active=True,
    ).first()

    if not link:
        messages.error(request, 'You do not have access to this Instagram account.')
        return redirect('dashboard:home')

    request.session['active_ig_account_id'] = ig_account.id
    messages.success(request, f'Switched to @{ig_account.username}')
    return redirect('dashboard:home')
