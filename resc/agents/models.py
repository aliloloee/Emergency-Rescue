from django.db import models
from django.utils.translation import gettext_lazy as _


class Point(models.Model) :

    name = models.CharField(verbose_name=_('name'), max_length=100)

