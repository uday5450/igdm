"""
Scheduler app — Views for creating, listing, and managing scheduled posts.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from instagram.models import InstagramAccount
from .models import ScheduledPost
from .forms import ScheduledPostForm


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
def scheduled_list(request):
    """List all scheduled posts for the active Instagram account."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    scheduled_posts = ScheduledPost.objects.filter(ig_account=ig_account)

    # Tab filtering
    tab = request.GET.get('tab', 'all')
    if tab == 'pending':
        scheduled_posts = scheduled_posts.filter(status='pending')
    elif tab == 'published':
        scheduled_posts = scheduled_posts.filter(status='published')
    elif tab == 'failed':
        scheduled_posts = scheduled_posts.filter(status='failed')

    return render(request, 'scheduler/list.html', {
        'scheduled_posts': scheduled_posts,
        'ig_account': ig_account,
        'active_tab': tab,
    })


@login_required
def scheduled_create(request):
    """Create a new scheduled post with file upload."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    if request.method == 'POST':
        form = ScheduledPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.ig_account = ig_account
            post.created_by = request.user
            post.save()

            # Generate public URLs from uploaded files
            post.media_url = post.generate_public_url(post.media_file)
            if post.thumbnail_file:
                post.thumbnail_url = post.generate_public_url(post.thumbnail_file)
            post.save(update_fields=['media_url', 'thumbnail_url'])

            messages.success(
                request,
                f'Post scheduled for {post.scheduled_at.strftime("%b %d, %Y at %I:%M %p")}!'
            )
            return redirect('scheduler:detail', post_id=post.id)
    else:
        form = ScheduledPostForm()

    return render(request, 'scheduler/create.html', {
        'form': form,
        'ig_account': ig_account,
    })


@login_required
def scheduled_detail(request, post_id):
    """View details of a scheduled post."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    post = get_object_or_404(ScheduledPost, id=post_id, ig_account=ig_account)

    return render(request, 'scheduler/detail.html', {
        'post': post,
        'ig_account': ig_account,
    })


@login_required
def scheduled_delete(request, post_id):
    """Delete a scheduled post (only if pending)."""
    ig_account = _get_active_ig_account(request)
    if not ig_account:
        messages.warning(request, 'Please connect an Instagram account first.')
        return redirect('instagram:connect')

    post = get_object_or_404(ScheduledPost, id=post_id, ig_account=ig_account)

    if not post.is_editable:
        messages.error(request, 'Cannot delete a post that has already been published or is currently publishing.')
        return redirect('scheduler:detail', post_id=post.id)

    if request.method == 'POST':
        post.delete()
        messages.info(request, 'Scheduled post deleted.')
        return redirect('scheduler:list')

    return render(request, 'scheduler/confirm_delete.html', {
        'post': post,
        'ig_account': ig_account,
    })
