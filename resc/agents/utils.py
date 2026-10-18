from django.db import models
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError

from secrets import choice, randbelow
from string import ascii_uppercase
import hashlib
import json


class MissionStatus (models.IntegerChoices) :
    """
    Where a mission is in its lifecycle. What actually happened is MissionOutcome:
    the agent reports an outcome (REPORTED), then the center closes the mission
    (CLOSED) and may override that report.
    """
    JUST_DEFINED   = settings.JUST_DEFINED
    IN_PROGRESS    = settings.IN_PROGRESS
    REPORTED       = settings.REPORTED
    CLOSED         = settings.CLOSED

    @classmethod
    def all_types(cls):
        return {
            cls.JUST_DEFINED.value : cls.JUST_DEFINED.label,
            cls.IN_PROGRESS.value : cls.IN_PROGRESS.label,
            cls.REPORTED.value : cls.REPORTED.label,
            cls.CLOSED.value : cls.CLOSED.label
        }

    @classmethod
    def open_statuses(cls):
        """
        Statuses in which a mission still holds its agent. Used by the constraint
        that stops one agent being assigned to two missions at once, so changing
        this changes the database constraint - it needs a migration.
        """
        return (cls.JUST_DEFINED, cls.IN_PROGRESS, cls.REPORTED)


class MissionOutcome (models.IntegerChoices) :
    """What happened on a mission. Null until the agent reports."""
    SUCCESS = settings.SUCCESS
    FAILURE = settings.FAILURE

    @classmethod
    def all_types(cls):
        return {
            cls.SUCCESS.value : cls.SUCCESS.label,
            cls.FAILURE.value : cls.FAILURE.label
        }


class AlertStatus (models.IntegerChoices) :
    """
    Lifecycle of a distress alert - the "possible mission" raised when a subject
    device transmits. UNROUTED means no free agent was available in the region at
    the time; the next reading from the same device retries the routing.
    """
    UNROUTED  = settings.ALERT_UNROUTED
    ROUTED    = settings.ALERT_ROUTED
    CONVERTED = settings.ALERT_CONVERTED
    DISMISSED = settings.ALERT_DISMISSED

    @classmethod
    def all_types(cls):
        return {
            cls.UNROUTED.value : cls.UNROUTED.label,
            cls.ROUTED.value : cls.ROUTED.label,
            cls.CONVERTED.value : cls.CONVERTED.label,
            cls.DISMISSED.value : cls.DISMISSED.label
        }

    @classmethod
    def open_statuses(cls):
        """
        Statuses in which an alert is still awaiting a decision. Used by the
        constraint that enforces one open alert per subject device, which is what
        deduplicates the stream of readings coming from a device in distress.
        """
        return (cls.UNROUTED, cls.ROUTED)


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

    # def from_db_value(self, value, expression, connection):
    #     if value is None:
    #         return value
    #     return value
    #     # return json.loads(value)

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
        return value


class ModelType (models.IntegerChoices) :
    SUBJECT = settings.SUBJECT_MODEL
    AGENT   = settings.AGENT_MODEL

    @classmethod
    def all_types(cls):
        return {
            cls.SUBJECT.value : cls.SUBJECT.label,
            cls.AGENT.value : cls.AGENT.label,
        }