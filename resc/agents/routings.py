from django.urls import path
from agents import consumers



websocket_urlpatterns = [
    path('ws/subject/send/', consumers.AliveSubjectConsumer.as_asgi(), name='subject-data')
]