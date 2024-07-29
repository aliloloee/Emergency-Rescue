from django.urls import path
from agents import views

app_name = 'agents'


urlpatterns = [
    path('main/', views.MainBoard.as_view(), name='main'),
    path('api/life/', views.LifeAPIView.as_view(), name='api-life'),
]
