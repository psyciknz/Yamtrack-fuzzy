import logging
from collections import defaultdict
from csv import DictReader

from django.apps import apps
from django.conf import settings
from django.utils.dateparse import parse_datetime

import app
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations.imports import helpers
from integrations.imports.helpers import (MediaImportError,
                                          MediaImportUnexpectedError)

logger = logging.getLogger(__name__)


def importer(file, user, mode):
    """Import media from CSV file using the class-based importer."""
    csv_importer = BookImporter(file, user, mode)
    return csv_importer.import_data()


class BookImporter:
    """Class to handle importing user data from CSV files."""

    def __init__(self, file, user, mode):
        """Initialize the importer with file, user, and mode.

        Args:
            file: Uploaded CSV file object
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        # Track existing media for "new" mode
        self.existing_media = helpers.get_existing_media(user)

        # Track media IDs to delete in overwrite mode
        self.to_delete = defaultdict(lambda: defaultdict(set))

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized Book CSV importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all user data from the CSV file."""
        try:
            decoded_file = self.file.read().decode("utf-8").splitlines()
            #format 
            #isbn,providerid,provider,title,read_start,read_end
        except UnicodeDecodeError as e:
            msg = "Invalid file format. Please upload a CSV file."
            raise MediaImportError(msg) from e

        fieldnames = ['isbn','providerid','provider','title','read_start','read_end','sourcee','media_id','progress','status']
        reader = DictReader(decoded_file,fieldnames=fieldnames)

        for row in reader:
            try:
                self._process_row(row)
            except Exception as error:
                error_msg = f"Error processing entry: {row}"
                raise MediaImportUnexpectedError(error_msg) from error

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages

    def _process_row(self, row):
        """Process a single row from the CSV file."""
        media_type = MediaTypes.BOOK.value

        # Check if we should process this movie based on mode
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            media_type,
            row["provider"],
            row["providerid"],
            self.mode,
        ):
            return

        if row["title"] == "" or row["provider"]or row["providerid"] == "":
            self._handle_missing_metadata(
                row,
                media_type
            )

        item, _ = app.models.Item.objects.update_or_create(
            media_id=row["media_id"],
            source=row["source"][0],
            media_type=media_type,
            season_number=None,
            episode_number=None,
            defaults={
                "title": row["title"],
                "image": row["image"],
            },
        )

        model = apps.get_model(app_label="app", model_name=media_type)
        instance = model(item=item)
        if media_type != MediaTypes.EPISODE.value:  # episode has no user field
            instance.user = self.user

        row["item"] = item
        form = app.forms.get_form_class(media_type)(
            row,
            instance=instance,
        )

        if form.is_valid():
            progressed_at = row.get("progressed_at")
            if progressed_at:
                form.instance._history_date = parse_datetime(progressed_at)
            self.bulk_media[media_type].append(form.instance)
        else:
            error_msg = f"{row['title']} ({media_type}): {form.errors.as_json()}"
            self.warnings.append(error_msg)
            logger.error(error_msg)

    def _handle_missing_metadata(self, row, media_type):
        """Handle missing metadata by fetching from provider - 
        Format #isbn,providerid,provider,title,read_start,read_end """
        try:
            searchquery = row["isbn"] or row["title"]
            if row["provider"] != "":
                metadata = services.get_media_metadata(
                    media_type,
                    row["providerid"],
                    row["provider"],
                )
                row["title"] = metadata["title"]
                row["image"] = metadata["image"]
                row["media_id"] = row["providerid"],
                row["source"] = row["provider"],
            else:
                metadata = services.search(
                    media_type,
                    searchquery,
                    1,
                    Sources.HARDCOVER.value,
                )
                row["title"] = metadata["results"][0]["title"],
                row["source"] = Sources.HARDCOVER.value,
                row["media_id"] = metadata["results"][0]["media_id"],
                row["media_type"] = media_type,
                row["image"] = metadata["results"][0]["image"],
                row["status"] = Status.COMPLETED.value,
                row["progress"] = '0'
        except services.ProviderAPIError as e:
            self.warnings.append(
                f"Failed to fetch metadata for {row['media_id']}: {e!s}",
            )
            raise
