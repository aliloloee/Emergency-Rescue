from pathlib import Path
from decouple import config 
from datetime import timedelta
from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'


SECRET_KEY = config('SECRET_KEY')


# Application definition
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',

    # third-party
    'rest_framework',
    'leaflet',

    # local apps
    'accounts',
    'profiles',
    'agents',

    # swagger
    'drf_yasg',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'resc.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATE_DIR, ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


AUTH_USER_MODEL = 'accounts.User'

# WSGI_APPLICATION = 'resc.wsgi.application'
ASGI_APPLICATION = 'resc.asgi.application'


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_URL = '/static/'
STATICFILES_DIRS = [STATIC_DIR, ]

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Http authentication
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/agent/dashboard/'  # or any other URL you want to redirect after login
LOGOUT_REDIRECT_URL = '/'  # or any other URL you want to redirect after logout


# REST FRAMEWORK SETTINGS
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

# SWAGGER SETTINGS
SWAGGER_SETTINGS = {
    "DEFAULT_MODEL_RENDERING": "example",
    'SECURITY_DEFINITIONS': {
        'Bearer': {
                'type': 'apiKey',
                'name': 'Authorization',
                'in': 'header'
        }
    }
}

# JWT CONFIGURATION
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=10),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),

    'SIGNING_KEY': SECRET_KEY,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'JTI_CLAIM': 'jti',

    ## For customizing the login process for User with type of Emergency-center 
    "ACCESS_TOKEN_NAME": "access_token",
    "REFRESH_TOKEN_NAME": "refresh_token",
    "JWT_COOKIE_SAMESITE": "Lax",
}


############# APP Settings #############

## LOCAL APP CONFIGS (STATIC VARIABLES, CONSTANTS, ....)

# TYPE OF PROFILE
NORMAL           = 1, _('NORMAL')
EMERGENCY_CENTER = 2, _('EMERGENCY_CENTER')
SUPER            = 3, _('SUPER')

# STATUS OF MISSIONS
JUST_DEFINED  = 1, _('JUST_DEFINED')
IN_PROGRESS   = 2, _('IN_PROGRESS')
SUCCESS       = 3, _('SUCCESS')
FAILURE       = 4, _('FAILURE')

# SETTING FOR CREATING API_KEY OF THE DEVICE
DEVICE_API_KEY_SETTINGS = {
    'MESSAGE_LOWER_BAND': 20,
    'MESSAGE_UPPER_BAND': 30,
    'HASHING_METHOD': 'default',   # 'default' to use django make_password for hashing
    # 'HASHING_METHOD': 'sha3_256' # 'sha3_256' to use this algorithm for hashing 
}

# REQUIRED KEYS FOR AGENTS AND SUBJECT TO BE RECORDED
SUBJECT_REQUIRED_KEYS = {"lat", "lng", "heartrate", "timestamp"}
AGENT_REQUIRED_KEYS = {"lat", "lng", "timestamp"}


# WEBSOCKETS CONFIGS
DEVICE_HEADER_NAME_WS = 'device'
# JWT_HEADER_NAME_WS = 'user'
HEADER_TYPES = ('Resc', )


# Django Channels Routigs Config
CHANNELS_ROUTING_NAME = 'routings'
CHANNELS_URL_PATTERN = 'websocket_urlpatterns'


# WHICH MODEL TO USE FOR TRANSFERING DATA FROM REDIS IN CONSUMERS
SUBJECT_MODEL = 0, _('SUBJECT')
AGENT_MODEL = 1, _('AGENT')