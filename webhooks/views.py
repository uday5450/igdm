"""
Webhooks app — Webhook endpoint for Instagram events.
Handles GET verification and POST event processing.
"""
import json
import logging
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from instagram.models import InstagramAccount
from automations.engine import process_comment_event, process_story_event, process_dm_event
from .models import WebhookEventLog

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook_handler(request):
    """
    Instagram Webhook endpoint.

    GET: Verification challenge from Meta.
    POST: Incoming events (comments, story replies, DMs).
    """
    if request.method == 'GET':
        return _handle_verification(request)
    else:
        return _handle_event(request)


def _handle_verification(request):
    """
    Handle Meta's webhook verification challenge.
    Meta sends: hub.mode, hub.verify_token, hub.challenge
    We must return hub.challenge if verify_token matches.
    """
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode == 'subscribe' and token == settings.INSTAGRAM_WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verification successful")
        return HttpResponse(challenge, content_type='text/plain', status=200)
    else:
        logger.warning(f"Webhook verification failed: mode={mode}, token={token}")
        return HttpResponse('Verification failed', status=403)


def _handle_event(request):
    """
    Handle incoming webhook events from Instagram.
    Parses the payload, logs it, and triggers automations.
    """
    try:
        body = json.loads(request.body)
        logger.warning(f"BODY_handle_event ::::  {body}")
    except json.JSONDecodeError:
        logger.error("Webhook received invalid JSON")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    logger.info(f"Webhook received: {json.dumps(body)[:500]}")

    # Instagram webhooks have this structure:
    # { "object": "instagram", "entry": [ { "id": ..., "time": ..., "changes": [...] } ] }
    obj_type = body.get('object')
    if obj_type != 'instagram':
        logger.info(f"Ignoring non-Instagram webhook: {obj_type}")
        return JsonResponse({'status': 'ignored'}, status=200)

    entries = body.get('entry', [])

    for entry in entries:
        ig_user_id = str(entry.get('id', ''))
        changes = entry.get('changes', [])
        messaging = entry.get('messaging', [])

        # Find the IG account
        ig_account = None
        try:
            ig_account = InstagramAccount.objects.get(ig_user_id=ig_user_id)
        except InstagramAccount.DoesNotExist:
            logger.info(f"Webhook received for unregistered IG account: {ig_user_id} — storing event")

        # If no IG account found and no changes/messaging, store raw event
        if not ig_account and not changes and not messaging:
            WebhookEventLog.objects.create(
                event_type='other',
                ig_account=None,
                ig_user_id=ig_user_id,
                payload=body,
                processed=False,
                error_message='No IG account found in DB',
            )

        # Process field changes (comments)
        for change in changes:
            field = change.get('field', '')
            value = change.get('value', {})

            if field == 'comments':
                _process_comment_change(ig_user_id, value, body, ig_account)
            elif field == 'story_insights':
                # Story reply handling
                pass
            else:
                # Log unknown event types
                WebhookEventLog.objects.create(
                    event_type='other',
                    ig_account=ig_account,
                    ig_user_id=ig_user_id,
                    payload=body,
                    processed=False,
                )

        # Process messaging events (DMs, story replies)
        for msg_event in messaging:
            _process_messaging_event(ig_user_id, msg_event, body, ig_account)

    return JsonResponse({'status': 'ok'}, status=200)


def _process_comment_change(ig_user_id, value, full_payload, ig_account):
    """Process a comment webhook event."""
    comment_id = str(value.get('id', ''))
    comment_text = value.get('text', '')
    commenter_id = str(value.get('from', {}).get('id', ''))
    commenter_username = value.get('from', {}).get('username', '')
    media_id = str(value.get('media', {}).get('id', ''))
    parent_id = value.get('parent_id', '')

    # Skip the bot's own comments (prevents infinite reply loop)
    if commenter_id == ig_user_id:
        logger.info(f"Skipping own comment from @{commenter_username}")
        return

    # Skip reply comments (comments with parent_id are replies, not top-level)
    if parent_id:
        logger.info(f"Skipping reply comment (parent_id={parent_id}) from @{commenter_username}")
        return

    # Log the event
    event_log = WebhookEventLog.objects.create(
        event_type='comment',
        ig_account=ig_account,
        ig_user_id=ig_user_id,
        payload=full_payload,
        processed=False,
    )

    # Trigger automation engine
    try:
        result = process_comment_event(
            ig_user_id=ig_user_id,
            comment_id=comment_id,
            comment_text=comment_text,
            commenter_id=commenter_id,
            commenter_username=commenter_username,
            media_id=media_id,
        )
        event_log.processed = True
        event_log.process_result = result.get('action', '')
        event_log.error_message = result.get('error', '')
        event_log.save()
    except Exception as e:
        logger.exception(f"Error processing comment event: {e}")
        event_log.error_message = str(e)
        event_log.save()



def _process_messaging_event(ig_user_id, msg_event, full_payload, ig_account):
    """Process a messaging webhook event (DM or story reply)."""
    sender = msg_event.get('sender', {})
    sender_id = str(sender.get('id', ''))
    message = msg_event.get('message', {})
    message_text = message.get('text', '')

    # Skip read receipts (not actual messages)
    if 'read' in msg_event:
        logger.info(f'Skipping read receipt from {sender_id}')
        return

    # Skip message_edit events (edits to existing messages, not new messages)
    if 'message_edit' in msg_event:
        logger.info(f'Skipping message_edit event from {sender_id}')
        return

    # Skip reaction events
    if 'reaction' in msg_event:
        logger.info(f'Skipping reaction event from {sender_id}')
        return

    # Skip echo events (bot's own sent messages echoed back)
    if message.get('is_echo'):
        logger.info(f'Skipping echo message (bot own message)')
        return

    # Skip delivery events
    if 'delivery' in msg_event:
        logger.info(f'Skipping delivery event from {sender_id}')
        return

    # Skip if sender is the bot itself
    if sender_id == ig_user_id:
        logger.info(f'Skipping message from bot itself')
        return

    # Determine if this is a story reply
    is_story_reply = 'story' in message.get('attachments', [{}])[0].get('type', '') if message.get('attachments') else False

    if is_story_reply:
        event_type = 'story_reply'
    else:
        event_type = 'dm'

    # Log the event
    event_log = WebhookEventLog.objects.create(
        event_type=event_type,
        ig_account=ig_account,
        ig_user_id=ig_user_id,
        payload=full_payload,
        processed=False,
    )

    # Trigger automation engine for story replies
    if is_story_reply:
        try:
            result = process_story_event(
                ig_user_id=ig_user_id,
                sender_id=sender_id,
                sender_username=sender.get('username', ''),
                message_text=message_text,
            )
            event_log.processed = True
            event_log.process_result = result.get('action', '')
            event_log.error_message = result.get('error', '')
            event_log.save()
        except Exception as e:
            logger.exception(f"Error processing story event: {e}")
            event_log.error_message = str(e)
            event_log.save()
    else:
        try:
            result = process_dm_event(
                ig_user_id=ig_user_id,
                sender_id=sender_id,
                sender_username=sender.get('username', ''),
                message_text=message_text,
            )
            event_log.processed = True
            event_log.process_result = result.get('action', '')
            event_log.error_message = result.get('error', '')
            event_log.save()
        except Exception as e:
            logger.exception(f"Error processing DM event: {e}")
            event_log.error_message = str(e)
            event_log.save()
