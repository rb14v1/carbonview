from django.contrib import admin
from .models import Organization, Facility, Department, ReportingPeriod


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'legal_name', 'industry_type', 'reporting_boundary', 'created_at']
    list_filter = ['industry_type', 'reporting_boundary', 'created_at']
    search_fields = ['name', 'legal_name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'legal_name', 'industry_type')
        }),
        ('Reporting', {
            'fields': ('reporting_boundary', 'base_currency', 'base_year', 'resource')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'facility_code', 'is_active', 'is_carbon_neutral', 'created_at']
    list_filter = ['is_active', 'is_carbon_neutral', 'organization', 'created_at']
    search_fields = ['name', 'facility_code', 'organization__name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('organization', 'name', 'facility_code', 'location')
        }),
        ('Settings', {
            'fields': ('description', 'is_active', 'is_carbon_neutral')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'facility', 'created_at']
    list_filter = ['facility', 'created_at']
    search_fields = ['name', 'facility__name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Information', {
            'fields': ('facility', 'name')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'year', 'start_date', 'end_date', 'is_closed']
    list_filter = ['year', 'is_closed', 'organization', 'created_at']
    search_fields = ['name', 'organization__name']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Information', {
            'fields': ('organization', 'name', 'year')
        }),
        ('Period', {
            'fields': ('start_date', 'end_date', 'is_closed')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
