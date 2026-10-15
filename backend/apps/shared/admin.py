from django.contrib import admin

from .models import Resource, Country, State, City, Location


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "created_at"]
    search_fields = ["name", "url", "description"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name", "code"]


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "country"]
    list_filter = ["country"]
    search_fields = ["name", "code", "country__name"]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "state"]
    list_filter = ["state__country", "state"]
    search_fields = ["name", "state__name", "state__country__name"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["street_address", "city", "state", "country", "postal_code", "created_at"]
    list_filter = ["country", "state", "city", "created_at"]
    search_fields = ["street_address", "postal_code", "city__name", "state__name", "country__name"]
    readonly_fields = ["created_at", "updated_at"]
