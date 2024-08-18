from celery import shared_task

from agents.models import SubjectRecords
from resc.redis_conf import RSCREDIS

import json


@shared_task
def export_from_redis_to_db(*args, **kwargs) :
    record_id  = kwargs.get('record_id', None)
    queue_name = kwargs.get('queue_name', None)
    queue_size = kwargs.get('queue_size', None)

    redis = RSCREDIS.db

    rec = SubjectRecords.objects.get(id=record_id)
    queue = redis.lrange(queue_name, -queue_size, queue_size)
    rec.data = rec.data + [json.loads(x) for x in queue] 
    rec.save()

    RSCREDIS.delete_key(queue_name)