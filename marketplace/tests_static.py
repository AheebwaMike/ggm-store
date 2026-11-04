"""Runs collectstatic the way Render does, so a broken static file fails here and not during a deploy.
Run with:  python manage.py test marketplace.tests_static"""
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class CollectStaticTests(SimpleTestCase):
    def test_collectstatic_works_with_manifest_storage(self):
        css_is_built = any(
            (Path(folder) / 'css' / 'tailwind.css').exists() for folder in settings.STATICFILES_DIRS
        )
        if not css_is_built:
            self.skipTest('static/css/tailwind.css is not built yet (run .\\scripts\\build-css.ps1 first)')

        with tempfile.TemporaryDirectory() as target:
            with override_settings(
                STATIC_ROOT=target,
                STORAGES={
                    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
                },
            ):
                # Raises CommandError when a CSS or JS file points at something that does not exist
                call_command('collectstatic', interactive=False, verbosity=0)