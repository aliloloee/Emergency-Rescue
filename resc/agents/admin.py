from django.contrib.gis import admin
from agents.models import Point
from leaflet.admin import LeafletGeoAdmin


@admin.register(Point)
class PointAdmin(LeafletGeoAdmin) :
    list_display = ('name', 'location')


