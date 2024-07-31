from django.db import models
from django.conf import settings


class MissionStatus (models.IntegerChoices) :
    IN_PROGRESS    = settings.IN_PROGRESS
    SUCCESS        = settings.SUCCESS
    FAILURE        = settings.FAILURE

    @classmethod
    def all_types(cls):
        return {
            cls.IN_PROGRESS.value : cls.IN_PROGRESS.label,
            cls.SUCCESS.value : cls.SUCCESS.label,
            cls.FAILURE.value : cls.FAILURE.label
        }
