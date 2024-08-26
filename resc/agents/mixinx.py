from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from channels.db import database_sync_to_async

from agents.models import SubjectDevice

import jwt


User = get_user_model()

class JWTAuthMixin:
    HEADER_TYPE_BYTES = {h.encode(HTTP_HEADER_ENCODING) for h in settings.HEADER_TYPES}

    async def get_token(self, header):
        parts = header.split()

        if len(parts) == 0:
            return None

        if parts[0].encode('utf-8') not in self.HEADER_TYPE_BYTES:
            return None

        if len(parts) != 2:
            raise AuthenticationFailed(
                _("Authorization header must contain two space-delimited values"),
                code="bad_authorization_header",
            )

        return parts[1]
    
    @database_sync_to_async
    def get_user_from_token(self, token):
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except (jwt.ExpiredSignatureError, jwt.DecodeError, User.DoesNotExist):
            return None

    async def authenticate(self, scope):
        # Ensure header is present
        header_key = settings.JWT_HEADER_NAME_WS.encode('utf-8')
        header_exists = any(header[0] == header_key for header in scope['headers'])
        if not header_exists:
            raise AuthenticationFailed(_("Authorization header is missing"), code="authorization_header_missing")

        # Retrieve and validate the header
        header = dict(scope['headers'])[header_key].decode('utf-8')
        access_token = await self.get_token(header=header)
        if not access_token:
            raise AuthenticationFailed(_("Invalid Token"), code="invalid_token")
        
        # Fetch User
        print(access_token)
        user = await self.get_user_from_token(access_token[0])
        if user is None:
            await self.close()
        else:
            self.scope['user'] = user



class BaseAuthMixin:
    HEADER_TYPE_BYTES = {h.encode(HTTP_HEADER_ENCODING) for h in settings.HEADER_TYPES}
    device_model = SubjectDevice  # Define your device model here

    async def get_api_key(self, header):
        parts = header.split()

        if len(parts) == 0:
            return None

        if parts[0].encode('utf-8') not in self.HEADER_TYPE_BYTES:
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
            return self.device_model.objects.get(api_key=api_key)
        except self.device_model.DoesNotExist:
            raise AuthenticationFailed(_("Device not found"), code="device_not_found")

    @database_sync_to_async
    def get_region(self, device):
        return device.subject.profile.region

    async def authenticate(self, scope):
        # Ensure header is present
        header_key = settings.DEVICE_HEADER_NAME_WS.encode('utf-8')
        header_exists = any(header[0] == header_key for header in scope['headers'])
        if not header_exists:
            raise AuthenticationFailed(_("Authorization header is missing"), code="authorization_header_missing")

        # Retrieve and validate the header
        header = dict(scope['headers'])[header_key].decode('utf-8')
        api_key = await self.get_api_key(header=header)
        if not api_key:
            raise AuthenticationFailed(_("Invalid API key"), code="invalid_api_key")

        # Fetch the device and region using the API key
        device = await self.get_device(api_key=api_key)
        region = await self.get_region(device=device)

        # Add device and region to scope
        scope["device"] = device
        scope["region"] = region


class AliveSubjectAuthMixin(BaseAuthMixin):
    async def connect(self):
        try:
            await self.authenticate(self.scope)
        except AuthenticationFailed as e:
            await self.close(code=4001)
            return




# class AnotherConsumerAuthMixin(BaseAuthMixin):
#     async def connect(self):
#         try:
#             await self.authenticate(self.scope)
#         except AuthenticationFailed as e:
#             await self.close(code=4001)
#             return

#         # Add any additional authentication or setup logic specific to this consumer

#         await super().connect()

