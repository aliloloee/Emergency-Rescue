from django.contrib.gis import admin
from agents.models import Point, Region, LifeData
from leaflet.admin import LeafletGeoAdmin


@admin.register(Point)
class PointAdmin(LeafletGeoAdmin) :
    list_display = ('name', )


@admin.register(Region)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('name', )

@admin.register(LifeData)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('heartrate', )
