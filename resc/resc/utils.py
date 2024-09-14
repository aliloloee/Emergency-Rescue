import importlib
from django.apps import apps
from django.conf import settings

def get_websocket_urlpatterns() :
    all_websocket_urlpatterns = []

    for app_config in apps.get_app_configs():
        if app_config.name.startswith("django.contrib") : # Exclude apps from django.contrib
            continue
        try:
            routing = importlib.import_module(f'{app_config.name}.{settings.CHANNELS_ROUTING_NAME}')
            if hasattr(routing, settings.CHANNELS_URL_PATTERN):
                all_websocket_urlpatterns += getattr(routing, settings.CHANNELS_URL_PATTERN)
        except ModuleNotFoundError:
            pass

    return all_websocket_urlpatterns

all_websocket_urlpatterns = get_websocket_urlpatterns()