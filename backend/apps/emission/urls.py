from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    EmissionCategoryViewSet,
    FuelTypeViewSet,
    Scope3CategoryViewSet,
    GasTypeViewSet,
    UnitOfMeasureViewSet,
    EmissionFactorSourceViewSet,
    EmissionFactorViewSet,
    EmissionActivityViewSet,
    EmissionCalculationViewSet,
    DataEvidenceViewSet,
    AirEmissionViewSet,
)

router = DefaultRouter()
router.register(r'emission-categories', EmissionCategoryViewSet)
router.register(r'scope-3-categories', Scope3CategoryViewSet)
router.register(r'gas-types', GasTypeViewSet)
router.register(r'units', UnitOfMeasureViewSet)
router.register(r'emission-factor-sources', EmissionFactorSourceViewSet)
router.register(r'emission-factors', EmissionFactorViewSet)
router.register(r'emission-activities', EmissionActivityViewSet)
router.register(r'emission-calculations', EmissionCalculationViewSet)
router.register(r'data-evidences', DataEvidenceViewSet)
router.register(r'air-emissions', AirEmissionViewSet)
router.register(r'fuel-types', FuelTypeViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
