from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.filter
def get_attr(obj, attr):
    """Get attribute from object dynamically."""
    return getattr(obj, attr, None)


SOURCES_CONFIG = {
    "kitsu": {
        "name": "Kitsu",
        "logo": static("img/kitsu-logo.png"),
    },
    "trakt": {
        "name": "Trakt",
        "logo": static("img/trakt-logo.svg"),
    },
    "myanimelist": {
        "name": "MyAnimeList",
        "logo": static("img/mal-logo.ico"),
    },
    "anilist": {
        "name": "AniList",
        "logo": static("img/anilist-logo.svg"),
    },
    "simkl": {
        "name": "SIMKL",
        "logo": static("img/simkl-logo.png"),
    },
    "yamtrack": {
        "name": "YamTrack",
        "logo": static("favicon/apple-touch-icon.png"),
    },
    "hltb": {
        "name": "HowLongToBeat",
        "logo": static("img/hltb-logo.png"),
    },
    "imdb": {
        "name": "IMDB",
        "logo": static("img/imdb-logo.png"),
    },
    "steam": {
        "name": "Steam",
        "logo": static("img/steam-logo.ico"),
    },
    "goodreads": {
        "name": "GoodReads",
        "logo": static("img/logo-goodreads.svg"),
    },
}


@register.simple_tag
def source_display(source_name):
    """Generate HTML display for a media source with logo and name."""
    info = SOURCES_CONFIG.get(source_name)
    if not info:
        return ""

    html = f"""
        <div class="flex items-center">
            <img alt="{info["name"]}" class="w-6 h-6 mr-2" src="{info["logo"]}">
            <h4 class="font-medium">{info["name"]}</h4>
        </div>
    """

    return format_html(html)


@register.filter
def date_format_display(format_value):
    """Display the human-readable name for date format values."""
    format_display_map = {
        "system_default": "System default (locale) — Aug 12, 2025 / 12 Aug 2025",
        "iso_8601": "ISO 8601 — 2025-08-12",
        "month_d_yyyy": "Month D, YYYY — Aug 12, 2025",
        "d_mon_yyyy": "D Mon YYYY — 12 Aug 2025",
        "m_d_yyyy": "M/D/YYYY — 08/12/2025",
        "d_m_yyyy": "D/M/YYYY — 12/08/2025",
        "dd_mm_yyyy": "DD.MM.YYYY — 12.08.2025",
    }
    return format_display_map.get(format_value, format_value)


@register.filter
def time_format_display(format_value):
    """Display the human-readable name for time format values."""
    format_display_map = {
        "system_default": "System default (locale) — 6:45 PM / 18:45",
        "h_mm_ampm": "12-hour (h:mm AM/PM) — 6:45 PM",
        "hh_mm_ampm": "12-hour, leading zero (hh:mm AM/PM) — 06:45 PM",
        "hh_mm": "24-hour (HH:mm) — 18:45",
        "hh_mm_ss": "24-hour with seconds (HH:mm:ss) — 18:45:00",
    }
    return format_display_map.get(format_value, format_value)
