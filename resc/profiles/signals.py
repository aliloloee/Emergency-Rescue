from django.dispatch import receiver
from django.db.models.signals import post_save
from django.contrib.auth import get_user_model

from profiles.models import Profile
from profiles.utils import ProfileType


@receiver(post_save, sender=get_user_model())
def post_create_profile(sender, instance, created, **kwargs) :
    """
    Create Profile instance for new users. Superusers will have super type profiles.
    """
    if created :
        profile = Profile.objects.create(user=instance)

    if instance.is_superuser :
        profile, _ = Profile.objects.get_or_create(user=instance)
        profile.type = ProfileType.SUPER
        profile.save()