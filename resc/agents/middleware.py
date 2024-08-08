import jwt
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser



class CustomAuthMiddleWare:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, recieve, send):
        header = dict(scope['headers'])[settings.DEVICE_HEADER_NAME_WS.encode('utf-8')].decode('utf-8')
        print(header)

        return await self.app(scope, recieve, send)