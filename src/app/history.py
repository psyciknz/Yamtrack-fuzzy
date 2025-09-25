import logging
from collections import defaultdict
from datetime import timedelta

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from app import statistics as stats
from app.models import TV, BasicMedia, Episode, MediaTypes, Season
from app.templatetags import app_tags

logger = logging.getLogger(__name__)

from .models import Episode, Item


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
    
def get_user_consumable_media(user, start_date=None, end_date=None):
    """
    Get all individual consumable media items (movies, episodes, etc.) for a user.
    Uses the existing get_user_media function but focuses on individual consumable items.
    """
    # Use the existing statistics function to get user media
    user_media, media_count = stats.get_user_media(user, start_date, end_date)
    
    consumable_items = []
    
    # Process each media type from the existing function
    for media_type, queryset in user_media.items():
        if media_type == "tv":
            # For TV shows, we want the individual episodes, not the TV show itself
            for tv_show in queryset:
                for season in tv_show.seasons.all():
                    for episode in season.episodes.all():
                        episode.consumable_type = "episode"
                        episode.display_title = f"{tv_show.item.title} - S{season.item.season_number}E{episode.item.episode_number}"
                        if episode.item.title and episode.item.title != tv_show.item.title:
                            episode.display_title += f": {episode.item.title}"
                        consumable_items.append(episode)
        
        elif media_type == "season":
            # For seasons, we want the individual episodes
            for season in queryset:
                tv_title = season.related_tv.item.title if season.related_tv else "Unknown Show"
                for episode in season.episodes.all():
                    episode.consumable_type = "episode"
                    episode.display_title = f"{tv_title} - S{season.item.season_number}E{episode.item.episode_number}"
                    if episode.item.title and episode.item.title != tv_title:
                        episode.display_title += f": {episode.item.title}"
                    consumable_items.append(episode)
        
        else:
            # For other media types (movies, games, books, etc.), add them directly
            for item in queryset:
                item.consumable_type = media_type
                item.display_title = item.item.title
                consumable_items.append(item)
    
    # Update media count to reflect episodes instead of seasons/TV shows
    episode_count = sum(1 for item in consumable_items if item.consumable_type == "episode")
    if episode_count > 0:
        media_count["episode"] = episode_count
        # Remove TV and season counts since we're showing episodes instead
        if "tv" in media_count:
            media_count["total"] -= media_count["tv"]
            del media_count["tv"]
        if "season" in media_count:
            media_count["total"] -= media_count["season"]
            del media_count["season"]
        # Add episode count to total
        media_count["total"] += episode_count
    
    logger.info(
        "%s - Retrieved %d consumable media items %s",
        user,
        len(consumable_items),
        "for all time" if start_date is None else f"from {start_date} to {end_date}",
    )
    
    return consumable_items, media_count


def get_consumable_media_timeline(consumable_items):
    """Build a timeline of consumable media organized by date."""
    timeline = defaultdict(list)
    
    for item in consumable_items:
        # Determine the date to use for timeline placement
        date_to_use = None
        
        if hasattr(item, 'end_date') and item.end_date:
            date_to_use = timezone.localdate(item.end_date)
        elif hasattr(item, 'start_date') and item.start_date:
            date_to_use = timezone.localdate(item.start_date)
        
        if date_to_use:
            timeline[date_to_use].append(item)
    
    # Sort timeline by date (most recent first) and items within each date
    sorted_timeline = {}
    for date in sorted(timeline.keys(), reverse=True):
        # Sort items within the date by end_date or start_date
        sorted_items = sorted(
            timeline[date],
            key=lambda x: (
                timezone.localtime(x.end_date) if hasattr(x, 'end_date') and x.end_date 
                else timezone.localtime(x.start_date) if hasattr(x, 'start_date') and x.start_date
                else timezone.now()
            ),
            reverse=True
        )
        sorted_timeline[date] = sorted_items
    
    return sorted_timeline