from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from events.tasks import reload_calendar


class ReloadCalendarTaskTests(TestCase):
    """Tests for the reload_calendar Celery task."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="taskuser",
            password="pass12345",
        )

    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.calendar.fetch_releases")
    def test_auto_pause_runs_for_global_refresh(self, mock_fetch, mock_auto_pause):
        mock_fetch.return_value = "ok"

        result = reload_calendar()

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=None, items_to_process=None)
        mock_auto_pause.assert_called_once_with()

    @patch("events.tasks.auto_pause.auto_pause_stale_items")
    @patch("events.tasks.calendar.fetch_releases")
    def test_auto_pause_skipped_for_single_user(self, mock_fetch, mock_auto_pause):
        mock_fetch.return_value = "ok"

        result = reload_calendar(user=self.user)

        self.assertEqual(result, "ok")
        mock_fetch.assert_called_once_with(user=self.user, items_to_process=None)
        mock_auto_pause.assert_not_called()

