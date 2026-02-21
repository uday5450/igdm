"""
Dashboard app — Template context processor.
Provides active IG account and user's IG accounts to all templates.
"""
from instagram.models import InstagramAccount


def ig_accounts_context(request):
    """
    Add Instagram account data to template context:
    - active_ig_account: The currently selected IG account
    - user_ig_accounts: All IG accounts linked to this user
    """
    if not request.user.is_authenticated:
        return {}

    # Get all active linked IG accounts for this user
    user_ig_accounts = InstagramAccount.objects.filter(
        user_links__user=request.user,
        user_links__is_active=True,
    )

    # Get the active account from session
    active_ig_account = None
    account_id = request.session.get('active_ig_account_id')
    if account_id:
        try:
            active_ig_account = user_ig_accounts.get(id=account_id)
        except InstagramAccount.DoesNotExist:
            pass

    # Fallback to first account
    if not active_ig_account and user_ig_accounts.exists():
        active_ig_account = user_ig_accounts.first()
        if active_ig_account:
            request.session['active_ig_account_id'] = active_ig_account.id

    return {
        'active_ig_account': active_ig_account,
        'user_ig_accounts': user_ig_accounts,
    }
