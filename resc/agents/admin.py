from django.contrib.gis import forms
from django.contrib.gis import admin
from django.contrib.auth import get_user_model
from leaflet.admin import LeafletGeoAdmin

from agents.models import Point, Region, Agent, Mission, LifeData
from profiles.models import Profile
from profiles.utils import ProfileType

User = get_user_model()

class AgentAdminForm(forms.ModelForm):
    class Meta:
        model = Agent
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        emergency_center_profiles = Profile.objects.filter(type=ProfileType.EMERGENCY_CENTER)
        corresponding_users = User.objects.filter(id__in=emergency_center_profiles.values('user_id'))
        self.fields['emergency_center'].queryset = corresponding_users

class MissionAdminForm(forms.ModelForm):
    class Meta:
        model = Mission
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        normal_profiles = Profile.objects.filter(type=ProfileType.NORMAL)
        corresponding_users = User.objects.filter(id__in=normal_profiles.values('user_id'))
        self.fields['subject'].queryset = corresponding_users


@admin.register(Point)
class PointAdmin(LeafletGeoAdmin) :
    list_display = ('name', )


@admin.register(Region)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('name', )


@admin.register(Agent)
class AgentAdmin(LeafletGeoAdmin) :
    form = AgentAdminForm
    list_display = ('name', )


@admin.register(Mission)
class MissionAdmin(LeafletGeoAdmin) :
    form = MissionAdminForm


# Is this needed ?
@admin.register(LifeData)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('heartrate', )
