from typing import Any
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponseForbidden
from django.utils.translation import get_language
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from agents import serializers
from profiles.utils import ProfileType


class MainBoard(LoginRequiredMixin, UserPassesTestMixin, TemplateView) :
    template_name = "main.html"

    def get_context_data(self, **kwargs) :
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # only emergency must have region in their profiles
        polygon = user.profile.region.polygon
        location = user.profile.location.location
        centroid = polygon.centroid

        # Calculate bounds of the polygon
        bounds = polygon.extent  # returns (xmin, ymin, xmax, ymax)

        context['center_lat'] = centroid.y
        context['center_lng'] = centroid.x
        context['bounds'] = bounds
        context['emergencyLat'] = location.y
        context['emergencyLng'] = location.x
        return context
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.profile.type == ProfileType.EMERGENCY_CENTER

    def handle_no_permission(self):
        return HttpResponseForbidden("You are not allowed to access this page.")

