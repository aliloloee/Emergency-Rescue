from django.urls import path
from agents import consumers



websocket_urlpatterns = [
    path('ws/subject/send/', consumers.AliveSubjectConsumer.as_asgi(), name='ws-subject-data'),
    path('ws/agent/send/', consumers.AgentConsumer.as_asgi(), name='ws-agent-data'),
    path('ws/center/recieve/', consumers.EmergencyReceiveConsumer.as_asgi(), name='ws-center-data'),
]