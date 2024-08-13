from resc.settings.base import *
import os


DEBUG = True

ALLOWED_HOSTS = ['*']

# A crucial step for working with postgis data on windows
# GDAL Configuration and Installation on Windows for Django Projects
# https://medium.com/@limeira.felipe94/gdal-configuration-and-installation-on-windows-for-django-projects-538171db5ccc

GDAL_LIBRARY_PATH = r"C:\Users\Ali\Desktop\Emergency Rescue\venv\Lib\site-packages\osgeo\gdal304.dll"
GEOS_LIBRARY_PATH = r"C:\Users\Ali\Desktop\Emergency Rescue\venv\Lib\site-packages\osgeo\geos_c.dll"

# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': 'rescue',
        'USER': 'postgres', 
        'PASSWORD': 'ali90055',
        'HOST': '127.0.0.1', 
        'PORT': '5432',
    }
}

# CACHE
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient"
        },
        "KEY_PREFIX": "caching"
    }
}


# CELERY CONFIG
CELERY_BROKER_URL = f'redis://127.0.0.1:6379/0'
CELERY_RESULT_BACKEND = f'redis://127.0.0.1:6379/0'

CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json', ]
CELERY_RESULT_EXPIRES = timedelta(days=1)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = False
CELERY_WORKER_PREFETCH_MULTIPLIER = 4

# CHANNELS LAYER
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": ["redis://127.0.0.1:6379/2"],
        },
    },
}

