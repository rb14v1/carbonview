from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Q, DecimalField, Count
from django.db.models.functions import Coalesce
from decimal import Decimal
from .models import FuelType
from .serializers import FuelTypeSerializer

from .models import (
    EmissionCategory,
    Scope3Category,
    GasType,
    UnitOfMeasure,
    EmissionFactorSource,
    EmissionFactor,
    EmissionActivity,
    EmissionCalculation,
    DataEvidence,
    AirEmission,
)
from .serializers import (
    EmissionCategorySerializer,
    Scope3CategorySerializer,
    GasTypeSerializer,
    UnitOfMeasureSerializer,
    EmissionFactorSourceSerializer,
    EmissionFactorSerializer,
    EmissionActivitySerializer,
    EmissionCalculationSerializer,
    DataEvidenceSerializer,
    AirEmissionSerializer,
)


class EmissionCategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for emission categories"""
    queryset = EmissionCategory.objects.all()
    serializer_class = EmissionCategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['scope']
    search_fields = ['name', 'code']
    ordering_fields = ['scope', 'name', 'created_at']
    ordering = ['scope', 'name']


class Scope3CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for Scope 3 categories"""
    queryset = Scope3Category.objects.all()
    serializer_class = Scope3CategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['code', 'name', 'created_at']
    ordering = ['code']


class GasTypeViewSet(viewsets.ModelViewSet):
    """ViewSet for gas types"""
    queryset = GasType.objects.all()
    serializer_class = GasTypeSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'gas_name']
    ordering_fields = ['code', 'gas_name', 'created_at']
    ordering = ['code']


class UnitOfMeasureViewSet(viewsets.ModelViewSet):
    """ViewSet for units of measure"""
    queryset = UnitOfMeasure.objects.all()
    serializer_class = UnitOfMeasureSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['code', 'name', 'symbol']
    ordering_fields = ['code', 'name']
    ordering = ['code']


class EmissionFactorSourceViewSet(viewsets.ModelViewSet):
    """ViewSet for emission factor sources"""
    queryset = EmissionFactorSource.objects.all()
    serializer_class = EmissionFactorSourceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'publisher']
    ordering_fields = ['name', 'version', 'published_on', 'created_at']
    ordering = ['-published_on']


class EmissionFactorViewSet(viewsets.ModelViewSet):
    """ViewSet for emission factors"""
    queryset = EmissionFactor.objects.all()
    serializer_class = EmissionFactorSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'category__scope', 'gas_type','fuel_type', 'geography', 'is_active']
    search_fields = ['factor_code', 'factor_name']
    ordering_fields = ['factor_code', 'factor_value', 'valid_from', 'created_at']
    ordering = ['category', 'factor_code']


class EmissionActivityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for emission activities.
    
    Dashboard endpoint available at: /api/emission-activities/dashboard/
    """
    queryset = EmissionActivity.objects.all().prefetch_related('calculations', 'evidences')
    serializer_class = EmissionActivitySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'organization',
        'facility',
        'reporting_period',
        'category',
        'category__scope',
        'status',
        'data_quality',
        'fuel_type'
    ]
    search_fields = ['activity_name', 'factor_code', 'supplier_name']
    ordering_fields = ['activity_date', 'total_co2e', 'status', 'created_at']
    ordering = ['-activity_date']

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """
        Get emissions dashboard data aggregated by organization and reporting period.
        
        Query parameters:
        - organization_id: Filter by organization (optional)
        - reporting_period_id: Filter by reporting period (optional)
        - facility_id: Filter by facility (optional)
        """
        from apps.company.models import Organization, ReportingPeriod, Facility

        org_id = request.query_params.get('organization_id')
        period_id = request.query_params.get('reporting_period_id')
        facility_id = request.query_params.get('facility_id')

        base_qs = EmissionActivity.objects.filter(status='approved')

        if org_id:
            base_qs = base_qs.filter(organization_id=org_id)
        if period_id:
            base_qs = base_qs.filter(reporting_period_id=period_id)
        if facility_id:
            base_qs = base_qs.filter(facility_id=facility_id)

        # Calculate totals by scope
        scope_1_total = base_qs.filter(category__scope='S1').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        scope_2_total = base_qs.filter(category__scope='S2').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        scope_3_total = base_qs.filter(category__scope='S3').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        total_co2e = scope_1_total + scope_2_total + scope_3_total

        # Count by status
        approved_count = base_qs.count()
        draft_count = EmissionActivity.objects.filter(
            status='draft'
        ).count()

        dashboard_data = {
            'total_co2e': float(total_co2e),
            'scope_1_total': float(scope_1_total),
            'scope_2_total': float(scope_2_total),
            'scope_3_total': float(scope_3_total),
            'approved_activities': approved_count,
            'draft_activities': draft_count,
            'filters_applied': {
                'organization_id': org_id,
                'reporting_period_id': period_id,
                'facility_id': facility_id,
            }
        }
        fuel_data = (
            base_qs.values('fuel_type__name')
            .annotate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            .order_by('-total')
        )

        dashboard_data['fuel_breakdown'] = [
            {
                "fuel": item['fuel_type__name'] or "Non-fuel",
                "total_co2e": float(item['total'])
            }
            for item in fuel_data
        ]

        return Response(dashboard_data)

    @action(detail=False, methods=['get'])
    def facility_dashboard(self, request):
        """
        Get emissions dashboard for a specific facility.
        
        Query parameters:
        - facility_id: Facility ID (required)
        """
        from apps.company.models import Facility

        facility_id = request.query_params.get('facility_id')
        if not facility_id:
            return Response(
                {'error': 'facility_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            facility = Facility.objects.get(id=facility_id)
        except Facility.DoesNotExist:
            return Response(
                {'error': 'Facility not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        base_qs = EmissionActivity.objects.filter(facility=facility, status='approved')

        scope_1 = base_qs.filter(category__scope='S1').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        scope_2 = base_qs.filter(category__scope='S2').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        scope_3 = base_qs.filter(category__scope='S3').aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        total = scope_1 + scope_2 + scope_3

        dashboard_data = {
            'facility_id': facility.id,
            'facility_name': facility.name,
            'facility_code': facility.facility_code,
            'organization_name': facility.organization.name,
            'is_carbon_neutral': facility.is_carbon_neutral,
            'total_co2e': float(total),
            'scope_1_total': float(scope_1),
            'scope_2_total': float(scope_2),
            'scope_3_total': float(scope_3),
            'total_activities': base_qs.count(),
            'departments_count': facility.departments.count(),
            'location': facility.location.name if facility.location else None,
        }
        fuel_data = (
            base_qs.values('fuel_type__name')
            .annotate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
        )

        dashboard_data['fuel_breakdown'] = [
            {
                "fuel": item['fuel_type__name'] or "Non-fuel",
                "total_co2e": float(item['total'])
            }
            for item in fuel_data
        ]
        return Response(dashboard_data)
    
    @action(detail=False, methods=['get'])
    def fuel_breakdown(self, request):
        """
        Get emissions grouped by fuel type
        """
        qs = EmissionActivity.objects.filter(status='approved')

        org_id = request.query_params.get('organization_id')
        if org_id:
            qs = qs.filter(organization_id=org_id)
        data = (
            qs.values('fuel_type__id', 'fuel_type__name')
            .annotate(
                total_co2e=Coalesce(Sum('total_co2e'), Decimal('0')),
                activity_count=Count('id')
            )
            .order_by('-total_co2e')
        )
        return Response(data)


class EmissionCalculationViewSet(viewsets.ModelViewSet):
    """ViewSet for emission calculations (read-only)"""
    queryset = EmissionCalculation.objects.all()
    serializer_class = EmissionCalculationSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['activity', 'gas_type', 'factor']
    ordering_fields = ['co2e_amount', 'created_at']
    ordering = ['-co2e_amount']
    http_method_names = ['get', 'head', 'options']


class DataEvidenceViewSet(viewsets.ModelViewSet):
    """ViewSet for data evidence files"""
    queryset = DataEvidence.objects.all()
    serializer_class = DataEvidenceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['activity']
    search_fields = ['name', 'document_number']
    ordering_fields = ['created_at', 'name']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        """Set uploaded_by to current user"""
        if self.request.user.is_authenticated:
            serializer.save(uploaded_by=self.request.user)
        else:
            serializer.save()


class AirEmissionViewSet(viewsets.ModelViewSet):
    """ViewSet for air emissions"""
    queryset = AirEmission.objects.all()
    serializer_class = AirEmissionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['facility', 'reporting_period']
    search_fields = ['pollutant_type', 'facility__name']
    ordering_fields = ['amount', 'created_at']
    ordering = ['-created_at']

class FuelTypeViewSet(viewsets.ModelViewSet):
    """ViewSet for fuel types"""
    queryset = FuelType.objects.all()
    serializer_class = FuelTypeSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code']
    ordering_fields = ['name', 'code', 'created_at']
    ordering = ['name']