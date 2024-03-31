from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractBaseUser, PermissionsMixin
from django.utils.translation import gettext_lazy as _
import uuid


class UserProfileManager(BaseUserManager):

    def create_user(self, email, firstname, lastname, password=None, **extra_fields):
        if not email:
            raise ValueError(_('Users must have email'))

        user = self.model(
            email=self.normalize_email(email),
            firstname=firstname,
            lastname=lastname,
            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, firstname, lastname, password=None, **extra_fields) :
        user = self.create_user(email, firstname, lastname, password, **extra_fields)
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):

    email  = models.EmailField(max_length=255, unique=True, verbose_name=_('Email address'))
    firstname = models.CharField(max_length=100, verbose_name=_('Firstname'))
    lastname  = models.CharField(max_length=100, verbose_name=_('Lastname'))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    is_active  = models.BooleanField(default=False, verbose_name=_('Account is active'))
    is_staff   = models.BooleanField(default=False, verbose_name=_('Account is staff'))

    objects = UserProfileManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['firstname', 'lastname', ]

    def __str__(self) :
        return f'{self.firstname} {self.lastname}'


