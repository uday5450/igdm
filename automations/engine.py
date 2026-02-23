"""
Automations app — Runtime engine for processing webhook events.
Handles comment → keyword match → send DM → log contact.
"""
import logging
from django.utils import timezone
from instagram.models import InstagramAccount
from instagram.services import decrypt_token, send_dm, send_dm_by_user_id, reply_to_comment, check_user_follows
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

        # Step 2: Follow check (if enabled) — check BEFORE sending DM
        if automation.ask_follow_enabled and automation.ask_follow_message:
            user_follows = check_user_follows(access_token, commenter_id)
            print(f"\n🔍 FOLLOW CHECK → @{commenter_username}: {'✅ Following' if user_follows else '❌ Not following'}")

            if not user_follows:
                # User doesn't follow — send follow-ask message instead of DM
                return _send_follow_ask_message(
                    access_token, ig_user_id, commenter_id, commenter_username,
                    ig_account, None, automation, is_resend=False,
                    comment_id=comment_id, comment_text=comment_text,
                    media_id=media_id,
                )

        # Step 3: Send DM (or Opening Message if enabled)
        if automation.opening_message_enabled and automation.opening_message:
            # Per-user-per-reel check: has this user already been contacted for this reel?
            existing_contact = Contact.objects.filter(
                ig_account=ig_account,
                automation=automation,
                ig_user_id=commenter_id,
                media_id=media_id,
            ).order_by('-created_at').first()

            if existing_contact and existing_contact.dm_sent:
                # User already received the full DM on this reel — send DM directly again
                print(f"\n📩 DM (repeat, already received) → @{commenter_username}")
                print(f"   Message: {automation.dm_message}")
                result = send_dm(access_token, ig_user_id, comment_id, automation.dm_message, buttons=automation.dm_buttons or None)
                print(f"   Response: {result}")
                if 'error' not in result:
                    print(f"   ✅ DM SENT (repeat)")
                else:
                    print(f"   ❌ DM FAILED")
                print(f"{'='*50}\n")

                # Create new contact record for this comment
                Contact.objects.create(
                    ig_account=ig_account,
                    automation=automation,
                    ig_user_id=commenter_id,
                    username=commenter_username,
                    comment_id=comment_id,
                    comment_text=comment_text,
                    media_id=media_id,
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

            elif existing_contact and existing_contact.opening_sent and not existing_contact.dm_sent:
                # User got opening message but didn't click button — resend opening message with button
                # Build quick reply button for opening message
                opening_qr = [{'title': automation.opening_message_button_text or 'Send me the link', 'payload': 'SEND_LINK'}]
                print(f"\n📩 OPENING MESSAGE (resend) → @{commenter_username}")
                print(f"   Message: {automation.opening_message}")
                result = send_dm(access_token, ig_user_id, comment_id, automation.opening_message, quick_replies=opening_qr)
                print(f"   Response: {result}")
                if 'error' not in result:
                    print(f"   ✅ Opening Message RESENT")
                else:
                    print(f"   ❌ Opening Message FAILED")
                print(f"{'='*50}\n")

                # Create new contact record
                Contact.objects.create(
                    ig_account=ig_account,
                    automation=automation,
                    ig_user_id=commenter_id,
                    username=commenter_username,
                    comment_id=comment_id,
                    comment_text=comment_text,
                    media_id=media_id,
                    tag=automation.tag,
                    opening_sent=True,
                    dm_sent=False,
                    dm_error=result.get('error', ''),
                )

                automation.total_triggers += 1
                if 'error' in result:
                    automation.total_failures += 1
                automation.save()

                return {
                    'success': 'error' not in result,
                    'action': 'opening_resent' if 'error' not in result else 'opening_failed',
                    'error': result.get('error', ''),
                }

            else:
                # First time: send opening message
                # Build quick reply button for opening message
                opening_qr = [{'title': automation.opening_message_button_text or 'Send me the link', 'payload': 'SEND_LINK'}]
                print(f"\n📩 OPENING MESSAGE → @{commenter_username}")
                print(f"   Message: {automation.opening_message}")
                result = send_dm(access_token, ig_user_id, comment_id, automation.opening_message, quick_replies=opening_qr)
                print(f"   Response: {result}")
                if 'error' not in result:
                    print(f"   ✅ Opening Message SENT")
                else:
                    print(f"   ❌ Opening Message FAILED")
                print(f"{'='*50}\n")

                # Create contact with opening_sent=True (actual DM pending user response)
                contact = Contact.objects.create(
                    ig_account=ig_account,
                    automation=automation,
                    ig_user_id=commenter_id,
                    username=commenter_username,
                    comment_id=comment_id,
                    comment_text=comment_text,
                    media_id=media_id,
                    tag=automation.tag,
                    opening_sent=True,
                    dm_sent=False,
                    dm_error=result.get('error', ''),
                )

                automation.total_triggers += 1
                if 'error' not in result:
                    logger.info(f"Opening message sent to @{commenter_username} via automation '{automation.name}'")
                else:
                    automation.total_failures += 1
                    logger.error(f"Opening message failed for @{commenter_username}: {result.get('error')}")
                automation.save()

                return {
                    'success': 'error' not in result,
                    'action': 'opening_sent' if 'error' not in result else 'opening_failed',
                    'error': result.get('error', ''),
                }
        else:
            # Standard flow: send DM directly
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
                media_id=media_id,
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


def process_dm_event(ig_user_id: str, sender_id: str, sender_username: str,
                     message_text: str = '') -> dict:
    try:
        ig_account = InstagramAccount.objects.get(ig_user_id=ig_user_id)
    except InstagramAccount.DoesNotExist:
        return {'success': False, 'action': 'skip', 'error': 'IG account not found'}

    if not ig_account.is_token_valid:
        _pause_all_automations(ig_account, 'Access token expired')
        return {'success': False, 'action': 'paused', 'error': 'Token expired'}

    # === Check for pending follow-check contacts (from comment-stage follow check) ===
    follow_pending = Contact.objects.filter(
        ig_account=ig_account,
        ig_user_id=sender_id,
        follow_check_sent=True,
        follow_verified=False,
        dm_sent=False,
        automation__template_type='comment_dm',
        automation__is_active=True,
        automation__is_paused=False,
    ).select_related('automation').order_by('-created_at').first()

    if follow_pending:
        automation = follow_pending.automation
        access_token = decrypt_token(ig_account.access_token_encrypted)
        if not access_token:
            _pause_all_automations(ig_account, 'Failed to decrypt access token')
            return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}

        print(f"\n{'='*50}")
        print(f"🔍 FOLLOW CHECK (DM response) → @{sender_username}")
        print(f"   Automation: '{automation.name}'")

        user_follows = check_user_follows(access_token, sender_id)
        print(f"   Follows: {user_follows}")

        if user_follows:
            # User follows! Send actual DM
            return _send_actual_dm_after_follow(
                access_token, ig_user_id, sender_id, sender_username,
                follow_pending, automation
            )
        else:
            # User doesn't follow, resend the follow-ask message
            return _send_follow_ask_message(
                access_token, ig_user_id, sender_id, sender_username,
                ig_account, follow_pending, automation, is_resend=True
            )

    # === Check for pending opening messages from comment_dm automations ===
    # When a user received an opening message (from a comment automation),
    # and they respond/click, we send the actual DM with the link.
    pending_contacts = Contact.objects.filter(
        ig_account=ig_account,
        ig_user_id=sender_id,
        opening_sent=True,
        dm_sent=False,
        automation__template_type='comment_dm',
        automation__is_active=True,
        automation__is_paused=False,
    ).select_related('automation')

    for contact in pending_contacts:
        automation = contact.automation
        if not automation:
            continue

        access_token = decrypt_token(ig_account.access_token_encrypted)
        if not access_token:
            _pause_all_automations(ig_account, 'Failed to decrypt access token')
            return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}

        # Send actual DM directly (user responded to opening message)
        print(f"\n{'='*50}")
        print(f"📩 FOLLOW-UP DM (after opening) → @{sender_username}")
        print(f"   Automation: '{automation.name}'")
        print(f"   Message: {automation.dm_message}")
        result = send_dm_by_user_id(access_token, ig_user_id, sender_id, automation.dm_message, buttons=automation.dm_buttons or None)
        print(f"   Response: {result}")
        if 'error' not in result:
            print(f"   ✅ Follow-up DM SENT")
        else:
            print(f"   ❌ Follow-up DM FAILED")
        print(f"{'='*50}\n")

        contact.dm_sent = 'error' not in result
        contact.dm_sent_at = timezone.now() if 'error' not in result else None
        contact.dm_error = result.get('error', '')
        contact.save()

        if 'error' not in result:
            automation.total_dms_sent += 1
        else:
            automation.total_failures += 1
        automation.save()

        return {
            'success': 'error' not in result,
            'action': 'followup_dm_sent' if 'error' not in result else 'dm_failed',
            'error': result.get('error', ''),
        }

    # === Standard dm_reply automations ===
    automations = Automation.objects.filter(
        ig_account=ig_account,
        is_active=True,
        is_paused=False,
        template_type='dm_reply',
    )

    for automation in automations:
        access_token = decrypt_token(ig_account.access_token_encrypted)
        if not access_token:
            _pause_all_automations(ig_account, 'Failed to decrypt access token')
            return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}

        already_contact = Contact.objects.filter(
            ig_account=ig_account,
            automation=automation,
            ig_user_id=sender_id,
        ).exists()

        if automation.opening_message_enabled and not already_contact:
            result = send_dm_by_user_id(access_token, ig_user_id, sender_id, automation.opening_message or automation.dm_message, buttons=automation.dm_buttons or None)
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
                'action': 'opening_sent' if 'error' not in result else 'dm_failed',
                'error': result.get('error', ''),
            }

        if automation.matches_keyword(message_text):
            access_token = decrypt_token(ig_account.access_token_encrypted)
            if not access_token:
                _pause_all_automations(ig_account, 'Failed to decrypt access token')
                return {'success': False, 'action': 'paused', 'error': 'Token decryption failed'}
            result = send_dm_by_user_id(access_token, ig_user_id, sender_id, automation.dm_message, buttons=automation.dm_buttons or None)
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


