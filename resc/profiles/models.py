from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from profiles import utils
from agents.models import Region


User = get_user_model()

class Profile(models.Model) :
    user = models.OneToOneField(
                            User, on_delete=models.CASCADE, unique=True,
                            null=True, blank=True,
                            related_name='profile', verbose_name=_('User')
                            )
    
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, related_name='regions',
                            null=True, blank=True, verbose_name=_('Region'))

    type = models.PositiveSmallIntegerField(
                            choices=utils.ProfileType.choices, default=utils.ProfileType.NORMAL,
                            verbose_name=_('Type')
                            )

    address = models.CharField(null=True, blank=True, max_length=500, verbose_name=_('Address'))
    phone   = models.CharField(null=True, blank=True, max_length=30, verbose_name=_('Phone number'))
    city    = models.CharField(null=True, blank=True, max_length=50, verbose_name=_('City'))
    postal  = models.CharField(null=True, blank=True, max_length=50, verbose_name=_('Postal code'))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    def type_in_string (self):
        return dict(utils.ProfileType.choices)[self.type].upper()

    class Meta :
        verbose_name = _('Profile')
        verbose_name_plural = _('Profiles')
        ordering = ('created',)

    def __str__(self):
        return _('Profile of {}').format(self.user)