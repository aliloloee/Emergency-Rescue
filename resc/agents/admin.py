from django.contrib.gis import admin
from agents.models import Point, Region
from leaflet.admin import LeafletGeoAdmin


@admin.register(Point)
class PointAdmin(LeafletGeoAdmin) :
    list_display = ('name', )


@admin.register(Region)
class RegionAdmin(LeafletGeoAdmin):
    list_display = ('name', )
