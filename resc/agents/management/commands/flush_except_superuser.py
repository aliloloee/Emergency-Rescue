from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Flushes the database but preserves the superuser'

    def handle(self, *args, **kwargs):
        User = get_user_model()

        # Retrieve the superuser
        try:
            superuser = User.objects.filter(is_superuser=True).first()
            if superuser:
                superuser_data = {
                    'email': superuser.email,
                    'password': superuser.password,  # hashed password
                    'firstname': superuser.firstname,
                    'lastname': superuser.lastname,
                }
            else:
                self.stdout.write(self.style.ERROR('No superuser found.'))
                return
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR('No superuser found.'))
            return

        # Flush the database
        call_command('flush', '--no-input')

        # Recreate the superuser
        user = User.objects.create_superuser(
            email=superuser_data['email'],
            firstname=superuser_data['firstname'],
            lastname=superuser_data['lastname'],
            password=None  # No need to set a password again as it is already hashed
        )

        # Update superuser details
        user.password = superuser_data['password']
        user.save()

        self.stdout.write(self.style.SUCCESS('Database flushed but superuser preserved.'))
