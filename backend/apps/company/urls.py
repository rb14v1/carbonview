from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrganizationViewSet, FacilityViewSet, DepartmentViewSet, ReportingPeriodViewSet

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet)
router.register(r'facilities', FacilityViewSet)
router.register(r'departments', DepartmentViewSet)
router.register(r'reporting-periods', ReportingPeriodViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
