from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer



User = get_user_model()


class RegisterUserSerializer(serializers.ModelSerializer):

    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        ref_name = None
        model = User
        fields = ('email', 'firstname', 'lastname', 'password', 'confirm_password', )

        extra_kwargs = {
            'password': {
                'write_only' : True,
                'style' : {'input_type' : 'password'},
            },
            'confirm_password': {
                'write_only' : True,
                'style' : {'input_type' : 'password'},
            }
        }

    def validate(self, data) :
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError(_("Passwords do not match"))
        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        return User.objects.create_user(**validated_data)


class JWTCookieTokenRefreshSerializer(TokenRefreshSerializer) :
    refresh = None

    def validate(self, attrs):
        attrs["refresh"] = self.context["request"].COOKIES.get(settings.SIMPLE_JWT["REFRESH_TOKEN_NAME"])

        if attrs["refresh"]:
            return super().validate(attrs)
        else:
            raise InvalidToken("No valid refresh token found")