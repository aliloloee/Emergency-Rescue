from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

from agents import utils

User = get_user_model()


class Point(models.Model) :
    """
    Point
    """

    name = models.CharField(verbose_name=_('name'), max_length=100)
    location = models.PointField(verbose_name=_('location'), srid=4326)

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta :
        verbose_name = _('Point')
        verbose_name_plural = _('Points')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Region(models.Model):
    """
    Region
    """

    name = models.CharField(verbose_name=_('name'), max_length=100)
    description = models.CharField(verbose_name=_('description'), max_length=500)
    polygon = models.PolygonField(verbose_name=_('polygon'), srid=4326)

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta:
        verbose_name = _('Region')
        verbose_name_plural = _('Regions')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Agent(models.Model):
    """
    Agents
    """
    name = models.CharField(max_length=100, verbose_name=_("name"))
    emergency_center = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agents")
    busy = models.BooleanField(default=False, verbose_name=_("Agent is busy"))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta:
        verbose_name = _('Agent')
        verbose_name_plural = _('Agents')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Mission(models.Model):
    """
    Mission
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="missions")
    subject = models.ForeignKey(User, on_delete=models.PROTECT, related_name="missions", verbose_name=_("Alive subject"))
    status = models.PositiveSmallIntegerField(
                            choices=utils.MissionStatus.choices, default=utils.MissionStatus.IN_PROGRESS,
                            verbose_name=_('Status')
                            )

    agent_records = models.JSONField(default=list, verbose_name=_("Agent records"))
    subject_records = models.JSONField(default=list, verbose_name=_("Subject records"))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta:
        verbose_name = _('Mission')
        verbose_name_plural = _('Missions')
        ordering = ('created',)

    def __str__(self):
        return f'Mission by agent {self.agent.name}'

# The point is:
# First the data of people under ruble is sent (including location, heartrate)
# Demonstarte their location and heartrate on the map
# It might be better to recieve their location on redis. and bulk save to postgres after (for instance) 20 redis samples

class LifeData(models.Model):

    user = models.ForeignKey(
                    User, on_delete=models.CASCADE,
                    related_name='lifedate', verbose_name=_('User')
                    )
    location = models.PointField(verbose_name=_('location'), srid=4326)
    heartrate = models.PositiveIntegerField(verbose_name=_('heartrate'))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta:
        verbose_name = _('Life Data')
        verbose_name_plural = _('Life Data')
        ordering = ('created',)

    def __str__(self):
        return f'data at {self.location}, with heartrate of {self.heartrate}'

