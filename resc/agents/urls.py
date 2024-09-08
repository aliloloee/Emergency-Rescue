from django.urls import path
from agents import views

app_name = 'agents'


urlpatterns = [
    path('dashboard/', views.MainBoard.as_view(), name='main'),
    path('dashboard/config/', views.js_config, name='js-config'),
]
