from django.db import models
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError

from secrets import choice, randbelow
from string import ascii_uppercase
import hashlib
import json


class MissionStatus (models.IntegerChoices) :
    JUST_DEFINED   = settings.JUST_DEFINED
    IN_PROGRESS    = settings.IN_PROGRESS
    SUCCESS        = settings.SUCCESS
    FAILURE        = settings.FAILURE

    @classmethod
    def all_types(cls):
        return {
            cls.JUST_DEFINED.value : cls.JUST_DEFINED.label,
            cls.IN_PROGRESS.value : cls.IN_PROGRESS.label,
            cls.SUCCESS.value : cls.SUCCESS.label,
            cls.FAILURE.value : cls.FAILURE.label
        }


def generate_api_key():
    DAKS = settings.DEVICE_API_KEY_SETTINGS
    n = randbelow(DAKS['MESSAGE_UPPER_BAND'] - DAKS['MESSAGE_LOWER_BAND']) + DAKS['MESSAGE_LOWER_BAND']
    message = (''.join(choice(ascii_uppercase) for _ in range(n))).encode()

    if DAKS['HASHING_METHOD'] == 'sha3_256':
        api_key = hashlib.sha3_256(message).hexdigest()
    else:  # default mode
        api_key = make_password(message.decode())

    return api_key


class CustomJSONField(models.JSONField):
    def __init__(self, required_keys={}, *args, **kwargs):
        self.required_keys = set(required_keys)
        super().__init__(*args, **kwargs)

    def validate_structure(self, value):
        if not isinstance(value, list):
            raise ValidationError('Data must be a list.')

        for item in value:
            if not isinstance(item, dict):
                raise ValidationError('Each item in data must be a dictionary.')
            
            if set(item.keys()) != self.required_keys:
                raise ValidationError(f'Each dictionary must contain exactly these keys: {self.required_keys}')
            for key in self.required_keys:
                if not isinstance(item[key], (int, float)):
                    raise ValidationError(f'The value for {key} must be a number.')

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return json.loads(value)

    def to_python(self, value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValidationError('Invalid JSON format.')
        self.validate_structure(value)
        return value

    def get_prep_value(self, value):
        self.validate_structure(value)
        return json.dumps(value)

