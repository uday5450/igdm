"""
Automations app — Runtime engine for processing webhook events.
Handles comment → keyword match → send DM → log contact.
"""
import logging
from django.utils import timezone
from instagram.models import InstagramAccount
from instagram.services import decrypt_token, send_dm, send_dm_by_user_id, reply_to_comment
from .models import Automation, Contact

logger = logging.getLogger(__name__)


def process_comment_event(ig_user_id: str, comment_id: str, comment_text: str,
                          commenter_id: str, commenter_username: str,
                          media_id: str = '') -> dict:
    """
    Process an incoming comment event:
    1. Find the Instagram account
    2. Find active automation matching the media/keywords
    3. Send DM via comment_id (policy-safe)
    4. Log contact

    Returns: {'success': bool, 'action': str, 'error': str}
    """
    # Find the IG account
    try:
        ig_account = InstagramAccount.objects.get(ig_user_id=ig_user_id)
    except InstagramAccount.DoesNotExist:
        logger.warning(f"No IG account found for user_id={ig_user_id}")
        return {'success': False, 'action': 'skip', 'error': 'IG account not found'}

    # Check token validity
    if not ig_account.is_token_valid:
        logger.warning(f"Token expired for @{ig_account.username}")
        _pause_all_automations(ig_account, 'Access token expired')
        return {'success': False, 'action': 'paused', 'error': 'Token expired'}

    # Find active automations for this account
    automations = Automation.objects.filter(
        ig_account=ig_account,
        is_active=True,
        is_paused=False,
        template_type='comment_dm',
    )
    print(f"\n🔍 Found {automations.count()} active automations for @{ig_account.username}")

    if media_id:
        # Filter by specific post or automations targeting any post
        automations = automations.filter(
            models_Q_target_post(media_id)
        )
        print(f"   After post filter (media_id={media_id}): {automations.count()} automations")

    for automation in automations:
        print(f"\n📋 Automation: '{automation.name}'")
        print(f"   Keywords: {automation.keywords} (json: {automation.keywords_json})")
        print(f"   Comment text: '{comment_text}'")

        # Check keyword match
        match = automation.matches_keyword(comment_text)
        print(f"   Keyword match: {match}")
        if not match:
            continue

        # Check if we already processed this exact comment (webhook retry protection)
        already_processed = Contact.objects.filter(
            ig_account=ig_account,
            automation=automation,
            comment_id=comment_id,
        ).exists()

        if already_processed:
            print(f"   ⚠️ Already processed comment {comment_id}")
            logger.info(f"Comment {comment_id} already processed for automation '{automation.name}'")
            continue

        # Decrypt access token
        access_token = decrypt_token(ig_account.access_token_encrypted)
        if not access_token:
            _pause_all_automations(ig_account, 'Failed to decrypt access token')
            return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}

        # Step 1: Public reply (if enabled)
        reply_sent = False
        if automation.public_reply_enabled:
            reply_msg = automation.get_random_reply()
            if reply_msg:
                reply_msg = f"@{commenter_username} {reply_msg}"
                print(f"\n{'='*50}")
                print(f"📝 COMMENT REPLY → @{commenter_username}")
                print(f"   Message: {reply_msg}")
                reply_result = reply_to_comment(access_token, comment_id, reply_msg)
                print(f"   Response: {reply_result}")
                if 'error' in reply_result:
                    print(f"   ❌ Reply FAILED")
                    logger.warning(f"Comment reply failed for @{commenter_username}: {reply_result.get('error')}")
                else:
                    print(f"   ✅ Reply SENT")
                    reply_sent = True
                    logger.info(f"Public reply sent to @{commenter_username}: {reply_msg}")

        # Step 2: Send the DM
        print(f"\n📩 DM → @{commenter_username}")
        print(f"   Message: {automation.dm_message}")
        result = send_dm(access_token, ig_user_id, comment_id, automation.dm_message, buttons=automation.dm_buttons or None)
        print(f"   Response: {result}")
        if 'error' not in result:
            print(f"   ✅ DM SENT")
        else:
            print(f"   ❌ DM FAILED")
        print(f"{'='*50}\n")

        # Create contact record
        contact = Contact.objects.create(
            ig_account=ig_account,
            automation=automation,
            ig_user_id=commenter_id,
            username=commenter_username,
            comment_id=comment_id,
            comment_text=comment_text,
            tag=automation.tag,
            dm_sent='error' not in result,
            dm_sent_at=timezone.now() if 'error' not in result else None,
            dm_error=result.get('error', ''),
        )

        # Update automation stats
        automation.total_triggers += 1
        if 'error' not in result:
            automation.total_dms_sent += 1
            logger.info(f"DM sent to @{commenter_username} via automation '{automation.name}'")
        else:
            automation.total_failures += 1
            logger.error(f"DM failed for @{commenter_username}: {result.get('error')}")
        automation.save()

        return {
            'success': 'error' not in result,
            'action': 'dm_sent' if 'error' not in result else 'dm_failed',
            'error': result.get('error', ''),
        }

    return {'success': True, 'action': 'no_match', 'error': ''}


def process_story_event(ig_user_id: str, sender_id: str, sender_username: str,
                        message_text: str = '') -> dict:
    """
    Process a story reply event.
    """
    try:
        ig_account = InstagramAccount.objects.get(ig_user_id=ig_user_id)
    except InstagramAccount.DoesNotExist:
        return {'success': False, 'action': 'skip', 'error': 'IG account not found'}

    if not ig_account.is_token_valid:
        _pause_all_automations(ig_account, 'Access token expired')
        return {'success': False, 'action': 'paused', 'error': 'Token expired'}

    automations = Automation.objects.filter(
        ig_account=ig_account,
        is_active=True,
        is_paused=False,
        template_type='story_dm',
    )

    for automation in automations:
        if not automation.matches_keyword(message_text):
            continue

        already_sent = Contact.objects.filter(
            ig_account=ig_account,
            automation=automation,
            ig_user_id=sender_id,
        ).exists()

        if already_sent:
            continue

        access_token = decrypt_token(ig_account.access_token_encrypted)
        if not access_token:
            _pause_all_automations(ig_account, 'Failed to decrypt access token')
            return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}

        result = send_dm_by_user_id(access_token, ig_user_id, sender_id, automation.dm_message)

        Contact.objects.create(
            ig_account=ig_account,
            automation=automation,
            ig_user_id=sender_id,
            username=sender_username,
            comment_text=message_text,
            tag=automation.tag,
            dm_sent='error' not in result,
            dm_sent_at=timezone.now() if 'error' not in result else None,
            dm_error=result.get('error', ''),
        )

        automation.total_triggers += 1
        if 'error' not in result:
            automation.total_dms_sent += 1
        else:
            automation.total_failures += 1
        automation.save()

        return {
            'success': 'error' not in result,
            'action': 'dm_sent' if 'error' not in result else 'dm_failed',
            'error': result.get('error', ''),
        }

    return {'success': True, 'action': 'no_match', 'error': ''}


def models_Q_target_post(media_id: str):
    """Build a Q filter for target_post_id matching."""
    from django.db.models import Q
    return Q(target_post_id=media_id) | Q(target_post_id='')


def _pause_all_automations(ig_account, reason: str):
    """Pause all active automations for an IG account."""
    count = Automation.objects.filter(
        ig_account=ig_account,
        is_active=True,
    ).update(is_paused=True, pause_reason=reason)
    logger.warning(f"Paused {count} automations for @{ig_account.username}: {reason}")
