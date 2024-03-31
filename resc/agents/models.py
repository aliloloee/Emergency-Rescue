from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _


class Point(models.Model) :
    """
    Point
    """

    name = models.CharField(verbose_name=_('name'), max_length=100)
    location = models.PointField(srid=4326)

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta :
        verbose_name = _('Point')
        verbose_name_plural = _('Points')
        ordering = ('created',)

    def __str__(self):
        return _('At {}').format(self.location)

