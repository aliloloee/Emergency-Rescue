from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from django.utils.translation import get_language
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from agents import serializers



from django.shortcuts import render


class LifeAPIView(generics.GenericAPIView):

    permission_classes = (IsAuthenticated, )
    serializer_class = serializers.LifeSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid(raise_exception=True):
            serializer.save()

            return Response(
                _('Life data saved'),
                status = status.HTTP_201_CREATED
            )



def main(request) :
    response = render(request, "main.html", {})
    return response
