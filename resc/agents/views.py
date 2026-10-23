from django.views.generic import TemplateView
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.gis.db.models import Extent
from django.http import HttpResponseForbidden, JsonResponse
from django.utils.translation import gettext_lazy as _

from agents.models import Region
from profiles.models import Profile
from profiles.utils import ProfileType

import os



class MainBoard(LoginRequiredMixin, UserPassesTestMixin, TemplateView) :
    template_name = "main.html"

    def get_context_data(self, **kwargs) :
        context = super().get_context_data(**kwargs)
        extra_context = {}
        user = self.request.user

        polygon = user.profile.region.polygon
        centroid = polygon.centroid

        # Calculate bounds of the polygon
        bounds = polygon.extent  # returns (xmin, ymin, xmax, ymax)
        extra_context['center_lat'] = centroid.y
        extra_context['center_lng'] = centroid.x
        extra_context['bounds'] = bounds

        # get centers locations
        centers_within_region = Profile.center_objects.get_centers_in_local_region(region=user.profile.region)
        locations = []
        for center in centers_within_region :
            loc = center.location.location
            li = [loc.y, loc.x, str(center.user)]

            # make sure the length of li for the corresponding center is 4 (it's 3 for other centers)
            if center.user == user :
                li.append('self')

            locations.append(li)

        extra_context['locations'] = locations

        # The map uses the same idea of "live" the dispatcher does, so a marker
        # cannot sit there looking current while the server has already written
        # that device off as offline.
        extra_context['live_seconds'] = settings.AGENT_LIVE_SECONDS

        context.update(extra_context)
        return context
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.profile.type == ProfileType.EMERGENCY_CENTER

    def handle_no_permission(self):
        return HttpResponseForbidden("You are not allowed to access this page.")


class RootBoard(LoginRequiredMixin, UserPassesTestMixin, TemplateView) :
    """
    The administrator's system-wide view.

    Gated to SUPER, which is the mirror of MainBoard's gate rather than a
    widening of it: a root account cannot open the centre dashboard, and a
    centre account cannot open this. The socket behind it enforces the same
    split, so neither can be reached by going around the other.
    """
    template_name = "root.html"

    def get_context_data(self, **kwargs) :
        context = super().get_context_data(**kwargs)

        # The map covers every region, so centre it on all of them together
        # rather than on whichever happens to be first.
        regions = Region.objects.all()
        extent = regions.aggregate(area=Extent('polygon'))['area']

        if extent :
            context['center_lat'] = (extent[1] + extent[3]) / 2
            context['center_lng'] = (extent[0] + extent[2]) / 2
        else :
            context['center_lat'] = 0
            context['center_lng'] = 0

        context['regions'] = [region.name for region in regions]
        context['live_seconds'] = settings.AGENT_LIVE_SECONDS
        return context

    def test_func(self):
        return (self.request.user.is_authenticated
                and self.request.user.profile.type == ProfileType.SUPER)

    def handle_no_permission(self):
        return HttpResponseForbidden("You are not allowed to access this page.")


def js_config(requests):
    context = {
        'DJANGO_SETTINGS_MODULE' : os.environ.get('DJANGO_SETTINGS_MODULE')
    }

    return JsonResponse(context)

