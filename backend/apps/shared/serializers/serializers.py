from rest_framework import serializers

from ..models import City, Country, Location, Resource, State


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = [
            "id",
            "name",
            "url",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["id", "code", "name"]
        read_only_fields = ["id"]


class StateSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = State
        fields = ["id", "country", "country_name", "code", "name"]
        read_only_fields = ["id", "country_name"]


class CitySerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)
    country_id = serializers.IntegerField(source="state.country.id", read_only=True)
    country_name = serializers.CharField(source="state.country.name", read_only=True)

    class Meta:
        model = City
        fields = [
            "id",
            "state",
            "state_name",
            "country_id",
            "country_name",
            "name",
        ]
        read_only_fields = ["id", "state_name", "country_id", "country_name"]


class LocationSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(source="country.name", read_only=True)
    state_name = serializers.CharField(source="state.name", read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True)

    class Meta:
        model = Location
        fields = [
            "id",
            "country",
            "country_name",
            "state",
            "state_name",
            "city",
            "city_name",
            "street_address",
            "postal_code",
            "latitude",
            "longitude",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "country_name",
            "state_name",
            "city_name",
            "created_at",
            "updated_at",
        ]
