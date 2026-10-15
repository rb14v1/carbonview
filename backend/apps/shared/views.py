from rest_framework import viewsets

from .models import City, Country, Location, Resource, State
from .serializers import (
    CitySerializer,
    CountrySerializer,
    LocationSerializer,
    ResourceSerializer,
    StateSerializer,
)


class ResourceViewSet(viewsets.ModelViewSet):
    queryset = Resource.objects.all().order_by("-created_at")
    serializer_class = ResourceSerializer


class CountryViewSet(viewsets.ModelViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer


class StateViewSet(viewsets.ModelViewSet):
    queryset = State.objects.select_related("country").all()
    serializer_class = StateSerializer


class CityViewSet(viewsets.ModelViewSet):
    queryset = City.objects.select_related("state", "state__country").all()
    serializer_class = CitySerializer


class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.select_related("country", "state", "city").all().order_by(
        "-created_at"
    )
    serializer_class = LocationSerializer
