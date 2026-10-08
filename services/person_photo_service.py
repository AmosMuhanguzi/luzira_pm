import base64
import binascii
import logging
from pathlib import Path
from uuid import uuid4

from flask import current_app


logger = logging.getLogger(__name__)
MAX_PHOTO_BYTES = 5 * 1024 * 1024
JPEG_DATA_PREFIX = 'data:image/jpeg;base64,'


class PersonPhotoService:
    @staticmethod
    def save_capture(data_url):
        if not data_url:
            return None, None
        if not isinstance(data_url, str) or not data_url.startswith(JPEG_DATA_PREFIX):
            return None, 'Captured photo must be a JPEG image.'

        encoded_image = data_url[len(JPEG_DATA_PREFIX):]
        max_encoded_length = ((MAX_PHOTO_BYTES + 2) // 3) * 4
        if len(encoded_image) > max_encoded_length:
            return None, 'Photo is too large. Please retake it.'

        try:
            image_data = base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError):
            return None, 'Captured photo could not be read. Please retake it.'

        if len(image_data) > MAX_PHOTO_BYTES:
            return None, 'Photo is too large. Please retake it.'
        if not image_data.startswith(b'\xff\xd8\xff'):
            return None, 'Captured photo is not a valid JPEG image.'

        filename = f'{uuid4().hex}.jpg'
        photo_dir = Path(current_app.instance_path) / 'person_photos'
        try:
            photo_dir.mkdir(parents=True, exist_ok=True)
            (photo_dir / filename).write_bytes(image_data)
        except OSError:
            logger.exception('Unable to save captured person photo.')
            return None, 'Photo could not be saved. Please try again.'

        return filename, None

    @staticmethod
    def delete_photo(filename):
        if not filename:
            return

        photo_path = Path(current_app.instance_path) / 'person_photos' / filename
        try:
            photo_path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Unable to remove an unassociated person photo.')
