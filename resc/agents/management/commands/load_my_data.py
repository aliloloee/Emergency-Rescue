from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Load data from fixtures/data.json into the database'

    def handle(self, *args, **kwargs):
        self.stdout.write('Loading data from fixtures/data.json...')
        call_command('loaddata', 'fixtures/data.json')
        self.stdout.write(self.style.SUCCESS('Data loaded successfully'))