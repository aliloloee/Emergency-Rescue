from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils.translation import gettext_lazy as _

from resc.redis_conf import RSCREDIS
from agents.models import SubjectRecords

import json



class AliveSubjectConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = SubjectRecords
        self.redis = RSCREDIS.db
        self.queue_size = 100

    async def connect(self):
        self.device = self.scope["device"]
        self.region = self.scope["region"]

        # CREATE A RECORD
        self.record = await database_sync_to_async(self.create_record)()
        
        # GET REDIS DATABASE
        self.queue_name = f'queue:{self.device.pk}:{self.record.pk}' 
        self.counter = 0

        self.publish_group_name = f'publish-{self.device.pk}'

        await self.channel_layer.group_add(
            self.publish_group_name,
            self.channel_name
        )

        await self.accept()

    async def receive(self, text_data=None):
        if text_data :
            data = json.loads(text_data)
            device_data = {
                'lat': data["lat"],
                'lng': data["lng"],
                'heartrate': data["heartrate"],
                'timestamp': data["timestamp"]
            }

            await self.channel_layer.group_send(
                self.publish_group_name,
                {
                    'type': 'processing',
                    **device_data
                }
            )

    async def processing(self, event) :
        device_data = {
            'lat': float(event['lat']),
            'lng': float(event['lng']),
            'heartrate': int(event['heartrate']),
            'timestamp': str(event['timestamp'])
        }

    async def disconnect(self, close_code=None):
        await self.channel_layer.group_discard(self.publish_group_name, self.channel_name)

    def create_record(self) :
        kw = {
            'device':self.device,
            'data':[]
        }
        return self.model.objects.create(**kw)
