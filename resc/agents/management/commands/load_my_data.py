import os
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Load data from fixtures/data.json into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            'filename', type=str, help='The name of the fixture file (e.g., data.json)'
        )
        parser.add_argument(
            '--exclude', nargs='*', type=str, help='Exclude specific models from loading'
        )

    def handle(self, *args, **kwargs):
        filename = kwargs.pop('filename')
        fixture_path = os.path.join(settings.BASE_DIR, 'fixtures', filename)

        if not os.path.exists(fixture_path):
            self.stdout.write(self.style.ERROR(f"Fixture file '{filename}' does not exist."))
            return

        self.stdout.write(f'Loading data from {fixture_path}...')
        call_command('loaddata', fixture_path, *args, **kwargs)
        self.stdout.write(self.style.SUCCESS('Data loaded successfully'))
