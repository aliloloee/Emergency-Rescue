import redis
import os

from decouple import config 


os.environ.setdefault('DJANGO_SETTINGS_MODULE', config('DJANGO_SETTINGS_MODULE'))


class Redis() :
    def __init__(self) :
        host = 'localhost' if os.environ.get('DJANGO_SETTINGS_MODULE') == 'resc.settings.developement' else config('REDIS_HOST')
        self.db = redis.Redis(host=host, port=6379, db=1)

    def check_key_value_validity(self, key, value) :
        try :
            db_value = self.db.get(str(key)).decode("utf-8")
        except :
            return False
        return value == db_value 

    def check_key_existance(self, key) :
        try :
            self.db.get(str(key)).decode("utf-8")
        except :
            return False
        return True

    def delete_key(self, key) :
        self.db.delete(str(key))


RSCREDIS = Redis()