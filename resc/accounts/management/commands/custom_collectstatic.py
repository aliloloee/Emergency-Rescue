from django.core.management.base import BaseCommand
from django.contrib.staticfiles.management.commands.collectstatic import Command as CollectStaticCommand
import os

from decouple import config 


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resc.settings.developement')


class Command(CollectStaticCommand):
    help = 'Custom collectstatic command'

    def handle(self, *args, **options):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resc.settings.developement')
        # Call the original collectstatic command logic
        super().handle(*args, **options)
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', config('DJANGO_SETTINGS_MODULE'))