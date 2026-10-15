from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CityViewSet,
    CountryViewSet,
    LocationViewSet,
    ResourceViewSet,
    StateViewSet,
)

router = DefaultRouter()
router.register(r"resources", ResourceViewSet)
router.register(r"countries", CountryViewSet)
router.register(r"states", StateViewSet)
router.register(r"cities", CityViewSet)
router.register(r"locations", LocationViewSet)

app_name = "shared"

urlpatterns = [
    path("", include(router.urls)),
]
