import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.cache import cache

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

base_url = "https://www.googleapis.com/books/v1/volumes"
search_url = "https://openlibrary.org/search.json"


def handle_error(error):
    """Handle Google Books API errors."""
    raise services.ProviderAPIError(
        Sources.GOOGLEBOOKS.value,
        error,
    )


def search(query, page):
    """Search for books on Open Library."""
    cache_key = (
        f"search_{Sources.GOOGLEBOOKS.value}_{MediaTypes.BOOK.value}_{query}_{page}"
    )
    data = cache.get(cache_key)

    if data is None:
        params = {
            "q": f"intitle:{query}",
            "maxResults": settings.PER_PAGE,
            "printType": "books",
            "startIndex": page
        }

        try:
            response = services.api_request(
                Sources.GOOGLEBOOKS.value,
                "GET",
                base_url,
                params=params,
            )
        except requests.RequestException as e:
            handle_error(e)

        results = [
            {
                "media_id": media_id,
                "source": Sources.GOOGLEBOOKS.value,
                "media_type": MediaTypes.BOOK.value,
                "title": doc["volumeInfo"]["title"],
                "image": get_image_url(doc["volumeInfo"]),
            }
            for doc in response.get("items", [])
            if (media_id := get_media_id(doc)) and "volumeInfo" in doc and "title" in doc["volumeInfo"]
        ]

        total_results = response["totalItems"]
        data = helpers.format_search_response(
            page,
            settings.PER_PAGE,
            total_results,
            results,
        )

        cache.set(cache_key, data)
    return data


def extract_googlebooks_id(path):
    """
    Extract the ID from an Google Books media.

    Args:
        path (str): A path like '/works/OL123W' or a full URL

    Returns:
        str: The extracted ID (e.g., 'OL123W')
    """
    if not path:
        return None

    # Handle both full URLs and path fragments
    return path.rstrip("/").split("/")[-1]


def get_media_id(doc):
    """Get media ID from document with fallback logic."""
    if "id" in doc:
        return doc["id"]


def book(media_id):
    """Get metadata for a book from Open Library."""
    return asyncio.run(async_book(media_id))


async def async_book(media_id):
    """Asynchronous implementation of book metadata retrieval."""
    cache_key = f"{Sources.GOOGLEBOOKS.value}_{MediaTypes.BOOK.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        book_url = f"{base_url}/{media_id}"

        try:
            response_book = services.api_request(
                Sources.GOOGLEBOOKS.value,
                "GET",
                book_url,
            )
        except requests.RequestException as e:
            handle_error(e)

        responseBook = response_book.get("volumeInfo", [])

        data = {
            "media_id": media_id,
            "source": Sources.GOOGLEBOOKS.value,
            "source_url": response_book.get("selfLink"),
            "media_type": MediaTypes.BOOK.value,
            "title": responseBook["title"],
            "max_progress": responseBook.get("pageCount"),
            "image": get_cover_image_url(responseBook),
            "synopsis": get_description(responseBook, response_book),
            "genres": get_subjects(responseBook),
            "score": 0,
            "score_count": 0,
            "details": {
                "physical_format": responseBook.get("printType"),
                "number_of_pages": responseBook.get("pageCount"),
                "publish_date": get_publish_date(responseBook),
                "author": responseBook.get("authors"),
                "publishers": get_publishers(responseBook),
                "isbn": get_isbns(responseBook),
            },
        }

        cache.set(cache_key, data)

    return data


def get_image_url(doc):
    """Get the cover image URL for a book."""
    # when no picture, cover_i is not present in the response
    # e.g book: OL31949778W
    covers = doc.get("imageLinks",[])
    if covers:
        if "medium" in covers:
            return covers["medium"]
        elif "thumbnail" in covers:
            return covers["thumbnail"]
        elif "smallThumbnail" in covers:
            return covers["smallThumbnail"]
    return settings.IMG_NONE


def get_cover_image_url(response):
    """Get the cover image URL from a work response."""
    covers = response.get("imageLinks", [])
    if covers:
        return covers["thumbnail"]
    return settings.IMG_NONE


def get_description(response_book, response_work):
    """Extract and clean up the book description."""
    if "description" in response_book:
        description = response_book["description"]
    elif "description" in response_work:
        description = response_work["description"]
    else:
        description = "No synopsis available."

    # sometimes the description is a dict
    # like {'type': '/type/text', 'value': '...'}
    if isinstance(description, dict):
        description = description["value"]

    if description != "No synopsis available.":
        soup = BeautifulSoup(description, "html.parser")
        text = soup.get_text(separator=" ")
        description = " ".join(text.split())

    return description


def get_physical_format(response):
    """Get the physical format of the book."""
    format_value = response.get("dimessions")
    if format_value:
        return format_value.title()
    return None


def get_publish_date(response):
    """Get the first publication date."""
    if "publish_date" in response:
        publish_date = response["publish_date"].removeprefix("cop. ")

        date_formats = [
            "%B %d, %Y",  # January 19, 2001
            "%d %B %Y",  # 18 March 2025
        ]
        for date_format in date_formats:
            try:
                parsed_date = datetime.strptime(publish_date, date_format).replace(
                    tzinfo=ZoneInfo("UTC"),
                )
                return parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # If no format matches, return the original string
        return publish_date
    return None


def get_subjects(response):
    """Get list of subjects/genres."""
    if "categories" in response:
        return response["categories"][:5]
    return None


def get_publishers(response):
    """Get list of publishers."""
    if "publisherr" in response:
        return response.get("publisher", [])[:5]
    return None


def get_isbns(response):
    """Get list of ISBNs."""
    if "industryIdentifiers" in response:
        industry = response.get("industryIdentifiers")
        for isbn in industry:
            if isbn["type"] == "ISBN_13":
                isbn_13 = isbn["identifier"]
            if isbn["type"] == "ISBN_10":
                isbn_10 = isbn["identifier"]
        
        isbns = isbn_13 + isbn_10
        
    if isbns:
        return isbns
    return None


async def get_editions(response_book, response_work):
    """Get list of editions asynchronously."""
    book_id = extract_openlibrary_id(response_book.get("key", ""))
    work_id = extract_openlibrary_id(response_work.get("key", ""))

    if not work_id:
        work_id = book_id

    # limit to 500 editions, pagination is not supported
    url = f"https://openlibrary.org/works/{work_id}/editions.json?limit=500"

    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == requests.codes.ok:
            data = await response.json()
            return [
                {
                    "source": Sources.GOOGLEBOOKS.value,
                    "source_url": f"https://openlibrary.org/books/{extract_openlibrary_id(edition['key'])}",
                    "media_id": extract_openlibrary_id(edition["key"]),
                    "media_type": MediaTypes.BOOK.value,
                    "title": edition.get("title"),
                    "image": get_cover_image_url(edition),
                }
                for edition in data["entries"]
                if extract_openlibrary_id(edition["key"]) != book_id
                and edition.get("title")
            ]
    return []


async def get_ratings(response_work):
    """Get ratings data for a book asynchronously."""
    work_id = extract_openlibrary_id(response_work.get("key", ""))

    if not work_id:
        return None, None

    url = f"https://openlibrary.org/works/{work_id}/ratings.json"

    async with aiohttp.ClientSession() as session, session.get(url) as response:
        if response.status == requests.codes.ok:
            data = await response.json()
            summary = data.get("summary", {})
            average = summary.get("average")
            count = summary.get("count")

            if average and count:
                # Convert to 10-point scale (multiply by 2) and round to 1 decimal place
                score = round(summary["average"] * 2, 1)
                score_count = summary["count"]
                return score, score_count

    return None, None
