from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from channels.db import database_sync_to_async

from agents.models import SubjectDevice


class CustomAuthMiddleWare:
    def __init__(self, app):
        self.app = app
        self.DEVICE_HEADER_TYPE_BYTES = {h.encode(HTTP_HEADER_ENCODING) for h in settings.DEVICE_HEADER_TYPES}
        self.device = SubjectDevice

    async def __call__(self, scope, receive, send):
        try:
            # Ensure header is present
            header_key = settings.DEVICE_HEADER_NAME_WS.encode('utf-8')
            if header_key not in scope['headers']:
                raise AuthenticationFailed(_("Authorization header is missing"), code="authorization_header_missing")

            # Retrieve and validate the header
            header = dict(scope['headers'])[header_key].decode('utf-8')
            api_key = await self.get_api_key(header=header)
            if not api_key:
                raise AuthenticationFailed(_("Invalid API key"), code="invalid_api_key")

            # Fetch the device using the API key
            device = await self.get_device(api_key=api_key)
            scope["device"] = device

        except AuthenticationFailed as e:
            # Handle the authentication failure
            await send({
                'type': 'websocket.close',
                'code': 4001,  # Custom close code for authentication failure
                'reason': str(e),
            })
            return

        return await self.app(scope, receive, send)

    async def get_api_key(self, header):
        parts = header.split()

        if len(parts) == 0:
            return None

        if parts[0].encode('utf-8') not in self.DEVICE_HEADER_TYPE_BYTES:
            return None

        if len(parts) != 2:
            raise AuthenticationFailed(
                _("Authorization header must contain two space-delimited values"),
                code="bad_authorization_header",
            )

        return parts[1]
    
    @database_sync_to_async
    def get_device(self, api_key):
        try:
            device = self.device.objects.get(api_key=api_key)
        except self.device.DoesNotExist:
            raise AuthenticationFailed(_("Device not found"), code="device_not_found")

        return device

