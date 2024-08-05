from django.urls import path
from agents import views

app_name = 'agents'


urlpatterns = [
    path('dashboard/', views.MainBoard.as_view(), name='main'),
]
