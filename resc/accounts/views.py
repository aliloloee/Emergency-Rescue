from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView



class CustomTokenObtainPairView(TokenObtainPairView):

    # @swagger_auto_schema(**schemas['CustomTokenObtainPairSchema'])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(TokenRefreshView):
    
    # @swagger_auto_schema(**schemas['CustomTokenRefreshViewSchema'])
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)