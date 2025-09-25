from .models import Episode, Item, WatchHistory


def record_watch_history(user, item, episode=None, rewatch=False, progress_minutes=None):
    """Record a watch history entry."""
    return WatchHistory.objects.create(
        user=user,
        item=item,
        episode=episode,
        rewatch=rewatch,
        progress_minutes=progress_minutes
    )

def get_user_watch_stats(user, days=None):
    """Get user's watch statistics."""
    temp_qs = WatchHistory.objects.all()
    print(temp_qs.count())
    qs = WatchHistory.objects.filter(user=user)
    
    if days:
        from datetime import timedelta

        from django.utils import timezone
        cutoff = timezone.now() - timedelta(days=days)
        qs = qs.filter(watched_date__gte=cutoff)
    
    return {
        'total': qs.count(),
        'movies': qs.filter(item__media_type='movie').count(),
        'episodes': qs.filter(item__media_type__in=['tv', 'anime']).count(),
        'unique_items': qs.values('item').distinct().count(),
    }