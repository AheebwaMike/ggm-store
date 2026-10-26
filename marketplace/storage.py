import os
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class CloudinaryMediaStorage(Storage):
    """
    Custom Django Storage class for Cloudinary.
    Replaces the unmaintained django-cloudinary-storage package
    (which does not support Django 5+/6+).
    """

    def __init__(self, **kwargs):
        credentials = (
            os.getenv('CLOUDINARY_CLOUD_NAME'),
            os.getenv('CLOUDINARY_API_KEY'),
            os.getenv('CLOUDINARY_API_SECRET'),
        )
        self._fallback_storage = (
            FileSystemStorage(**kwargs) if not all(credentials) else None
        )

        if self._fallback_storage is None:
            cloudinary.config(
                cloud_name=credentials[0],
                api_key=credentials[1],
                api_secret=credentials[2],
                secure=True,
            )

    def _save(self, name, content):
        if self._fallback_storage is not None:
            return self._fallback_storage._save(name, content)

        folder = 'ggm-store'
        result = cloudinary.uploader.upload(
            content,
            folder=folder,
            resource_type='image',
            use_filename=True,
            unique_filename=True,
            overwrite=False,
        )
        return f"{result['resource_type']}:{result['public_id']}"

    def _open(self, name, mode='rb'):
        if self._fallback_storage is not None:
            return self._fallback_storage._open(name, mode)
        raise NotImplementedError("Opening files is not supported by Cloudinary storage.")

    def exists(self, name):
        if self._fallback_storage is not None:
            return self._fallback_storage.exists(name)
        return bool(name and ':' in name)

    def url(self, name):
        if self._fallback_storage is not None:
            return self._fallback_storage.url(name)
        if not name or ':' not in name:
            return ''
        resource_type, public_id = name.split(':', 1)
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type=resource_type,
            secure=True,
        )
        return url

    def delete(self, name):
        if self._fallback_storage is not None:
            return self._fallback_storage.delete(name)
        if not name or ':' not in name:
            return
        resource_type, public_id = name.split(':', 1)
        cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=True,
        )

    def size(self, name):
        if self._fallback_storage is not None:
            return self._fallback_storage.size(name)
        return 0

    def get_available_name(self, name, max_length=None):
        if self._fallback_storage is not None:
            return self._fallback_storage.get_available_name(name, max_length)
        ext = os.path.splitext(name)[1] or '.jpg'
        return f"{uuid.uuid4().hex}{ext}"

    def deconstruct(self):
        return ('marketplace.storage.CloudinaryMediaStorage', [], {})
