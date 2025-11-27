"""Utilities for caching the History page."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.utils import formats, timezone

from app import helpers
from app.models import Episode, Game, Item, MediaTypes, Movie

logger = logging.getLogger(__name__)

HISTORY_CACHE_PREFIX = "history_page_v9"
HISTORY_CACHE_TIMEOUT = 60 * 60 * 6  # 6 hours
HISTORY_STALE_AFTER = timedelta(minutes=15)
HISTORY_DAYS_PER_PAGE = 30
HISTORY_REFRESH_LOCK_PREFIX = f"{HISTORY_CACHE_PREFIX}_refresh_lock"


def _cache_key(user_id: int, logging_style: str) -> str:
    return f"{HISTORY_CACHE_PREFIX}_{user_id}_{logging_style or 'repeats'}"


def _refresh_lock_key(user_id: int, logging_style: str) -> str:
    return f"{HISTORY_REFRESH_LOCK_PREFIX}_{user_id}_{logging_style or 'repeats'}"


def _localize_datetime(value):
    """Convert a datetime to the current timezone if possible."""
    if value is None:
        return None

    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())

    return timezone.localtime(value)


def _resolve_runtime_minutes(*items):
    """Pick the first usable runtime value from the provided items."""
    for item in items:
        if not item:
            continue

        runtime = getattr(item, "runtime_minutes", None)
        if runtime and runtime < 999999:
            return runtime

    return 0


def _get_episode_poster(episode):
    """Prefer show/season posters over episodic stills for consistent cards."""
    season_item = getattr(episode.related_season, "item", None)
    episode_item = getattr(episode, "item", None)
    tv_item = getattr(getattr(episode.related_season, "related_tv", None), "item", None)

    poster = (
        getattr(tv_item, "image", None)
        or getattr(season_item, "image", None)
        or getattr(episode.item, "image", None)
        or settings.IMG_NONE
    )

    return poster


def _get_episode_display_title(episode, episode_title_map=None):
    """Derive a best-effort episode title from local data only."""
    episode_item = getattr(episode, "item", None)
    season_item = getattr(episode.related_season, "item", None)

    key = None
    if episode_item:
        key = (
            getattr(episode_item, "media_id", None),
            getattr(episode_item, "source", None),
            getattr(episode_item, "season_number", None),
            getattr(episode_item, "episode_number", None),
        )

    if episode_title_map and key in episode_title_map:
        title_candidate = episode_title_map.get(key)
        if title_candidate:
            return title_candidate
    # Prefer the stored episode title if present.
    if episode_item and episode_item.title:
        return episode_item.title
    if season_item and season_item.title:
        return season_item.title
    return ""


def _format_game_hours(minutes: int) -> str:
    """Show hours only if at least 1h, otherwise keep minutes."""
    minutes = minutes or 0
    if minutes >= 60:
        return f"{minutes // 60}h"
    return f"{minutes}min"


def _build_episode_entry(episode, episode_title_map=None):
    played_at_local = _localize_datetime(episode.end_date or episode.created_at)
    if not played_at_local:
        return None

    episode_item = getattr(episode, "item", None)
    season_item = getattr(episode.related_season, "item", None)
    tv_item = getattr(getattr(episode.related_season, "related_tv", None), "item", None)
    runtime_minutes = _resolve_runtime_minutes(
        episode.item,
        season_item,
        tv_item,
    )

    display_title = _get_episode_display_title(episode, episode_title_map)

    return {
        "media_type": MediaTypes.EPISODE.value,
        "item": season_item or episode.item,
        "poster": _get_episode_poster(episode),
        "title": episode_item.title if episode_item else (season_item.title if season_item else episode.item.title),
        "display_title": display_title,
        "episode_label": (
            f"{episode.item.season_number}x{episode.item.episode_number:02d}"
            if episode.item.season_number is not None
            and episode.item.episode_number is not None
            else None
        ),
        "episode_code": (
            f"S{episode.item.season_number:02d}E{episode.item.episode_number:02d}"
            if episode.item.season_number is not None
            and episode.item.episode_number is not None
            else None
        ),
        "played_at_local": played_at_local,
        "runtime_minutes": runtime_minutes,
        "runtime_display": helpers.minutes_to_hhmm(runtime_minutes) if runtime_minutes else None,
    }


def _build_movie_entry(movie):
    played_at_local = _localize_datetime(movie.end_date or movie.created_at)
    if not played_at_local:
        return None

    runtime_minutes = _resolve_runtime_minutes(movie.item)

    return {
        "media_type": MediaTypes.MOVIE.value,
        "item": movie.item,
        "poster": movie.item.image or settings.IMG_NONE,
        "title": movie.item.title,
        "display_title": movie.item.title,
        "play_count": 1,
        "episode_label": None,
        "episode_code": None,
        "played_at_local": played_at_local,
        "runtime_minutes": runtime_minutes,
        "runtime_display": helpers.minutes_to_hhmm(runtime_minutes) if runtime_minutes else None,
    }


def build_history_days(user):
    """Build the list of grouped history entries for a user."""
    game_logging_style = getattr(user, "game_logging_style", "repeats")

    episodes = (
        Episode.objects.filter(
            related_season__user=user,
            end_date__isnull=False,
        )
        .select_related(
            "item",
            "related_season__item",
            "related_season__related_tv__item",
        )
        .order_by("-end_date")
    )
    movies_qs = Movie.objects.filter(
        user=user,
        end_date__isnull=False,
    ).select_related("item")

    movies = movies_qs.order_by("-end_date")
    movie_play_counts = (
        movies_qs.values("item__media_id", "item__source")
        .annotate(play_count=models.Count("id"))
        .order_by()
    )
    movie_play_map = {
        (row["item__media_id"], row["item__source"]): row["play_count"]
        for row in movie_play_counts
    }
    games = (
        Game.objects.filter(user=user)
        .select_related("item")
        .order_by("-end_date", "-created_at")
    )

    entries = []

    # Build a lookup of episode titles from stored items to avoid provider calls
    episode_keys = []
    for ep in episodes:
        ep_item = getattr(ep, "item", None)
        if not ep_item:
            continue
        episode_keys.append(
            (
                getattr(ep_item, "media_id", None),
                getattr(ep_item, "source", None),
                getattr(ep_item, "season_number", None),
                getattr(ep_item, "episode_number", None),
            ),
        )

    episode_keys = [key for key in episode_keys if all(key)]
    episode_title_map = {}
    if episode_keys:
        media_ids = {k[0] for k in episode_keys}
        sources = {k[1] for k in episode_keys}
        season_numbers = {k[2] for k in episode_keys}
        episode_numbers = {k[3] for k in episode_keys}

        titles_qs = Item.objects.filter(
            media_type=MediaTypes.EPISODE.value,
            media_id__in=media_ids,
            source__in=sources,
            season_number__in=season_numbers,
            episode_number__in=episode_numbers,
        ).exclude(title__isnull=True).exclude(title="")

        for item in titles_qs:
            key = (
                item.media_id,
                item.source,
                item.season_number,
                item.episode_number,
            )
            if key not in episode_title_map:
                episode_title_map[key] = item.title

    for episode in episodes:
        entry = _build_episode_entry(episode, episode_title_map)
        if entry:
            entries.append(entry)

    for movie in movies:
        entry = _build_movie_entry(movie)
        if not entry:
            continue
        key = (movie.item.media_id, movie.item.source)
        annotated = movie_play_map.get(key)
        repeat_attr = getattr(movie, "repeats", None)
        play_count = annotated or repeat_attr or 1
        entry["play_count"] = play_count
        entries.append(entry)

    # Games
    if game_logging_style == "sessions":
        for game in games:
            if not (game.start_date or game.end_date):
                continue

            activity_dt = game.end_date or game.start_date or game.created_at
            played_at_local = _localize_datetime(activity_dt)
            if not played_at_local:
                continue
            runtime_minutes = game.progress or 0
            start_local = _localize_datetime(game.start_date).date() if game.start_date else None
            end_local = _localize_datetime(game.end_date).date() if game.end_date else played_at_local.date()
            if not start_local:
                start_local = end_local
            date_range_display = f"{formats.date_format(start_local, 'M j')} - {formats.date_format(end_local, 'M j')}"

            entries.append(
                {
                    "media_type": MediaTypes.GAME.value,
                    "item": game.item,
                    "poster": game.item.image or settings.IMG_NONE,
                    "title": game.item.title,
                    "display_title": game.item.title,
                    "progress_display": _format_game_hours(runtime_minutes),
                    "date_range_display": date_range_display,
                    "episode_label": None,
                    "episode_code": None,
                    "played_at_local": played_at_local,
                    "runtime_minutes": runtime_minutes,
                    "runtime_display": helpers.minutes_to_hhmm(runtime_minutes) if runtime_minutes else None,
                },
            )
    else:
        # repeats style: spread playtime evenly across date range
        for game in games:
            if not (game.start_date or game.end_date):
                continue

            total_minutes = game.progress or 0
            if total_minutes <= 0:
                continue

            start_dt = game.start_date or game.end_date or game.created_at
            end_dt = game.end_date or game.start_date or game.created_at
            if not start_dt or not end_dt:
                continue

            start_local = _localize_datetime(start_dt).date()
            end_local = _localize_datetime(end_dt).date()
            if start_local > end_local:
                start_local, end_local = end_local, start_local

            day_count = (end_local - start_local).days + 1
            if day_count <= 0:
                day_count = 1

            base = total_minutes // day_count
            remainder = total_minutes % day_count
            date_range_display = f"{formats.date_format(start_local, 'M j')} - {formats.date_format(end_local, 'M j')}"
            total_progress_display = _format_game_hours(total_minutes)

            for offset in range(day_count):
                day = start_local + timedelta(days=offset)
                minutes_for_day = base + (1 if offset < remainder else 0)
                day_dt = timezone.make_aware(
                    datetime.combine(day, datetime.min.time()),
                    timezone.get_current_timezone(),
                )
                entries.append(
                    {
                        "media_type": MediaTypes.GAME.value,
                        "item": game.item,
                        "poster": game.item.image or settings.IMG_NONE,
                        "title": game.item.title,
                        "display_title": game.item.title,
                        "progress_display": total_progress_display,
                        "date_range_display": date_range_display,
                        "episode_label": None,
                        "episode_code": None,
                        "played_at_local": day_dt,
                        "runtime_minutes": minutes_for_day,
                        "runtime_display": helpers.minutes_to_hhmm(minutes_for_day) if minutes_for_day else None,
                    },
                )

    entries.sort(key=lambda entry: entry["played_at_local"], reverse=True)

    grouped_entries = defaultdict(list)
    for entry in entries:
        grouped_entries[entry["played_at_local"].date()].append(entry)

    history_days = []
    for _, day_entries in sorted(
        grouped_entries.items(),
        key=lambda item: item[0],
        reverse=True,
    ):
        day_entries.sort(key=lambda entry: entry["played_at_local"], reverse=True)
        first_entry_time = day_entries[0]["played_at_local"]
        total_minutes = sum(entry["runtime_minutes"] or 0 for entry in day_entries)

        history_days.append(
            {
                "date": first_entry_time.date(),
                "weekday": formats.date_format(first_entry_time, "l"),
                "date_display": formats.date_format(first_entry_time, "F j, Y"),
                "entries": day_entries,
                "total_minutes": total_minutes,
                "total_runtime_display": helpers.minutes_to_hhmm(total_minutes)
                if total_minutes
                else "0min",
            },
        )

    return history_days


def cache_history_days(user_id: int, logging_style: str, history_days):
    """Persist the grouped history in cache."""
    cache.set(
        _cache_key(user_id, logging_style),
        {
            "history_days": history_days,
            "built_at": timezone.now(),
        },
        timeout=HISTORY_CACHE_TIMEOUT,
    )


def get_history_days(user):
    """Return cached history, rebuilding if needed."""
    logging_style = getattr(user, "game_logging_style", "repeats")
    cache_entry = cache.get(_cache_key(user.id, logging_style))
    if cache_entry:
        built_at = cache_entry.get("built_at")
        if built_at and timezone.now() - built_at > HISTORY_STALE_AFTER:
            schedule_history_refresh(user.id, logging_style)
        return cache_entry.get("history_days", [])

    history_days = build_history_days(user)
    cache_history_days(user.id, logging_style, history_days)
    return history_days


def invalidate_history_cache(user_id: int):
    """Remove cached history for a user."""
    for style in ("sessions", "repeats", None):
        cache.delete(_cache_key(user_id, style or "repeats"))


def refresh_history_cache(user_id: int):
    """Rebuild and store history for a user."""
    user_model = get_user_model()
    try:
        user = user_model.objects.get(id=user_id)
    except user_model.DoesNotExist:
        return None

    history_days = build_history_days(user)
    logging_style = getattr(user, "game_logging_style", "repeats")
    cache_history_days(user_id, logging_style, history_days)
    cache.delete(_refresh_lock_key(user_id, logging_style))
    return history_days


def schedule_history_refresh(user_id: int, logging_style: str = "repeats", debounce_seconds: int = 30):
    """Queue a background refresh for a user's history cache."""
    lock_key = _refresh_lock_key(user_id, logging_style)
    if debounce_seconds and not cache.add(lock_key, True, debounce_seconds):
        return False

    try:
        from app.tasks import refresh_history_cache_task

        refresh_history_cache_task.delay(user_id)
        return True
    except Exception as exc:  # pragma: no cover - Celery not available
        logger.debug(
            "Falling back to inline history cache rebuild for user %s: %s",
            user_id,
            exc,
        )
        refresh_history_cache(user_id)
        return False
