from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.conf import settings

from agents import utils
from agents.utils import CustomJSONField

User = get_user_model()


class BaseModel(models.Model) :

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta :
        abstract = True


class Point(BaseModel) :
    name = models.CharField(verbose_name=_('name'), max_length=100)
    location = models.PointField(verbose_name=_('location'), srid=4326)

    class Meta :
        verbose_name = _('Point')
        verbose_name_plural = _('Points')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Region(BaseModel):
    name = models.CharField(verbose_name=_('name'), max_length=100)
    description = models.CharField(verbose_name=_('description'), max_length=500)
    polygon = models.PolygonField(verbose_name=_('polygon'), srid=4326)

    class Meta:
        verbose_name = _('Region')
        verbose_name_plural = _('Regions')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Agent(BaseModel):
    name = models.CharField(max_length=100, verbose_name=_("name"))
    emergency_center = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agents")
    busy = models.BooleanField(default=False, verbose_name=_("Agent is busy"))


    class Meta:
        verbose_name = _('Agent')
        verbose_name_plural = _('Agents')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Device(BaseModel) :
    api_key = models.CharField(
                    max_length=100, default=utils.generate_api_key, 
                    blank=True, verbose_name=_('API Key')
                    )
    name = models.CharField(
                    max_length=100,
                    verbose_name=_('Device name')
                    )

    class Meta :
        abstract = True


class SubjectDevice(Device) :
    subject = models.ForeignKey(
                    User, on_delete=models.CASCADE, blank=True, null=True,
                    related_name='devices', verbose_name=_('Subject')
                    )

    class Meta :
        unique_together = ('subject', 'name', )
        verbose_name = _('Subject device')
        verbose_name_plural = _('Subject devices')
        ordering = ('created',)

    def __str__(self):
        return f'Subject device: {self.name}'


class AgentDevice(Device) :
    agent = models.ForeignKey(
                    Agent, on_delete=models.CASCADE,
                    related_name='devices', verbose_name=_('Agent')
                    )

    class Meta :
        unique_together = ('agent', 'name', )
        verbose_name = _('Agent device')
        verbose_name_plural = _('Agent devices')
        ordering = ('created',)

    def __str__(self):
        return f'Agent device: {self.name}'


class SubjectRecords(BaseModel) :
    device = models.ForeignKey(
                    SubjectDevice, on_delete=models.CASCADE,
                    related_name='records', verbose_name=_('Device')
                    )

    data = CustomJSONField(required_keys=settings.SUBJECT_REQUIRED_KEYS, default=list)

    class Meta :
        verbose_name = _('Subject Record')
        verbose_name_plural = _('Subject Records')
        ordering = ('created',)

    def __str__(self):
        return f'Subject record with device {self.device.name}'


class AgentRecords(BaseModel) :
    device = models.ForeignKey(
                    AgentDevice, on_delete=models.CASCADE,
                    related_name='records', verbose_name=_('Device')
                    )

    data = CustomJSONField(required_keys=settings.AGENT_REQUIRED_KEYS, default=list)

    class Meta :
        verbose_name = _('Agent Record')
        verbose_name_plural = _('Agent Records')
        ordering = ('created',)

    def __str__(self):
        return f'Agent record with device {self.device.name}'


class Mission(BaseModel):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="missions")
    subject = models.ForeignKey(User, on_delete=models.PROTECT, related_name="missions", verbose_name=_("Alive subject"))
    status = models.PositiveSmallIntegerField(
                            choices=utils.MissionStatus.choices, default=utils.MissionStatus.JUST_DEFINED,
                            verbose_name=_('Status')
                            )
    archived = models.BooleanField(default=False, verbose_name=_("Mission is archived"))

    class Meta:
        verbose_name = _('Mission')
        verbose_name_plural = _('Missions')
        ordering = ('created',)

    def __str__(self):
        return f'Mission by agent {self.agent.name}'


