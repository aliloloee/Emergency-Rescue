from celery import Celery
import os

from decouple import config 


os.environ.setdefault('DJANGO_SETTINGS_MODULE', config('DJANGO_SETTINGS_MODULE'))
app = Celery('resc')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
