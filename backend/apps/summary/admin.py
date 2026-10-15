from django.contrib import admin

from .models import (
    AuditLog,
    CarbonCredit,
    Certificate,
    EnergySummary,
    MonthlyEmissionSummary,
    NeutralityClaim,
    ReductionProject,
    WasteSummary,
    WaterUsage,
)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["action", "content_type", "object_id", "changed_by", "created_at"]
    list_filter = ["action", "content_type", "changed_by", "created_at"]
    search_fields = ["action", "message", "changed_by__username"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ["name", "file", "created_at"]
    search_fields = ["name", "description", "file"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(CarbonCredit)
class CarbonCreditAdmin(admin.ModelAdmin):
    list_display = ["project_name", "facility", "serial_number", "vintage_year", "quantity_tco2e", "status"]
    list_filter = ["status", "vintage_year", "facility"]
    search_fields = ["project_name", "serial_number", "registry_name", "facility__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ReductionProject)
class ReductionProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "facility", "start_date", "end_date", "expected_reduction_tco2e", "actual_reduction_tco2e"]
    list_filter = ["facility", "start_date", "end_date"]
    search_fields = ["name", "description", "facility__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(NeutralityClaim)
class NeutralityClaimAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "facility", "reporting_period", "status", "net_emissions"]
    list_filter = ["status", "organization", "facility", "reporting_period"]
    search_fields = ["name", "organization__name", "facility__name", "reporting_period__name"]
    readonly_fields = ["created_at", "updated_at", "gross_emissions", "reductions", "offsets_retired", "net_emissions"]


@admin.register(MonthlyEmissionSummary)
class MonthlyEmissionSummaryAdmin(admin.ModelAdmin):
    list_display = ["organization", "facility", "reporting_period", "year", "month", "scope", "total_co2e"]
    list_filter = ["organization", "facility", "reporting_period", "year", "month", "scope"]
    search_fields = ["organization__name", "facility__name", "reporting_period__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(EnergySummary)
class EnergySummaryAdmin(admin.ModelAdmin):
    list_display = ["facility", "reporting_period", "total_energy", "renewable_energy", "non_renewable_energy", "unit"]
    list_filter = ["facility", "reporting_period", "unit"]
    search_fields = ["facility__name", "reporting_period__name", "unit__code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(WaterUsage)
class WaterUsageAdmin(admin.ModelAdmin):
    list_display = ["facility", "reporting_period", "category", "amount", "unit"]
    list_filter = ["facility", "reporting_period", "unit", "category"]
    search_fields = ["facility__name", "reporting_period__name", "category", "unit__code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(WasteSummary)
class WasteSummaryAdmin(admin.ModelAdmin):
    list_display = ["facility", "reporting_period", "total_waste", "hazardous", "non_hazardous", "recycled_percentage", "unit"]
    list_filter = ["facility", "reporting_period", "unit"]
    search_fields = ["facility__name", "reporting_period__name", "unit__code"]
    readonly_fields = ["created_at", "updated_at"]
