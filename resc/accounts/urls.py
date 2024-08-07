from django.urls import path
from accounts import views
from django.contrib.auth import views as auth_views


app_name = 'accounts'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('api/user/', views.RegisterAPIView.as_view(), name='api-user'),
    path('api/login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/login/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
]

