from django.contrib.gis import forms
from django.contrib.gis import admin
from django.contrib.auth import get_user_model
from leaflet.admin import LeafletGeoAdmin

from agents.models import Point, Region, Agent, AgentDevice, SubjectDevice, AgentRecords, SubjectRecords, Mission
from profiles.models import Profile
from profiles.utils import ProfileType

User = get_user_model()

def fetch_ids_of_normal_users() :
    normal_profiles = Profile.objects.filter(type=ProfileType.NORMAL)
    corresponding_users = User.objects.filter(id__in=normal_profiles.values('user_id'))
    return corresponding_users

normal_users = fetch_ids_of_normal_users()


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
        self.fields['subject'].queryset = normal_users

class SubjectDeviceAdminForm(forms.ModelForm):
    class Meta:
        model = SubjectDevice
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['subject'].queryset = normal_users


@admin.register(Point)
class PointAdmin(LeafletGeoAdmin) :
    list_display = ('name', 'latitude', 'longitude')
    readonly_fields = ('latitude', 'longitude')
    
    def latitude(self, obj):
        return obj.location.y if obj.location else None
    
    def longitude(self, obj):
        return obj.location.x if obj.location else None

    latitude.short_description = 'Latitude'
    longitude.short_description = 'Longitude'


@admin.register(Region)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('name', )


@admin.register(Agent)
class AgentAdmin(LeafletGeoAdmin) :
    form = AgentAdminForm
    list_display = ('name', )

@admin.register(SubjectDevice)
class SubjectDeviceAdmin(LeafletGeoAdmin) :
    form = SubjectDeviceAdminForm

admin.site.register(AgentDevice)
admin.site.register(SubjectRecords)
admin.site.register(AgentRecords)


@admin.register(Mission)
class MissionAdmin(LeafletGeoAdmin) :
    form = MissionAdminForm

