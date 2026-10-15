from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Organization, Facility, Department, ReportingPeriod
from .serializers import (
    OrganizationSerializer,
    FacilitySerializer,
    DepartmentSerializer,
    ReportingPeriodSerializer,
    OrganizationDashboardSerializer,
    FacilityDashboardSerializer,
)

class OrganizationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing organizations.
    Provides CRUD operations for Organization model.
    
    Dashboard endpoint available at: /api/organizations/{id}/dashboard/
    """
    queryset = Organization.objects.prefetch_related(
    'facilities',
    'reporting_periods'
    )
    serializer_class = OrganizationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['industry_type', 'reporting_boundary']
    search_fields = ['name', 'legal_name']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['name']

    @action(detail=True, methods=['get'], serializer_class=OrganizationDashboardSerializer)
    def dashboard(self, request, pk=None):
        """
        Get organization dashboard with emissions summary.
        Shows total CO2e, breakdown by scope, facilities count, and carbon neutral status.
        """
        organization = self.get_object()
        serializer = self.get_serializer(organization)
        return Response(serializer.data)


class FacilityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing facilities.
    Provides CRUD operations for Facility model.
    
    Dashboard endpoint available at: /api/facilities/{id}/dashboard/
    """
    queryset = Facility.objects.select_related('organization', 'location').prefetch_related('departments')
    serializer_class = FacilitySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['organization', 'is_active', 'is_carbon_neutral']
    search_fields = ['name', 'facility_code', 'organization__name']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['organization__name', 'name']

    @action(detail=True, methods=['get'], serializer_class=FacilityDashboardSerializer)
    def dashboard(self, request, pk=None):
        """
        Get facility dashboard with emissions summary.
        Shows total CO2e, breakdown by scope, departments count, and carbon neutral status.
        """
        facility = self.get_object()
        serializer = self.get_serializer(facility)
        return Response(serializer.data)


class DepartmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing departments.
    Provides CRUD operations for Department model.
    """
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['facility', 'facility__organization']
    search_fields = ['name', 'facility__name']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['facility__name', 'name']


class ReportingPeriodViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reporting periods.
    Provides CRUD operations for ReportingPeriod model.
    """
    queryset = ReportingPeriod.objects.all()
    serializer_class = ReportingPeriodSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['organization', 'year', 'is_closed']
    search_fields = ['name', 'organization__name']
    ordering_fields = ['year', 'start_date', 'created_at', 'updated_at']
    ordering = ['-year', '-start_date']
    ordering = ['-year', '-start_date']
