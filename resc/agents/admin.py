from django.contrib.gis import forms
from django.contrib.gis import admin
from django.contrib.auth import get_user_model
from leaflet.admin import LeafletGeoAdmin

from agents.models import (
    Point, Region, Agent, AgentDevice, SubjectDevice, AgentRecords, SubjectRecords,
    Mission, DistressAlert,
)
from profiles.models import Profile
from profiles.utils import ProfileType

User = get_user_model()

def fetch_ids_of_normal_users() :
    # Must stay a function called per form instance. Evaluating it once at import
    # time froze the dropdown at whatever existed when the process started, so
    # users created afterwards never appeared until the container was restarted.
    normal_profiles = Profile.objects.filter(type=ProfileType.NORMAL)
    corresponding_users = User.objects.filter(id__in=normal_profiles.values('user_id'))
    return corresponding_users


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
        self.fields['subject'].queryset = fetch_ids_of_normal_users()

class SubjectDeviceAdminForm(forms.ModelForm):
    class Meta:
        model = SubjectDevice
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['subject'].queryset = fetch_ids_of_normal_users()


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


@admin.register(DistressAlert)
class DistressAlertAdmin(LeafletGeoAdmin) :
    list_display = ('subject_device', 'status', 'emergency_center', 'first_seen', 'last_seen')
    list_filter = ('status',)
    readonly_fields = ('first_seen', 'last_seen')


@admin.register(Mission)
class MissionAdmin(LeafletGeoAdmin) :
    form = MissionAdminForm
    list_display = ('__str__', 'status', 'outcome', 'emergency_center', 'subject_device', 'archived')
    list_filter = ('status', 'outcome', 'archived')
    readonly_fields = ('acknowledged_at', 'reported_at', 'closed_at')


from agents.models import Route
@admin.register(Route)
class RoutesAdmin(LeafletGeoAdmin) :
    list_display = ('name', )