from django.core.management import call_command
from django.test import SimpleTestCase


class MigrationStateTests(SimpleTestCase):
    def test_model_changes_have_migrations(self):
        call_command('makemigrations', 'marketplace', check=True, dry_run=True, verbosity=0)
