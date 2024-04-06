from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from accounts import serializers
from accounts.permissions import AnyOnPost_AuthOnGet



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