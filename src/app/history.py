import logging
from collections import defaultdict

from django.utils import timezone

from app import statistics as stats

logger = logging.getLogger(__name__)




def get_user_consumable_media(user, start_date=None, end_date=None):
    """
    Get all individual consumable media items (movies, episodes, etc.) for a user.
    """
    user_media, media_count = stats.get_user_media(user, start_date, end_date)
    consumable_items = []
    
    # Media type handlers
    #"tv": _process_tv_shows,
    handlers = {
        "season": _process_seasons,
    }
    skipped_types = ["tv"]  # Media types to skip processing
    
    # Process each media type
    for media_type, queryset in user_media.items():
        if media_type in skipped_types:
            continue
        if media_type in handlers:
            items = handlers[media_type](queryset)
        else:
            items = _process_direct_media(queryset, media_type)
        consumable_items.extend(items)
    
    # Update media count for episodes
    updated_count = _update_media_count(media_count, consumable_items)
    
    _log_retrieval_info(user, consumable_items, start_date, end_date)
    
    return consumable_items, updated_count


def _process_tv_shows(tv_shows):
    """Process TV shows and extract individual episodes."""
    episodes = []
    for tv_show in tv_shows:
        for season in tv_show.seasons.all():
            episodes.extend(_extract_episodes_from_season(season, tv_show.item.title))
    return episodes


def _process_seasons(seasons):
    """Process seasons and extract individual episodes."""
    episodes = []
    for season in seasons:
        tv_title = season.related_tv.item.title if season.related_tv else "Unknown Show"
        episodes.extend(_extract_episodes_from_season(season, tv_title))
    return episodes


def _extract_episodes_from_season(season, tv_title):
    """Extract and format episodes from a season."""
    episodes = []
    for episode in season.episodes.all():
        episode.consumable_type = "episode"
        episode.display_title = _format_episode_title(
            tv_title, 
            season.item.season_number, 
            episode.item.episode_number,
            episode.item.title
        )
        episodes.append(episode)
    return episodes


def _format_episode_title(tv_title, season_number, episode_number, episode_title):
    """Format episode display title consistently."""
    base_title = f"{tv_title} - S{season_number}E{episode_number}"
    if episode_title and episode_title != tv_title:
        return f"{base_title}: {episode_title}"
    return base_title


def _process_direct_media(queryset, media_type):
    """Process media types that don't need episode extraction."""
    items = []
    for item in queryset:
        item.consumable_type = media_type
        item.display_title = item.item.title
        items.append(item)
    return items


def _update_media_count(media_count, consumable_items):
    """Update media count to reflect episodes instead of seasons/TV shows."""
    episode_count = sum(1 for item in consumable_items if item.consumable_type == "episode")
    
    if episode_count == 0:
        return media_count
    
    updated_count = media_count.copy()
    
    # Remove TV and season counts, add episode count
    removed_count = 0
    for media_type in ["tv", "season"]:
        if media_type in updated_count:
            removed_count += updated_count.pop(media_type)
    
    updated_count["episode"] = episode_count
    updated_count["total"] = updated_count["total"] - removed_count + episode_count
    
    return updated_count


def _log_retrieval_info(user, consumable_items, start_date, end_date):
    """Log information about retrieved media items."""
    date_range = "for all time" if start_date is None else f"from {start_date} to {end_date}"
    logger.info(
        "%s - Retrieved %d consumable media items %s",
        user,
        len(consumable_items),
        date_range,
    )


def get_consumable_media_timeline(consumable_items):
    """Build a timeline of consumable media organized by date."""
    timeline = defaultdict(list)
    for item in consumable_items:
        # Determine the date to use for timeline placement
        date_to_use = None
        
        if hasattr(item, "end_date") and item.end_date:
            date_to_use = timezone.localdate(item.end_date)
        elif hasattr(item, "start_date") and item.start_date:
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
                timezone.localtime(x.end_date) if hasattr(x, "end_date") and x.end_date 
                else timezone.localtime(x.start_date) if hasattr(x, "start_date") and x.start_date
                else timezone.now()
            ),
            reverse=True,
        )
        sorted_timeline[date] = sorted_items
    return sorted_timeline
