from django.urls import path
from accounts import views
# from django.contrib.auth import views as auth_views


app_name = 'accounts'

urlpatterns = [
    path('login/', views.CustomLoginView.as_view(), name='login'),
    # path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('api/user/', views.RegisterAPIView.as_view(), name='api-user'),
    path('api/login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/login/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
    path("api/token/refresh/", views.CustomBrowserRefreshToken.as_view(), name="browser_token_refresh"),
]