from django.urls import path
from agents import views

app_name = 'agents'


urlpatterns = [
    path('main/', views.main, name='main'),
]