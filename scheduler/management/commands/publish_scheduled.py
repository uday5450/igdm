"""
Management command to publish scheduled Instagram posts.
Run periodically via cron: * * * * * python manage.py publish_scheduled
"""
import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from scheduler.models import ScheduledPost
from instagram.services import (
    get_valid_access_token,
    create_media_container,
    check_container_status,
    publish_media_container,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Publish scheduled Instagram posts that are due'

    def handle(self, *args, **options):
        now = timezone.now()
        due_posts = ScheduledPost.objects.filter(
            status='pending',
            scheduled_at__lte=now,
        ).select_related('ig_account')

        if not due_posts.exists():
            self.stdout.write('No scheduled posts are due.')
            return

        self.stdout.write(f'Found {due_posts.count()} post(s) to publish...')

        for post in due_posts:
            self.publish_post(post)

    def publish_post(self, post):
        """Attempt to publish a single scheduled post."""
        self.stdout.write(f'\n📌 Publishing: {post}')

        # Mark as publishing
        post.status = 'publishing'
        post.save(update_fields=['status', 'updated_at'])

        try:
            # Get access token (auto-refreshes if expired)
            ig_account = post.ig_account
            access_token = get_valid_access_token(ig_account)
            if not access_token:
                raise Exception('Could not get a valid access token. Token may be expired and refresh failed. Please reconnect the account.')

            ig_user_id = ig_account.ig_user_id

            # Step 1: Create container
            media_type = 'REELS' if post.post_type == 'reel' else None
            cover_url = post.thumbnail_url if post.post_type == 'reel' and post.thumbnail_url else None

            self.stdout.write(f'  → Creating container (type={post.post_type})...')
            container_result = create_media_container(
                access_token=access_token,
                ig_user_id=ig_user_id,
                media_url=post.media_url,
                media_type=media_type,
                caption=post.caption,
                cover_url=cover_url,
                share_to_feed=post.share_to_feed,
            )

            if 'error' in container_result or 'id' not in container_result:
                error_msg = container_result.get('error', str(container_result))
                raise Exception(f'Container creation failed: {error_msg}')

            container_id = container_result['id']
            post.ig_container_id = container_id
            post.save(update_fields=['ig_container_id', 'updated_at'])
            self.stdout.write(f'  ✓ Container created: {container_id}')

            # Step 2: Wait for container to be ready (for videos)
            if post.post_type == 'reel':
                self.stdout.write('  → Waiting for video processing...')
                max_retries = 30
                for attempt in range(max_retries):
                    status_result = check_container_status(access_token, container_id)
                    status_code = status_result.get('status_code', '')

                    if status_code == 'FINISHED':
                        self.stdout.write('  ✓ Video processing complete')
                        break
                    elif status_code == 'ERROR':
                        raise Exception(f'Video processing failed: {status_result}')
                    elif status_code == 'IN_PROGRESS':
                        time.sleep(10)  # Wait 10 seconds before checking again
                    else:
                        time.sleep(5)

                    if attempt == max_retries - 1:
                        raise Exception(f'Video processing timed out after {max_retries * 10}s')

            # Step 3: Publish
            self.stdout.write('  → Publishing...')
            publish_result = publish_media_container(access_token, ig_user_id, container_id)

            if 'error' in publish_result or 'id' not in publish_result:
                error_msg = publish_result.get('error', str(publish_result))
                raise Exception(f'Publishing failed: {error_msg}')

            media_id = publish_result['id']
            post.ig_media_id = media_id
            post.status = 'published'
            post.published_at = timezone.now()
            post.save(update_fields=['ig_media_id', 'status', 'published_at', 'updated_at'])

            self.stdout.write(self.style.SUCCESS(f'  ✅ Published! Media ID: {media_id}'))

        except Exception as e:
            error_msg = str(e)
            post.status = 'failed'
            post.error_message = error_msg
            post.save(update_fields=['status', 'error_message', 'updated_at'])
            self.stdout.write(self.style.ERROR(f'  ❌ Failed: {error_msg}'))
            logger.exception(f'Failed to publish scheduled post {post.id}: {error_msg}')
