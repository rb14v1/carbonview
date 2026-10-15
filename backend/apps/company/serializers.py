from rest_framework import serializers
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.db.models.functions import Coalesce
from .models import Organization, Facility, Department, ReportingPeriod
from apps.shared.models import Resource
from apps.shared.serializers.serializers import ResourceSerializer

class OrganizationSerializer(serializers.ModelSerializer):
    resource = ResourceSerializer(read_only=True)
    resource_id = serializers.PrimaryKeyRelatedField(
        queryset=Resource.objects.all(), write_only=True, required=False, source='resource'
    )
    total_co2e = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id',
            'name',
            'legal_name',
            'industry_type',
            'reporting_boundary',
            'base_currency',
            'base_year',
            'resource',
            'resource_id',
            'total_co2e',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_co2e']

    def get_total_co2e(self, obj):
        """Calculate total CO2e emissions for the organization"""
        from apps.emission.models import EmissionActivity
        total = EmissionActivity.objects.filter(
            organization=obj,
            status='approved'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
        return float(total['total'])


class FacilitySerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(
        source='organization.name', read_only=True
    )
    location_name = serializers.CharField(
        source='location.name', read_only=True
    )
    total_co2e = serializers.SerializerMethodField()
    carbon_neutral_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Facility
        fields = [
            'id',
            'organization',
            'organization_name',
            'location',
            'location_name',
            'facility_code',
            'name',
            'description',
            'is_active',
            'is_carbon_neutral',
            'carbon_neutral_status',
            'total_co2e',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_co2e', 'carbon_neutral_status']

    def get_total_co2e(self, obj):
        """Calculate total CO2e emissions for the facility"""
        from apps.emission.models import EmissionActivity
        total = EmissionActivity.objects.filter(
            facility=obj,
            status='approved'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
        return float(total['total'])

    def get_carbon_neutral_status(self, obj):
        """Determine if facility is truly carbon neutral based on emissions"""
        from apps.emission.models import EmissionActivity
        total_co2e = EmissionActivity.objects.filter(
            facility=obj,
            status='approved'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))['total']
        
        return {
            'is_carbon_neutral': obj.is_carbon_neutral,
            'has_emissions': total_co2e > 0,
            'total_emissions': float(total_co2e)
        }
    

class DepartmentSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(
        source='facility.name', read_only=True
    )
    organization_name = serializers.CharField(
        source='facility.organization.name', read_only=True
    )
    total_co2e = serializers.SerializerMethodField()
    
    class Meta:
        model = Department
        fields = [
            'id',
            'facility',
            'facility_name',
            'organization_name',
            'name',
            'total_co2e',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_co2e']

    def get_total_co2e(self, obj):
        """Calculate total CO2e emissions for the department"""
        from apps.emission.models import EmissionActivity
        total = EmissionActivity.objects.filter(
            department=obj,
            status='approved'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
        return float(total['total'])


class ReportingPeriodSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(
        source='organization.name', read_only=True
    )
    total_co2e = serializers.SerializerMethodField()
    breakdown_by_scope = serializers.SerializerMethodField()
    
    class Meta:
        model = ReportingPeriod
        fields = [
            'id',
            'organization',
            'organization_name',
            'name',
            'year',
            'start_date',
            'end_date',
            'is_closed',
            'total_co2e',
            'breakdown_by_scope',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_co2e', 'breakdown_by_scope']

    def validate(self, attrs):
        """Run model-level period validation against the combined incoming and existing values before saving."""
        instance = ReportingPeriod(**attrs)
        if self.instance is not None:
            instance.pk = self.instance.pk
            for field in ('organization', 'name', 'year', 'start_date', 'end_date', 'is_closed'):
                if field not in attrs:
                    setattr(instance, field, getattr(self.instance, field))

        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)

        return attrs

    def get_total_co2e(self, obj):
        """Calculate total CO2e emissions for the reporting period"""
        from apps.emission.models import EmissionActivity
        total = EmissionActivity.objects.filter(
            reporting_period=obj,
            status='approved'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
        return float(total['total'])

    def get_breakdown_by_scope(self, obj):
        """Get emissions breakdown by scope (1, 2, 3)"""
        from apps.emission.models import EmissionActivity, EmissionScope
        
        breakdown = {}
        for scope in ['S1', 'S2', 'S3']:
            total = EmissionActivity.objects.filter(
                reporting_period=obj,
                status='approved',
                category__scope=scope
            ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            scope_name = dict(EmissionScope.choices).get(scope, scope)
            breakdown[scope_name] = float(total['total'])
        
        return breakdown


class OrganizationDashboardSerializer(serializers.ModelSerializer):
    """Dashboard view for organization with emissions and facilities summary"""
    total_co2e = serializers.SerializerMethodField()
    total_scope_1 = serializers.SerializerMethodField()
    total_scope_2 = serializers.SerializerMethodField()
    total_scope_3 = serializers.SerializerMethodField()
    carbon_neutral_facilities = serializers.SerializerMethodField()
    facilities_count = serializers.SerializerMethodField()
    active_reporting_periods = serializers.SerializerMethodField()
    net_co2e = serializers.SerializerMethodField()
    offsets = serializers.SerializerMethodField()
    reductions = serializers.SerializerMethodField()
    scope2_split = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id',
            'name',
            'legal_name',
            'industry_type',
            'reporting_boundary',
            'total_co2e',
            'net_co2e',          
            'offsets',           
            'reductions',        
            'total_scope_1',
            'total_scope_2',
            'total_scope_3',
            'scope2_split',
            'carbon_neutral_facilities',
            'facilities_count',
            'active_reporting_periods',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def _get_net_emissions_cache(self, obj):
        """Cache net-emission calculations per organization so repeated serializer fields reuse the same aggregates."""
        cache = getattr(self, '_net_emissions_cache', {})
        if obj.pk not in cache:
            try:
                from apps.summary.models import CarbonCredit, ReductionProject
                cache[obj.pk] = self._calculate_net_emissions(obj, CarbonCredit, ReductionProject)
            except (ImportError, AttributeError):
                cache[obj.pk] = None
            self._net_emissions_cache = cache
        return cache[obj.pk]

    def _get_scope_totals(self, obj):
        """Aggregate approved activity totals by scope once per organization and keep the result in serializer cache."""
        cache = getattr(self, '_scope_totals_cache', {})
        if obj.pk not in cache:
            from apps.emission.models import EmissionActivity
            rows = (
                EmissionActivity.objects.filter(
                    organization=obj,
                    status='approved',
                    category__scope__in=['S1', 'S2', 'S3'],
                )
                .values('category__scope')
                .annotate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            )
            cache[obj.pk] = {row['category__scope']: row['total'] for row in rows}
            self._scope_totals_cache = cache
        return cache[obj.pk]
    
    def _calculate_net_emissions(self, obj, CarbonCredit=None, ReductionProject=None, level="organization"):
        """Compute gross emissions, retired credits, reductions, and net emissions using organization or facility filters."""
        from apps.emission.models import EmissionActivity
        if CarbonCredit is None or ReductionProject is None:
            return Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')

        filters = {'status': 'approved'}

        if level == "organization":
            filters['organization'] = obj
            credit_filter = {'facility__organization': obj, 'status': 'retired'}
            reduction_filter = {'facility__organization': obj}
        else:
            filters['facility'] = obj
            credit_filter = {'facility': obj, 'status': 'retired'}
            reduction_filter = {'facility': obj}

        emissions = EmissionActivity.objects.filter(**filters).aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        credits = CarbonCredit.objects.filter(**credit_filter).aggregate(
            total=Coalesce(Sum('quantity_tco2e'), Decimal('0'))
        )['total']

        reductions = ReductionProject.objects.filter(**reduction_filter).aggregate(
            total=Coalesce(Sum('actual_reduction_tco2e'), Decimal('0'))
        )['total']

        return emissions, credits, reductions, emissions - credits - reductions

    def get_total_co2e(self, obj):
        """Total emissions across all facilities"""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            from apps.emission.models import EmissionActivity
            total = EmissionActivity.objects.filter(
                organization=obj,
                status='approved'
            ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            return float(total['total'])
        emissions, credits, reductions, net = totals
        return float(emissions)

    def get_net_co2e(self, obj):
        """Return cached net emissions, or zero when reduction and credit models are unavailable."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(net)

    def get_total_scope_1(self, obj):
        """Total Scope 1 emissions"""
        return float(self._get_scope_totals(obj).get('S1', Decimal('0')))

    def get_total_scope_2(self, obj):
        """Total Scope 2 emissions"""
        return float(self._get_scope_totals(obj).get('S2', Decimal('0')))

    def get_total_scope_3(self, obj):
        """Total Scope 3 emissions"""
        return float(self._get_scope_totals(obj).get('S3', Decimal('0')))

    def get_carbon_neutral_facilities(self, obj):
        """Count of carbon neutral facilities"""
        return obj.facilities.filter(is_carbon_neutral=True).count()

    def get_facilities_count(self, obj):
        """Total facilities in organization"""
        return obj.facilities.count()

    def get_active_reporting_periods(self, obj):
        """List of active reporting periods"""
        periods = obj.reporting_periods.filter(is_closed=False).values_list('id', 'name', 'year')
        return [{'id': p[0], 'name': p[1], 'year': p[2]} for p in periods]

    def get_scope2_split(self, obj):
        """Split approved Scope 2 emissions into market-based and location-based totals for dashboard charts."""
        from apps.emission.models import EmissionActivity

        market = EmissionActivity.objects.filter(
            organization=obj,
            status='approved',
            category__scope='S2',
            scope2_method='market_based'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))

        location = EmissionActivity.objects.filter(
            organization=obj,
            status='approved',
            category__scope='S2',
            scope2_method='location_based'
        ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))

        return {
            "market_based": float(market['total']),
            "location_based": float(location['total'])
        }
    
    def get_offsets(self, obj):
        """Expose cached retired-credit totals as dashboard offsets for the organization."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(credits)

    def get_reductions(self, obj):
        """Expose cached reduction-project totals so the dashboard can show avoided emissions separately."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(reductions)


class FacilityDashboardSerializer(serializers.ModelSerializer):
    """Dashboard view for facility with emissions summary"""
    total_co2e = serializers.SerializerMethodField()
    total_scope_1 = serializers.SerializerMethodField()
    total_scope_2 = serializers.SerializerMethodField()
    total_scope_3 = serializers.SerializerMethodField()
    departments_count = serializers.SerializerMethodField()
    carbon_neutral_status = serializers.SerializerMethodField()
    net_co2e = serializers.SerializerMethodField()
    offsets = serializers.SerializerMethodField()
    reductions = serializers.SerializerMethodField()
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True, allow_null=True)
    
    class Meta:
        model = Facility
        fields = [
            'id',
            'name',
            'facility_code',
            'organization',
            'organization_name',
            'location',
            'location_name',
            'is_active',
            'is_carbon_neutral',
            'carbon_neutral_status',
            'total_co2e',
            'net_co2e',        
            'offsets',         
            'reductions',      
            'total_scope_1',
            'total_scope_2',
            'total_scope_3',
            'departments_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def _get_net_emissions_cache(self, obj):
        """Cache net-emission calculations per facility so multiple dashboard fields share one aggregate lookup."""
        cache = getattr(self, '_net_emissions_cache', {})
        if obj.pk not in cache:
            try:
                from apps.summary.models import CarbonCredit, ReductionProject
                cache[obj.pk] = self._calculate_net_emissions(obj, CarbonCredit, ReductionProject, level="facility")
            except (ImportError, AttributeError):
                cache[obj.pk] = None
            self._net_emissions_cache = cache
        return cache[obj.pk]

    def _get_scope_totals(self, obj):
        """Aggregate approved facility emissions by scope once and reuse the values across serializer fields."""
        cache = getattr(self, '_scope_totals_cache', {})
        if obj.pk not in cache:
            from apps.emission.models import EmissionActivity
            rows = (
                EmissionActivity.objects.filter(
                    facility=obj,
                    status='approved',
                    category__scope__in=['S1', 'S2', 'S3'],
                )
                .values('category__scope')
                .annotate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            )
            cache[obj.pk] = {row['category__scope']: row['total'] for row in rows}
            self._scope_totals_cache = cache
        return cache[obj.pk]

    def _calculate_net_emissions(self, obj, CarbonCredit=None, ReductionProject=None, level="facility"):
        """Compute facility or organization gross emissions, offsets, reductions, and the resulting net total."""
        from apps.emission.models import EmissionActivity
        if CarbonCredit is None or ReductionProject is None:
            return Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')

        filters = {'status': 'approved'}

        if level == "organization":
            filters['organization'] = obj
            credit_filter = {'facility__organization': obj, 'status': 'retired'}
            reduction_filter = {'facility__organization': obj}
        else:
            filters['facility'] = obj
            credit_filter = {'facility': obj, 'status': 'retired'}
            reduction_filter = {'facility': obj}

        emissions = EmissionActivity.objects.filter(**filters).aggregate(
            total=Coalesce(Sum('total_co2e'), Decimal('0'))
        )['total']

        credits = CarbonCredit.objects.filter(**credit_filter).aggregate(
            total=Coalesce(Sum('quantity_tco2e'), Decimal('0'))
        )['total']

        reductions = ReductionProject.objects.filter(**reduction_filter).aggregate(
            total=Coalesce(Sum('actual_reduction_tco2e'), Decimal('0'))
        )['total']

        return emissions, credits, reductions, emissions - credits - reductions

    def get_total_co2e(self, obj):
        """Total emissions for facility"""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            from apps.emission.models import EmissionActivity
            total = EmissionActivity.objects.filter(
                facility=obj,
                status='approved'
            ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))
            return float(total['total'])
        emissions, credits, reductions, net = totals
        return float(emissions)

    def get_total_scope_1(self, obj):
        """Scope 1 emissions"""
        return float(self._get_scope_totals(obj).get('S1', Decimal('0')))

    def get_total_scope_2(self, obj):
        """Scope 2 emissions"""
        return float(self._get_scope_totals(obj).get('S2', Decimal('0')))

    def get_total_scope_3(self, obj):
        """Scope 3 emissions"""
        return float(self._get_scope_totals(obj).get('S3', Decimal('0')))

    def get_departments_count(self, obj):
        """Count of departments in facility"""
        return obj.departments.count()

    # def get_carbon_neutral_status(self, obj):
    #     """Carbon neutral status with details"""
    #     from apps.emission.models import EmissionActivity
    #     total_co2e = EmissionActivity.objects.filter(
    #         facility=obj,
    #         status='approved'
    #     ).aggregate(total=Coalesce(Sum('total_co2e'), Decimal('0')))['total']
        
    #     return {
    #         'is_marked_neutral': obj.is_carbon_neutral,
    #         'has_zero_emissions': total_co2e == 0,
    #         'total_emissions': float(total_co2e)
    #     }
    def get_carbon_neutral_status(self, obj):
        """Describe neutrality using net emissions when available, with a gross-emissions fallback when not."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            gross = Decimal(str(self.get_total_co2e(obj)))
            return {
                'is_carbon_neutral': obj.is_carbon_neutral,
                'net_emissions': float(gross),
                'gross_emissions': float(gross),
                'offsets': 0,
            }
        emissions, credits, reductions, net = totals
        return {
            'is_carbon_neutral': net <= 0,
            'net_emissions': float(net),
            'gross_emissions': float(emissions),
            'offsets': float(credits),
        }

    def get_net_co2e(self, obj):
        """Return cached facility net emissions, or zero when the supporting summary models are unavailable."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(net)
    
    def get_offsets(self, obj):
        """Return cached retired-credit totals for the facility dashboard offset metric."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(credits)

    def get_reductions(self, obj):
        """Return cached reduction-project totals so facility dashboards can show abatement impact."""
        totals = self._get_net_emissions_cache(obj)
        if totals is None:
            return float(0)
        emissions, credits, reductions, net = totals
        return float(reductions)
