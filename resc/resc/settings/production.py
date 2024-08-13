import sys
sys.path.append('/usr/src/app')

from resc.settings.base import *
from decouple import config 



DEBUG = config('DEBUG')

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
# 'db' --> docker-compose name of postgresql database
# 'ram' --> docker-compose name of redis

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': config('NAME'),
        'USER': config('USER'), 
        'PASSWORD': config('PASSWORD'),
        'HOST': 'db',
        'PORT': config('PORT'),
    }
}

# CACHE
redis_db = config('REDIS_HOST')
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{redis_db}:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient"
        },
        "KEY_PREFIX": "caching"
    }
}


# CELERY CONFIG
CELERY_BROKER_URL = f'redis://{redis_db}:6379/0'
CELERY_RESULT_BACKEND = f'redis://{redis_db}:6379/0'

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
            "hosts": [f"redis://{redis_db}:6379/2"],
        },
    },
}

