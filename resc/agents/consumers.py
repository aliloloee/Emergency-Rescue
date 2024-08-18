from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils.translation import gettext_lazy as _

from resc.redis_conf import RSCREDIS
from agents.models import SubjectRecords
from agents.tasks import export_from_redis_to_db

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
        self.region_group_name = f'region-{self.region.pk}'

        await self.channel_layer.group_add(
            self.publish_group_name,
            self.channel_name
        )

        await self.accept()

    async def receive(self, text_data=None):
        """
        The data includes the region which belongs to the corresponding user's profile
        ** for future updates, it is better to get lattitude and longitude, check which region they belong to
        ** and send data to the related 'region_group_name' according to the region
        """
        if text_data :
            data = json.loads(text_data)
            device_data = {
                'lat': data["lat"],
                'lng': data["lng"],
                'heartrate': data["heartrate"],
                'timestamp': data["timestamp"],
            }

            await self.channel_layer.group_send(
                self.publish_group_name,
                {
                    'type': 'processing',
                    'value': {**device_data}
                }
            )

            device_data['region'] = f'region-{self.region.pk}'
            await self.channel_layer.group_send(
                self.region_group_name,
                {
                    'type': 'echo',
                    'value': {**device_data}
                }
            )

    async def processing(self, event) :
        data = event['value']
        await self.add_to_db(data)

    async def disconnect(self, close_code=None):
        await self.channel_layer.group_discard(self.publish_group_name, self.channel_name)

    def create_record(self) :
        kw = {
            'device':self.device,
            'data':[]
        }
        return self.model.objects.create(**kw)

    async def add_to_db(self, value) :
        value_str = json.dumps(value)
        self.redis.rpush(self.queue_name, value_str)
        len = self.redis.llen(self.queue_name)
        if len == self.queue_size :
            prime_queue = f'{self.queue_name}-prime:{self.counter}'

            self.redis.rename(self.queue_name, prime_queue)
            export_from_redis_to_db.apply_async(kwargs={
                                'record_id': str(self.record.pk),
                                'queue_name': prime_queue,
                                'queue_size': self.queue_size,
                                })
            self.counter = self.counter + 1

            RSCREDIS.delete_key(self.queue_name)
