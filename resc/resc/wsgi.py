from django.core.wsgi import get_wsgi_application
import os

from decouple import config 


os.environ.setdefault('DJANGO_SETTINGS_MODULE', config('DJANGO_SETTINGS_MODULE'))
application = get_wsgi_application()
