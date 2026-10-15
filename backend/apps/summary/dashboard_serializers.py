from rest_framework import serializers

class EmissionBreakdownItemSerializer(serializers.Serializer):
    category = serializers.CharField(allow_null=True)
    subcategory = serializers.CharField(allow_null=True)
    scope3_category = serializers.CharField(allow_null=True)
    gas_type = serializers.CharField(allow_null=True)
    total_co2e = serializers.FloatField()

    
class ScopeBreakdownSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    total_co2e = serializers.FloatField()
    percentage = serializers.FloatField()
    breakdown = EmissionBreakdownItemSerializer(many=True) 


class Scope2SplitSerializer(serializers.Serializer):
    location_based = serializers.FloatField()
    market_based = serializers.FloatField()


class YearlyEmissionSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    total_co2e = serializers.FloatField()
    scope_1 = serializers.FloatField()
    scope_2 = serializers.FloatField()
    scope_3 = serializers.FloatField()


class MonthlyEmissionSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    month_name = serializers.CharField()
    total_co2e = serializers.FloatField()
    scope_1 = serializers.FloatField()
    scope_2 = serializers.FloatField()
    scope_3 = serializers.FloatField()


class WaterCategorySerializer(serializers.Serializer):
    category = serializers.CharField()
    amount = serializers.FloatField()
    unit = serializers.CharField(allow_null=True)


class NeutralityClaimItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.CharField()
    reporting_period = serializers.CharField()
    gross_emissions = serializers.FloatField()
    reductions = serializers.FloatField()
    offsets_retired = serializers.FloatField()
    net_emissions = serializers.FloatField()


class CarbonCreditItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    project_name = serializers.CharField()
    source = serializers.CharField()
    registry_name = serializers.CharField()
    vintage_year = serializers.IntegerField()
    quantity_tco2e = serializers.FloatField()
    status = serializers.CharField()


class ReductionProjectItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    expected_reduction_tco2e = serializers.FloatField()
    actual_reduction_tco2e = serializers.FloatField()


class DashboardFiltersSerializer(serializers.Serializer):
    organization_id = serializers.IntegerField(allow_null=True)
    facility_id = serializers.IntegerField(allow_null=True)
    reporting_period_id = serializers.IntegerField(allow_null=True)
    year = serializers.IntegerField(allow_null=True)


class SummaryKpiSerializer(serializers.Serializer):
    gross_emissions = serializers.FloatField()
    offsets = serializers.FloatField()
    reductions = serializers.FloatField()
    net_emissions = serializers.FloatField()
    is_carbon_neutral = serializers.BooleanField()
    approved_activities = serializers.IntegerField()
    facilities_count = serializers.IntegerField()
    reporting_periods_count = serializers.IntegerField()


class EnergySummaryCardSerializer(serializers.Serializer):
    total_energy = serializers.FloatField()
    renewable_energy = serializers.FloatField()
    non_renewable_energy = serializers.FloatField()
    units = serializers.ListField(child=serializers.CharField())


class WaterSummaryCardSerializer(serializers.Serializer):
    total_water_usage = serializers.FloatField()
    units = serializers.ListField(child=serializers.CharField())
    categories = WaterCategorySerializer(many=True)


class WasteSummaryCardSerializer(serializers.Serializer):
    total_waste = serializers.FloatField()
    hazardous = serializers.FloatField()
    non_hazardous = serializers.FloatField()
    average_recycled_percentage = serializers.FloatField()
    units = serializers.ListField(child=serializers.CharField())


class DashboardSerializer(serializers.Serializer):
    filters = DashboardFiltersSerializer()
    entity = serializers.DictField()
    geo = serializers.DictField()
    kpis = SummaryKpiSerializer()
    highlights = serializers.DictField()
    scope_breakdown = ScopeBreakdownSerializer(many=True)
    scope2_split = Scope2SplitSerializer()
    yearly_emissions = YearlyEmissionSerializer(many=True)
    monthly_emissions = MonthlyEmissionSerializer(many=True)
    energy = EnergySummaryCardSerializer()
    water = WaterSummaryCardSerializer()
    waste = WasteSummaryCardSerializer()
    carbon_credits = CarbonCreditItemSerializer(many=True)
    reduction_projects = ReductionProjectItemSerializer(many=True)
    neutrality_claims = NeutralityClaimItemSerializer(many=True)





