from .models import WatchHistory


def record_watch_history(user, media, episode=None, rewatch=False):
    """Record a watch history entry."""
    return WatchHistory.objects.create(
        user=user,
        media=media,
        episode=episode,
        rewatch=rewatch
    )

def get_user_watch_stats(user, days=None):
    """Get user's watch statistics."""
    qs = WatchHistory.objects.filter(user=user)
    
    if days:
        from datetime import timedelta

        from django.utils import timezone
        cutoff = timezone.now() - timedelta(days=days)
        qs = qs.filter(watched_date__gte=cutoff)
    
    return {
        'total': qs.count(),
        'movies': qs.filter(media__media_type='movie').count(),
        'episodes': qs.filter(media__media_type__in=['tv', 'anime']).count(),
        'unique_media': qs.values('media').distinct().count(),
    }