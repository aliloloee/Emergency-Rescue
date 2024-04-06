from django.urls import path
from accounts import views


app_name = 'accounts'

urlpatterns = [
    path('api/login/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/login/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
]

