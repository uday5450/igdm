"""
Instagram app — Service layer for Meta Graph API interactions.
Handles OAuth, token management, DM sending, and token encryption.
"""
import logging
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ─── Graph API Constants ────────────────────────────────────────────
GRAPH_API_VERSION = 'v21.0'
GRAPH_API_BASE = f'https://graph.instagram.com/{GRAPH_API_VERSION}'
OAUTH_BASE = 'https://www.instagram.com/oauth/authorize'
TOKEN_URL = f'https://api.instagram.com/oauth/access_token'
LONG_LIVED_TOKEN_URL = f'{GRAPH_API_BASE}/access_token'

# Required OAuth scopes for Instagram Business Login
OAUTH_SCOPES = [
    'instagram_business_basic',
    'instagram_business_manage_messages',
    'instagram_business_manage_comments',
    'instagram_business_content_publish',
    'instagram_business_manage_insights',
]


# ─── Token Encryption ───────────────────────────────────────────────

def _get_fernet():
    """Get Fernet instance for token encryption/decryption."""
    key = settings.FERNET_KEY
    if not key:
        raise ValueError("FERNET_KEY is not set. Generate one with: "
                         "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    """Encrypt an access token for storage."""
    f = _get_fernet()
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a stored access token."""
    try:
        f = _get_fernet()
        return f.decrypt(encrypted_token.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt token — invalid or corrupted")
        return ''


# ─── OAuth Flow ──────────────────────────────────────────────────────

def get_oauth_url(state: str = '') -> str:
    """
    Build the Instagram OAuth authorization URL.
    Redirects user to Instagram to approve permissions.
    """
    redirect_uri = f"{settings.BASE_URL}/instagram/callback/"
    params = {
        'client_id': settings.INSTAGRAM_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ','.join(OAUTH_SCOPES),
    }
    if state:
        params['state'] = state
    query = '&'.join(f"{k}={v}" for k, v in params.items())
    return f"{OAUTH_BASE}?{query}"


def exchange_code_for_short_token(code: str) -> dict:
    """
    Exchange authorization code for a short-lived access token.
    Returns: {'access_token': ..., 'user_id': ...}
    """
    redirect_uri = f"{settings.BASE_URL}/instagram/callback/"
    client_secret = settings.INSTAGRAM_CLIENT_SECRET
    
    # Debug logging
    print(f"[DEBUG] TOKEN_URL: {TOKEN_URL}")
    print(f"[DEBUG] client_id: {settings.INSTAGRAM_CLIENT_ID}")
    print(f"[DEBUG] client_secret: {client_secret[:4]}...{client_secret[-4:] if len(client_secret) > 8 else '(too short!)'}")
    print(f"[DEBUG] redirect_uri: {redirect_uri}")
    print(f"[DEBUG] code (first 20 chars): {code[:20]}...")
    
    resp = requests.post(TOKEN_URL, data={
        'client_id': settings.INSTAGRAM_CLIENT_ID,
        'client_secret': client_secret,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri,
        'code': code,
    }, timeout=30)

    print(f"[DEBUG] Response status: {resp.status_code}")
    print(f"[DEBUG] Response body: {resp.text}")

    if resp.status_code != 200:
        logger.error(f"Short token exchange failed: {resp.status_code} — {resp.text}")
        return {}

    return resp.json()


def exchange_for_long_lived_token(short_token: str) -> dict:
    """
    Exchange short-lived token for a long-lived token (60 days).
    Returns: {'access_token': ..., 'expires_in': ...}
    """
    resp = requests.get(LONG_LIVED_TOKEN_URL, params={
        'grant_type': 'ig_exchange_token',
        'client_secret': settings.INSTAGRAM_CLIENT_SECRET,
        'access_token': short_token,
    }, timeout=30)

    if resp.status_code != 200:
        logger.error(f"Long-lived token exchange failed: {resp.status_code} — {resp.text}")
        return {}

    return resp.json()


def refresh_long_lived_token(current_token: str) -> dict:
    """
    Refresh a long-lived token before it expires.
    Returns: {'access_token': ..., 'expires_in': ...}
    """
    resp = requests.get(LONG_LIVED_TOKEN_URL, params={
        'grant_type': 'ig_refresh_token',
        'access_token': current_token,
    }, timeout=30)

    if resp.status_code != 200:
        logger.error(f"Token refresh failed: {resp.status_code} — {resp.text}")
        return {}

    return resp.json()


# ─── Instagram Account Info ─────────────────────────────────────────

def fetch_ig_user_profile(access_token: str) -> dict:
    """
    Fetch the Instagram user profile (ID, username, profile picture).
    Returns: {'id': ..., 'username': ..., 'profile_picture_url': ...}
    """
    resp = requests.get(f'{GRAPH_API_BASE}/me', params={
        'fields': 'id,username,profile_picture_url',
        'access_token': access_token,
    }, timeout=30)

    if resp.status_code != 200:
        logger.error(f"Profile fetch failed: {resp.status_code} — {resp.text}")
        return {}

    return resp.json()


def fetch_user_media(access_token: str, ig_user_id: str, limit: int = 25) -> list:
    """
    Fetch recent media (posts/reels) for the Instagram account.
    Returns list of media objects.
    """
    resp = requests.get(f'{GRAPH_API_BASE}/{ig_user_id}/media', params={
        'fields': 'id,caption,media_type,media_url,thumbnail_url,timestamp,permalink',
        'limit': limit,
        'access_token': access_token,
    }, timeout=30)

    if resp.status_code != 200:
        logger.error(f"Media fetch failed: {resp.status_code} — {resp.text}")
        return []

    return resp.json().get('data', [])


# ─── Comment Reply ───────────────────────────────────────────────────

def reply_to_comment(access_token: str, comment_id: str, message: str) -> dict:
    """
    Reply to a comment publicly on Instagram.
    Uses POST /{comment-id}/replies endpoint.

    Args:
        access_token: Long-lived access token
        comment_id: The comment ID to reply to
        message: The reply message text

    Returns: API response dict or {'error': ...}
    """
    url = f"https://graph.instagram.com/v18.0/{comment_id}/replies"
    payload = {
        'message': message,
    }
    params = {
        "access_token": access_token
    }

    resp = requests.post(url, data=payload, params=params)

    if resp.status_code != 200:
        logger.error(f"Comment reply failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text, 'status_code': resp.status_code}

    logger.info(f"Comment reply sent to comment {comment_id}")
    return resp.json()


# ─── Messaging (DM) ─────────────────────────────────────────────────

def send_dm(access_token: str, ig_user_id: str, recipient_id: str, message: str, buttons: list = None, quick_replies: list = None) -> dict:
    """
    Send a DM to a user using the Instagram Messaging API.
    If buttons are provided, sends as a CTA button template.
    Otherwise sends as plain text.

    Args:
        access_token: Long-lived access token
        ig_user_id: The IG Business Account ID (sender)
        recipient_id: The recipient's scoped user ID or comment_id
        message: The DM message text
        buttons: Optional list of {title, url} dicts for CTA buttons

    Returns: API response dict
    """
    url = f'{GRAPH_API_BASE}/{ig_user_id}/messages'

    if buttons:
        # Build CTA buttons list
        cta_buttons = []
        for btn in buttons:
            cta_buttons.append({
                'type': 'web_url',
                'url': btn.get('url', ''),
                'title': btn.get('title', 'Open Link'),
            })

        payload = {
            'recipient': {'comment_id': recipient_id},
            'message': {
                'attachment': {
                    'type': 'template',
                    'payload': {
                        'template_type': 'button',
                        'text': message,
                        'buttons': cta_buttons
                    }
                }
            },
            'access_token': access_token,
        }
        print(f"   📎 Sending as CTA with {len(cta_buttons)} button(s): {[b['title'] for b in cta_buttons]}")
    elif quick_replies:
        # Send text with quick reply buttons (tappable pills below the message)
        qr_list = []
        for qr in quick_replies:
            qr_list.append({
                'content_type': 'text',
                'title': qr.get('title', 'Send me the link'),
                'payload': qr.get('payload', 'SEND_LINK'),
            })

        payload = {
            'recipient': {'comment_id': recipient_id},
            'message': {
                'text': message,
                'quick_replies': qr_list,
            },
            'access_token': access_token,
        }
        print(f"   🔘 Sending with {len(qr_list)} quick reply(s): {[q['title'] for q in qr_list]}")
    else:
        # Send as plain text
        payload = {
            'recipient': {'comment_id': recipient_id},
            'message': {'text': message},
            'access_token': access_token,
        }

    resp = requests.post(url, json=payload, timeout=30)

    if resp.status_code != 200:
        logger.error(f"DM send failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text, 'status_code': resp.status_code}

    logger.info(f"DM sent successfully to {recipient_id}")
    return resp.json()


def send_dm_by_user_id(access_token: str, ig_user_id: str, recipient_user_id: str, message: str, buttons: list = None) -> dict:
    url = f'{GRAPH_API_BASE}/{ig_user_id}/messages'
    if buttons:
        cta_buttons = []
        for btn in buttons:
            cta_buttons.append({
                'type': 'web_url',
                'url': btn.get('url', ''),
                'title': btn.get('title', 'Open Link'),
            })
        payload = {
            'recipient': {'id': recipient_user_id},
            'message': {
                'attachment': {
                    'type': 'template',
                    'payload': {
                        'template_type': 'button',
                        'text': message,
                        'buttons': cta_buttons
                    }
                }
            },
            'access_token': access_token,
        }
    else:
        payload = {
            'recipient': {'id': recipient_user_id},
            'message': {'text': message},
            'access_token': access_token,
        }

    resp = requests.post(url, json=payload, timeout=30)

    if resp.status_code != 200:
        logger.error(f"DM send (by user ID) failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text, 'status_code': resp.status_code}

    logger.info(f"DM sent to user {recipient_user_id}")
    return resp.json()


# ─── Full OAuth Flow Helper ─────────────────────────────────────────

def complete_oauth_flow(code: str) -> dict:
    """
    Complete the full OAuth flow:
    1. Exchange code → short-lived token
    2. Exchange short → long-lived token
    3. Fetch user profile

    Returns: {
        'success': bool,
        'ig_user_id': str,
        'username': str,
        'profile_picture_url': str,
        'access_token': str,        # long-lived token (plaintext)
        'expires_at': datetime,
        'error': str (if failed),
    }
    """
    # Step 1: Code → short-lived token
    short_data = exchange_code_for_short_token(code)
    if not short_data or 'access_token' not in short_data:
        return {'success': False, 'error': 'Failed to exchange authorization code for token.'}

    short_token = short_data['access_token']

    # Step 2: Short → long-lived token
    long_data = exchange_for_long_lived_token(short_token)
    if not long_data or 'access_token' not in long_data:
        return {'success': False, 'error': 'Failed to exchange for long-lived token.'}

    long_token = long_data['access_token']
    expires_in = long_data.get('expires_in', 5184000)  # Default: 60 days
    expires_at = timezone.now() + timedelta(seconds=expires_in)

    # Step 3: Fetch profile
    profile = fetch_ig_user_profile(long_token)
    if not profile or 'id' not in profile:
        return {'success': False, 'error': 'Failed to fetch Instagram profile.'}

    return {
        'success': True,
        'ig_user_id': profile['id'],
        'username': profile.get('username', ''),
        'profile_picture_url': profile.get('profile_picture_url', ''),
        'access_token': long_token,
        'expires_at': expires_at,
    }
