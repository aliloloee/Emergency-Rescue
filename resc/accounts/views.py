from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.conf import settings
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from accounts import serializers
from accounts.permissions import AnyOnPost_AuthOnGet


class CustomLoginView(LoginView):
    template_name = 'login.html'
    success_url = reverse_lazy('agents:main')

    def make_tokens(self, user) :
        refresh = RefreshToken.for_user(user)
        
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        data = self.make_tokens(user=user)

        response.set_cookie(
                settings.SIMPLE_JWT["REFRESH_TOKEN_NAME"],
                data["refresh"],
                max_age=settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"],
                httponly=True,
                samesite=settings.SIMPLE_JWT["JWT_COOKIE_SAMESITE"],
            )
        
        response.set_cookie(
                settings.SIMPLE_JWT["ACCESS_TOKEN_NAME"],
                data["access"],
                max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"],
                httponly=True,
                samesite=settings.SIMPLE_JWT["JWT_COOKIE_SAMESITE"],
            )

        return response


class RegisterAPIView(generics.CreateAPIView) :

    serializer_class = serializers.RegisterUserSerializer
    permission_classes = (AnyOnPost_AuthOnGet, )

    # @swagger_auto_schema(**schemas['RegisterAPISchema'], manual_parameters=[otp])
    def post(self, request) :
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid() :
            user = serializer.save()

            # Activate user while registration for simplicity
            user.is_active = True
            user.save()

            return Response(
                serializer.data,
                status = status.HTTP_201_CREATED
            )
        else :
            return Response(
                serializer.errors,
                status = status.HTTP_400_BAD_REQUEST,
            )

    # @swagger_auto_schema(**schemas['UserAPIViewSchema'])
    def get(self, request):
        user = request.user
        serializer = self.serializer_class(user)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
            )


class CustomTokenObtainPairView(TokenObtainPairView):

    # @swagger_auto_schema(**schemas['CustomTokenObtainPairSchema'])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(TokenRefreshView):
    
    # @swagger_auto_schema(**schemas['CustomTokenRefreshViewSchema'])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)