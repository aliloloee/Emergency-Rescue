from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.contrib.gis.geos import Point
from agents.models import LifeData

from decimal import Decimal

class LifeSerializer(serializers.ModelSerializer) :
    lattitude = serializers.DecimalField(max_value=Decimal(90.00000), min_value=Decimal(-90.00000), max_digits=7, decimal_places=5)
    longitude = serializers.DecimalField(max_value=Decimal(180.00000), min_value=Decimal(-180.00000), max_digits=8, decimal_places=5)

    class Meta :
        ref_name = None
        model = LifeData
        fields = ('lattitude', 'longitude', 'heartrate', )

    def create(self, validated_data):
        latt, long, user = validated_data.pop('lattitude'), validated_data.pop('longitude'), self.context['request'].user
        point = Point((latt, long))
        validated_data['user'] = user
        validated_data['location'] = point

        instance = super().create(validated_data)
        instance.save()
        return instance

