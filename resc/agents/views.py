from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponseForbidden
from django.utils.translation import gettext_lazy as _

from profiles.models import Profile
from profiles.utils import ProfileType


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

        context.update(extra_context)
        return context
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.profile.type == ProfileType.EMERGENCY_CENTER

    def handle_no_permission(self):
        return HttpResponseForbidden("You are not allowed to access this page.")

