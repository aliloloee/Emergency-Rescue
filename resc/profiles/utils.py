from django.db import models
from django.conf import settings


class ProfileType (models.IntegerChoices) :
    NORMAL           = settings.NORMAL
    EMERGENCY_CENTER = settings.EMERGENCY_CENTER
    SUPER            = settings.SUPER

    @classmethod
    def all_types(cls):
        return {
            cls.NORMAL.value : cls.NORMAL.label,
            cls.EMERGENCY_CENTER.value : cls.EMERGENCY_CENTER.label,
            cls.SUPER.value : cls.SUPER.label
        }

    @classmethod
    def allowed_types(cls):
        return {
            cls.NORMAL.value : cls.NORMAL.label,
            cls.EMERGENCY_CENTER.value : cls.EMERGENCY_CENTER.label
        }