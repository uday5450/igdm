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
GRAPH_API_VERSION = 'v24.0'
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
    redirect_uri = f"https://instagram.joingy.site/instagram/callback/"
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


def get_valid_access_token(ig_account) -> str:
    """
    Get a valid access token for the given InstagramAccount.
    If the token is expired or expiring within 7 days, automatically refreshes it.

    Args:
        ig_account: InstagramAccount model instance

    Returns:
        Plaintext access token string, or '' if unable to get a valid token.
    """
    if not ig_account.access_token_encrypted:
        logger.error(f"No token stored for {ig_account}")
        return ''

    current_token = decrypt_token(ig_account.access_token_encrypted)
    if not current_token:
        logger.error(f"Could not decrypt token for {ig_account}")
        return ''

    # If token is still valid and not expiring soon, return it
    if ig_account.is_token_valid and not ig_account.token_expires_soon:
        return current_token

    # Token is expired or expiring soon — try to refresh
    logger.info(f"Token for {ig_account} is expired or expiring soon. Attempting refresh...")

    refresh_data = refresh_long_lived_token(current_token)

    if not refresh_data or 'access_token' not in refresh_data:
        # Refresh failed — still return current token if it hasn't fully expired
        if ig_account.is_token_valid:
            logger.warning(f"Token refresh failed for {ig_account}, but current token still valid.")
            return current_token
        logger.error(f"Token refresh failed for {ig_account} and token is expired.")
        return ''

    # Refresh succeeded — save new token
    new_token = refresh_data['access_token']
    expires_in = refresh_data.get('expires_in', 5184000)  # Default 60 days
    new_expiry = timezone.now() + timedelta(seconds=expires_in)

    ig_account.access_token_encrypted = encrypt_token(new_token)
    ig_account.token_expires_at = new_expiry
    ig_account.save(update_fields=['access_token_encrypted', 'token_expires_at', 'updated_at'])

    logger.info(f"Token refreshed for {ig_account}. New expiry: {new_expiry}")
    return new_token


# ─── Instagram Account Info ─────────────────────────────────────────

def fetch_ig_user_profile(access_token: str) -> dict:
    """
    Fetch the Instagram user profile (ID, username, profile picture).
    Returns: {'id': ..., 'username': ..., 'profile_picture_url': ...}
    """
    resp = requests.get(f'{GRAPH_API_BASE}/me', params={
        'fields': 'id,username,profile_picture_url,user_id',
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


def check_user_follows(access_token: str, user_id: str) -> bool:
    """
    Check if a user follows the business account.
    Uses the is_user_follow_business field on the Instagram User node.

    Args:
        access_token: Long-lived access token of the business account
        user_id: The scoped user ID to check

    Returns: True if the user follows the business, False otherwise
    """
    try:
        resp = requests.get(f'{GRAPH_API_BASE}/{user_id}', params={
            'fields': 'is_user_follow_business',
            'access_token': access_token,
        }, timeout=30)

        if resp.status_code != 200:
            logger.error(f"Follow check failed: {resp.status_code} — {resp.text}")
            return False

        data = resp.json()
        follows = data.get('is_user_follow_business', False)
        logger.info(f"Follow check for user {user_id}: {follows}")
        return follows
    except Exception as e:
        logger.exception(f"Error checking follow status for user {user_id}: {e}")
        return False


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
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"
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


def send_dm_by_user_id(access_token: str, ig_user_id: str, recipient_user_id: str, message: str, buttons: list = None, quick_replies: list = None) -> dict:
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
    elif quick_replies:
        qr_list = []
        for qr in quick_replies:
            qr_list.append({
                'content_type': 'text',
                'title': qr.get('title', ''),
                'payload': qr.get('payload', ''),
            })
        payload = {
            'recipient': {'id': recipient_user_id},
            'message': {
                'text': message,
                'quick_replies': qr_list,
            },
            'access_token': access_token,
        }
        print(f"   🔘 Sending with {len(qr_list)} quick reply(s): {[q['title'] for q in qr_list]}")
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


# ─── Content Publishing ─────────────────────────────────────────────

def create_media_container(access_token: str, ig_user_id: str, media_url: str,
                           media_type: str = None, caption: str = '',
                           cover_url: str = None, share_to_feed: bool = True) -> dict:
    """
    Create an Instagram media container for publishing.

    Args:
        access_token: Long-lived access token
        ig_user_id: Instagram Business Account ID
        media_url: Public URL to image (JPEG) or video (MP4/MOV)
        media_type: 'REELS' for reels, None for image posts
        caption: Post caption text
        cover_url: Public URL to cover/thumbnail image (reels only)
        share_to_feed: Whether to share reel to main feed (reels only)

    Returns: API response dict with 'id' key on success
    """
    url = f'{GRAPH_API_BASE}/{ig_user_id}/media'

    params = {
        'caption': caption,
        'access_token': access_token,
    }

    if media_type == 'REELS':
        params['media_type'] = 'REELS'
        params['video_url'] = media_url
        params['share_to_feed'] = 'true' if share_to_feed else 'false'
        if cover_url:
            params['cover_url'] = cover_url
    else:
        # Image post
        params['image_url'] = media_url

    resp = requests.post(url, data=params, timeout=60)

    if resp.status_code != 200:
        logger.error(f"Container creation failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text, 'status_code': resp.status_code}

    logger.info(f"Media container created for {ig_user_id}")
    return resp.json()


def check_container_status(access_token: str, container_id: str) -> dict:
    """
    Check the status of a media container (useful for video processing).

    Returns: {'status_code': 'FINISHED'|'IN_PROGRESS'|'ERROR', ...}
    """
    url = f'{GRAPH_API_BASE}/{container_id}'
    resp = requests.get(url, params={
        'fields': 'status_code',
        'access_token': access_token,
    }, timeout=30)

    if resp.status_code != 200:
        logger.error(f"Container status check failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text}

    return resp.json()


def publish_media_container(access_token: str, ig_user_id: str, container_id: str) -> dict:
    """
    Publish a previously created media container.

    Args:
        access_token: Long-lived access token
        ig_user_id: Instagram Business Account ID
        container_id: The container ID from create_media_container()

    Returns: API response dict with 'id' key (published media ID)
    """
    url = f'{GRAPH_API_BASE}/{ig_user_id}/media_publish'

    resp = requests.post(url, data={
        'creation_id': container_id,
        'access_token': access_token,
    }, timeout=60)

    if resp.status_code != 200:
        logger.error(f"Media publish failed: {resp.status_code} — {resp.text}")
        return {'error': resp.text, 'status_code': resp.status_code}

    logger.info(f"Media published for {ig_user_id}: {resp.json().get('id')}")
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
    logger.warning(f"Fetched profile: {profile}")
    if not profile or 'id' not in profile:
        return {'success': False, 'error': 'Failed to fetch Instagram profile.'}

    return {
        'success': True,
        'ig_user_id': profile['user_id'],
        'username': profile.get('username', ''),
        'profile_picture_url': profile.get('profile_picture_url', ''),
        'access_token': long_token,
        'expires_at': expires_at,
    }
