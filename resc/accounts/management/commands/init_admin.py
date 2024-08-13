from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from decouple import config


class Command(BaseCommand):
    help = 'Create superuser from env file credentials'

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.count() == 0:

            email = config('DJANGO_SUPERUSER_EMAIL')
            firstname = config('DJANGO_SUPERUSER_FIRSTNAME')
            lastname = config('DJANGO_SUPERUSER_LASTNAME')
            password = config('DJANGO_SUPERUSER_PASSWORD')

            User.objects.create_superuser(email=email, firstname=firstname, lastname=lastname, password=password)
        else :
            self.stdout.write('Auth-User table not empty \n')