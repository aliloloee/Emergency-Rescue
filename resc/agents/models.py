from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model

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





# Assign rescue mission to the nearest Emergency center or the nearest free Emergency agent
    # Emergency centers have a pre-defined capacity (if they have no free agent, then the app must choose the second
    # closest center)
# Demonstrate the location of

# not migrated yet
# class EmergencyCenter(models.Model) :
#     name = ...
#     location = models.ForeignKey(Point, on_delete=models.PROTECT)
#     has_free_agent = ... # (upgrade with signals probably)
#     capacity = ... # (pre-defined number demonstrating the number of agents they have)
#     is_active = ...


# class Mission(models.Model) :
#     center = ...




