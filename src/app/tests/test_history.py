import datetime
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase

from app import history
from app.models import MediaTypes

User = get_user_model()


class HistoryTests(TestCase):
    """Simplified history tests to avoid constraint issues."""

    def setUp(self):
        """Set up minimal test data."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
        )

    def test_format_episode_title(self):
        """Test the _format_episode_title function without database dependencies."""
        # Test with episode title different from TV title
        title = history._format_episode_title(
            "Test TV Show",
            1,
            5,
            "Unique Episode Title",
        )
        self.assertEqual(title, "Test TV Show - S1E5: Unique Episode Title")

        # Test with episode title same as TV title
        title = history._format_episode_title("Test TV Show", 2, 3, "Test TV Show")
        self.assertEqual(title, "Test TV Show - S2E3")

        # Test with no episode title
        title = history._format_episode_title("Test TV Show", 3, 1, None)
        self.assertEqual(title, "Test TV Show - S3E1")

    def test_update_media_count_with_episodes(self):
        """Test _update_media_count when episodes are present."""
        # Create mock consumable items
        mock_items = []

        # Add episodes
        for i in range(3):  # noqa: B007
            episode = MagicMock()
            episode.consumable_type = "episode"
            mock_items.append(episode)

        # Add movies
        for i in range(2):  # noqa: B007
            movie = MagicMock()
            movie.consumable_type = "movie"
            mock_items.append(movie)

        original_count = {
            "total": 7,
            MediaTypes.TV.value: 1,
            MediaTypes.SEASON.value: 1,
            MediaTypes.MOVIE.value: 2,
            "other": 3,
        }

        updated_count = history._update_media_count(original_count, mock_items)

        # Should have episode count
        self.assertEqual(updated_count["episode"], 3)
        # Should preserve movie count
        self.assertEqual(updated_count[MediaTypes.MOVIE.value], 2)
        # Should remove TV and season counts
        self.assertNotIn(MediaTypes.TV.value, updated_count)
        self.assertNotIn(MediaTypes.SEASON.value, updated_count)

    def test_get_consumable_media_timeline_no_db(self):
        """Test timeline with mock objects to avoid database issues."""
        # Create mock consumable items
        mock_items = []

        # Item with end_date
        item1 = MagicMock()
        item1.end_date = datetime.datetime(2025, 1, 5, 15, 0, tzinfo=datetime.UTC)
        item1.start_date = None
        mock_items.append(item1)

        # Item with start_date only
        item2 = MagicMock()
        item2.end_date = None
        item2.start_date = datetime.datetime(2025, 1, 10, 10, 0, tzinfo=datetime.UTC)
        mock_items.append(item2)

        # Item with no dates
        item3 = MagicMock()
        item3.end_date = None
        item3.start_date = None
        mock_items.append(item3)

        timeline = history.get_consumable_media_timeline(mock_items)

        # Should have 2 dates
        self.assertEqual(len(timeline), 2)
        self.assertIn(datetime.date(2025, 1, 5), timeline)
        self.assertIn(datetime.date(2025, 1, 10), timeline)
