from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework.exceptions import PermissionDenied
from channels.db import database_sync_to_async

from agents.models import SubjectDevice, AgentDevice
from profiles.utils import ProfileType

from http.cookies import SimpleCookie

import jwt


class JWTAuthMixin:
    model = get_user_model()

    # Which profile types may open a JWT authenticated socket. This mirrors the
    # gate on the dashboard page itself (MainBoard.test_func), which allows only
    # emergency centers - note that SUPER is deliberately not included, so that
    # the socket and the page stay consistent. Override per consumer if needed.
    allowed_profile_types = (ProfileType.EMERGENCY_CENTER, )

    @staticmethod
    def get_access_token(scope):
        """
        Read the access token cookie. CookieMiddleware (part of AuthMiddlewareStack)
        has normally already parsed the header into scope['cookies']; fall back to
        parsing it ourselves so the consumer also works without that middleware.
        """
        cookies = scope.get('cookies')
        if cookies is None:
            raw = dict(scope.get('headers', ())).get(b'cookie', b'').decode()
            cookies = {key: morsel.value for key, morsel in SimpleCookie(raw).items()}

        return cookies.get(settings.SIMPLE_JWT['ACCESS_TOKEN_NAME'])

    @database_sync_to_async
    def get_region(self, access_token):
        """
        Resolve the region of the user owning the access token.

        A bad token raises AuthenticationFailed so the consumer can close with
        4001 and the browser knows to refresh its token and reconnect. Returning
        an anonymous placeholder instead would let the socket be accepted into a
        'region-None' group and fail silently.

        A valid token belonging to a user who is not allowed on this socket
        raises PermissionDenied instead, which closes with 4005. Refreshing the
        token cannot fix that, so it must not reuse 4001 - the browser would
        refresh and reconnect in an endless loop.
        """
        if not access_token:
            raise AuthenticationFailed(_('Access token cookie is missing'), code='access_token_missing')

        try:
            # Covers malformed tokens, bad signatures and - importantly - expired
            # ones: ExpiredSignatureError is not a subclass of DecodeError.
            payload = jwt.decode(access_token, settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.exceptions.PyJWTError:
            raise AuthenticationFailed(_('Access token is invalid or expired'), code='invalid_access_token')

        try:
            user = self.model.objects.select_related('profile__region').get(id=payload['user_id'])
        except (KeyError, self.model.DoesNotExist):
            raise AuthenticationFailed(_('Access token does not match a user'), code='user_not_found')

        # A user may legitimately have no profile yet, or a profile with no region.
        profile = getattr(user, 'profile', None)
        if profile is None:
            raise AuthenticationFailed(_('User has no profile'), code='profile_not_found')

        if profile.type not in self.allowed_profile_types:
            raise PermissionDenied(_('This account may not watch a region feed'), code='profile_type_not_allowed')

        if profile.region is None:
            raise AuthenticationFailed(_('User is not assigned to a region'), code='region_not_found')

        return profile.region

    async def authenticate(self, scope):
        scope['region'] = await self.get_region(self.get_access_token(scope))


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
        """
        Returns True when the scope was authenticated. Consumers must check the
        result and return early when it is False, otherwise they carry on and
        read scope keys that were never set.
        """
        try:
            await self.authenticate(self.scope)
        except AuthenticationFailed:
            await self.reject()
            return False

        return True

    async def reject(self, code=4001):
        """
        Accept before closing so the client actually receives the close code.

        Closing an unaccepted connection aborts the HTTP upgrade instead, which
        the client sees as a bare 403 with no code - and the browser needs the
        4001 to know it should refresh its token and reconnect.
        """
        await self.accept()
        await self.close(code=code)


class AgentAuthMixin(AliveSubjectAuthMixin):
    device_model = AgentDevice

    @database_sync_to_async
    def get_region(self, device):
        return device.agent.emergency_center.profile.region


class JWTConsumerAuthMixin(JWTAuthMixin):
    async def connect(self):
        """
        Returns True when the scope was authenticated and authorized - see
        AliveSubjectAuthMixin.
        """
        try:
            await self.authenticate(self.scope)
        except AuthenticationFailed:
            # A new token might work, so let the browser refresh and retry.
            await self.reject(code=4001)
            return False
        except PermissionDenied:
            # The token is fine, the account simply is not allowed here. Use a
            # code the browser does not retry on, or it loops forever.
            await self.reject(code=4005)
            return False

        return True

    async def reject(self, code=4001):
        """
        Accept before closing so the browser receives the close code and can act
        on it - see AliveSubjectAuthMixin.reject.
        """
        await self.accept()
        await self.close(code=code)

