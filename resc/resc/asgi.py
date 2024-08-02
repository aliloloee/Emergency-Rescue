import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from agents import routings as agents_routings



os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resc.settings')

django_asgi_app = get_asgi_application()
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                agents_routings.websocket_urlpatterns
            )
        )
    ),
})
