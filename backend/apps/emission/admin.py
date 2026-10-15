from django.contrib import admin

from .models import (
    AirEmission,
    DataEvidence,
    EmissionActivity,
    EmissionBreakdown,
    EmissionCalculation,
    EmissionCategory,
    EmissionFactor,
    EmissionFactorSource,
    GasType,
    Scope3Category,
    UnitOfMeasure,
)


@admin.register(EmissionCategory)
class EmissionCategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "scope", "category_type", "parent"]
    list_filter = ["scope", "category_type"]
    search_fields = ["code", "name", "parent__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Scope3Category)
class Scope3CategoryAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "created_at"]
    search_fields = ["code", "name", "description"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GasType)
class GasTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "gas_name", "gwp_value"]
    search_fields = ["code", "gas_name", "gwp_reference"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "symbol"]
    search_fields = ["code", "name", "symbol"]


@admin.register(EmissionFactorSource)
class EmissionFactorSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "publisher", "published_on"]
    list_filter = ["published_on"]
    search_fields = ["name", "version", "publisher"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = ["factor_code", "factor_name", "category", "gas_type", "activity_unit", "is_active"]
    list_filter = ["category__scope", "category", "gas_type", "is_active", "source"]
    search_fields = ["factor_code", "factor_name", "category__name", "gas_type__code", "source__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(EmissionActivity)
class EmissionActivityAdmin(admin.ModelAdmin):
    list_display = ["activity_name", "organization", "facility", "category", "activity_date", "status", "total_co2e"]
    list_filter = ["status", "category__scope", "organization", "facility", "reporting_period"]
    search_fields = ["activity_name", "organization__name", "facility__name", "factor_code", "invoice_number"]
    readonly_fields = ["created_at", "updated_at", "total_co2e", "approved_at"]


@admin.register(EmissionCalculation)
class EmissionCalculationAdmin(admin.ModelAdmin):
    list_display = ["activity", "factor", "gas_type", "activity_quantity", "co2e_amount", "created_at"]
    list_filter = ["gas_type", "factor__category"]
    search_fields = ["activity__activity_name", "factor__factor_code", "gas_type__code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(DataEvidence)
class DataEvidenceAdmin(admin.ModelAdmin):
    list_display = ["name", "activity", "document_number", "uploaded_by", "created_at"]
    list_filter = ["uploaded_by", "created_at"]
    search_fields = ["name", "document_number", "activity__activity_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AirEmission)
class AirEmissionAdmin(admin.ModelAdmin):
    list_display = ["pollutant_type", "facility", "reporting_period", "amount", "unit", "created_at"]
    list_filter = ["facility", "reporting_period", "unit"]
    search_fields = ["pollutant_type", "facility__name", "reporting_period__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(EmissionBreakdown)
class EmissionBreakdownAdmin(admin.ModelAdmin):
    list_display = ["organization", "facility", "reporting_period", "scope", "category", "subcategory", "total_co2e"]
    list_filter = ["scope", "organization", "facility", "reporting_period"]
    search_fields = ["organization__name", "facility__name", "category__name", "subcategory__name"]
    readonly_fields = ["created_at", "updated_at"]
