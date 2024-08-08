import redis
import os


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resc.settings')


class Redis() :
    """
    ** Future neccessary update :
    settings file needs to become a module containing developement and production files
    based on the mode, whether developement or production, the configs of self.db in this class should change
    """
    def __init__(self) :
        self.db = redis.Redis(host='localhost', port=6379, db=1)

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