def _send_follow_ask_message(access_token, ig_user_id, sender_id, sender_username,
                              ig_account, contact, automation, is_resend=False,
                              comment_id='', comment_text='', media_id=''):
    """Send 'please follow me' message with Visit Profile CTA button + I'm following quick reply.
    
    Called from comment stage (contact=None, creates new contact) or DM stage (contact exists).
    """
    tag = 'resend' if is_resend else 'first'
    print(f"\n{'='*50}")
    print(f"🔔 FOLLOW-ASK ({tag}) → @{sender_username}")
    print(f"   Automation: '{automation.name}'")
    print(f"   Message: {automation.ask_follow_message}")

    # Message 1: CTA card button for "Visit Profile" (opens profile URL, card-style like "Send me the link")
    profile_url = f"https://instagram.com/{ig_account.username}"
    visit_btn = [{'title': '🌟 Visit Profile', 'url': profile_url}]
    send_dm_by_user_id(
        access_token, ig_user_id, sender_id,
        automation.ask_follow_message,
        buttons=visit_btn
    )

    # Message 2: Quick reply for "I'm following" — this triggers the follow check when user taps it
    follow_qr = [{'title': "✅ I'm following", 'payload': 'IM_FOLLOWING'}]
    result = send_dm_by_user_id(
        access_token, ig_user_id, sender_id,
        "Once you've followed, tap the button below 👇",
        quick_replies=follow_qr
    )

    print(f"   Response: {result}")
    if 'error' not in result:
        print(f"   ✅ Follow-ask message SENT")
    else:
        print(f"   ❌ Follow-ask message FAILED")
    print(f"{'='*50}\n")

    # Create or update contact record
    if contact is None:
        # Called from comment stage — create new contact
        contact = Contact.objects.create(
            ig_account=ig_account,
            automation=automation,
            ig_user_id=sender_id,
            username=sender_username,
            comment_id=comment_id,
            comment_text=comment_text,
            media_id=media_id,
            tag=automation.tag,
            follow_check_sent=True,
            dm_sent=False,
            dm_error=result.get('error', ''),
        )
    else:
        # Called from DM stage — update existing contact
        contact.follow_check_sent = True
        contact.dm_error = result.get('error', '')
        contact.save()

    automation.total_triggers += 1
    if 'error' in result:
        automation.total_failures += 1
    automation.save()

    return {
        'success': 'error' not in result,
        'action': f'follow_ask_{"resent" if is_resend else "sent"}' if 'error' not in result else 'follow_ask_failed',
        'error': result.get('error', ''),
    }


def _send_actual_dm_after_follow(access_token, ig_user_id, sender_id, sender_username,
                                  contact, automation):
    """Send the actual DM after user has been verified as a follower."""
    print(f"   ✅ User follows! Sending actual DM...")
    print(f"   Message: {automation.dm_message}")

    result = send_dm_by_user_id(
        access_token, ig_user_id, sender_id,
        automation.dm_message, buttons=automation.dm_buttons or None
    )
    print(f"   Response: {result}")
    if 'error' not in result:
        print(f"   ✅ Actual DM SENT (after follow verification)")
    else:
        print(f"   ❌ Actual DM FAILED")
    print(f"{'='*50}\n")

    # Update contact record
    contact.follow_verified = True
    contact.dm_sent = 'error' not in result
    contact.dm_sent_at = timezone.now() if 'error' not in result else None
    contact.dm_error = result.get('error', '')
    contact.save()

    # Update automation stats
    if 'error' not in result:
        automation.total_dms_sent += 1
    else:
        automation.total_failures += 1
    automation.save()

    return {
        'success': 'error' not in result,
        'action': 'followup_dm_sent' if 'error' not in result else 'dm_failed',
        'error': result.get('error', ''),
    }


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
