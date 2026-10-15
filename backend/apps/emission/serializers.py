from rest_framework import serializers
from decimal import Decimal
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from .models import (
    EmissionScope,
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
    FuelType
)


class EmissionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionCategory
        fields = ['id', 'code', 'name', 'scope', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class Scope3CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Scope3Category
        fields = ['id', 'code', 'name', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class GasTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GasType
        fields = ['id', 'code', 'gas_name', 'gwp_value', 'gwp_reference', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ['id', 'code', 'name', 'symbol']
        read_only_fields = ['id']


class EmissionFactorSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionFactorSource
        fields = ['id', 'name', 'version', 'publisher', 'published_on', 'reference_url', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class EmissionFactorSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    gas_type_code = serializers.CharField(source='gas_type.code', read_only=True)
    source_name = serializers.CharField(source='source.name', read_only=True)
    geography_name = serializers.CharField(source='geography.name', read_only=True, allow_null=True)
    fuel_type_name = serializers.CharField(source='fuel_type.name', read_only=True, allow_null=True)

    class Meta:
        model = EmissionFactor
        fields = [
            'id',
            'source',
            'source_name',
            'category',
            'category_name',
            'scope3_category',
            'gas_type',
            'gas_type_code',
            'fuel_type',              
            'fuel_type_name',
            'factor_code',
            'factor_name',
            'factor_value',
            'activity_unit',
            'factor_unit',
            'geography',
            'geography_name',
            'valid_from',
            'valid_to',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EmissionCalculationSerializer(serializers.ModelSerializer):
    gas_type_code = serializers.CharField(source='gas_type.code', read_only=True)
    factor_code = serializers.CharField(source='factor.factor_code', read_only=True)
    fuel_type_name = serializers.CharField(
        source='factor.fuel_type.name',
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = EmissionCalculation
        fields = [
            'id',
            'activity',
            'factor',
            'factor_code',
            'gas_type',
            'fuel_type_name'
            'gas_type_code',
            'activity_quantity',
            'factor_value',
            'gas_amount',
            'co2e_amount',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class DataEvidenceSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = DataEvidence
        fields = [
            'id',
            'activity',
            'name',
            'file_url',
            'document_number',
            'uploaded_by',
            'uploaded_by_username',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'uploaded_by']


class EmissionActivitySerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    facility_name = serializers.CharField(source='facility.name', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_scope = serializers.CharField(source='category.get_scope_display', read_only=True)
    scope3_category_name = serializers.CharField(source='scope3_category.name', read_only=True, allow_null=True)
    unit_code = serializers.CharField(source='unit.code', read_only=True)
    entered_by_username = serializers.CharField(source='entered_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True, allow_null=True)
    fuel_type_name = serializers.CharField(source='fuel_type.name', read_only=True, allow_null=True)
    calculations = EmissionCalculationSerializer(many=True, read_only=True)
    evidences = DataEvidenceSerializer(many=True, read_only=True)
    
    class Meta:
        model = EmissionActivity
        fields = [
            'id',
            'organization',
            'organization_name',
            'facility',
            'facility_name',
            'department',
            'department_name',
            'reporting_period',
            'category',
            'category_name',
            'category_scope',
            'scope3_category',
            'scope3_category_name',
            'fuel_type',
            'fuel_type_name',
            'activity_name',
            'activity_date',
            'quantity',
            'unit',
            'unit_code',
            'factor_code',
            'scope2_method',
            'data_quality',
            'supplier_name',
            'invoice_number',
            'source_reference',
            'notes',
            'total_co2e',
            'status',
            'entered_by',
            'entered_by_username',
            'approved_by',
            'approved_by_username',
            'approved_at',
            'calculations',
            'evidences',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'total_co2e',
            'created_at',
            'updated_at',
            'calculations',
            'evidences',
        ]
        
        def validate(self, data):
            category = data.get("category") or getattr(self.instance, "category", None)
            fuel_type = data.get("fuel_type") or getattr(self.instance, "fuel_type", None)

            if category:
                category_name = category.name.lower()
                is_fuel_category = "fuel" in category_name or "combustion" in category_name

                if is_fuel_category and not fuel_type:
                    raise serializers.ValidationError(
                        {"fuel_type": "Fuel type is required for fuel-based activities"}
                    )

                if fuel_type and not is_fuel_category:
                    raise serializers.ValidationError(
                        {"fuel_type": "Fuel type should only be used for fuel-related categories"}
                    )

            return data


class AirEmissionSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source='facility.name', read_only=True)
    reporting_period_name = serializers.CharField(source='reporting_period.name', read_only=True)
    unit_code = serializers.CharField(source='unit.code', read_only=True)
    
    class Meta:
        model = AirEmission
        fields = [
            'id',
            'facility',
            'facility_name',
            'reporting_period',
            'reporting_period_name',
            'pollutant_type',
            'amount',
            'unit',
            'unit_code',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EmissionDashboardSerializer(serializers.Serializer):
    """Dashboard view for emissions across organization"""
    organization_id = serializers.IntegerField()
    organization_name = serializers.CharField()
    reporting_period_id = serializers.IntegerField()
    reporting_period_name = serializers.CharField()
    total_co2e = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_1_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_2_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_3_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    approved_activities = serializers.IntegerField()
    draft_activities = serializers.IntegerField()


class FacilityEmissionDashboardSerializer(serializers.Serializer):
    """Dashboard for facility emissions"""
    facility_id = serializers.IntegerField()
    facility_name = serializers.CharField()
    organization_name = serializers.CharField()
    total_co2e = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_1_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_2_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    scope_3_total = serializers.DecimalField(max_digits=18, decimal_places=6)
    is_carbon_neutral = serializers.BooleanField()
    total_activities = serializers.IntegerField()
    departments_count = serializers.IntegerField()

class FuelTypeSerializer(serializers.ModelSerializer):
    default_unit_code = serializers.CharField(source='default_unit.code', read_only=True)

    class Meta:
        model = FuelType
        fields = [
            'id',
            'name',
            'code',
            'default_unit',
            'default_unit_code',
            'description',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
