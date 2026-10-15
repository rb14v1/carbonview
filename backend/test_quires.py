import os
from pathlib import Path
from decimal import Decimal
from datetime import date

import django
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone


BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.chdir(BASE_DIR)
django.setup()
 
from apps.shared.models import Resource, Country, State, City, Location
from apps.company.models import (
    Organization, Facility, Department, ReportingPeriod,
    IndustryType, OrganizationBoundary,
)
from apps.emission.models import (
    EmissionCategory, Scope3Category, GasType, UnitOfMeasure,
    EmissionFactorSource, EmissionFactor, EmissionActivity,
    EmissionCalculation, DataEvidence,
    EmissionScope, Scope2Method, ActivityDataQuality, RecordStatus,
)
from apps.summary.models import (
    CarbonCredit, ReductionProject, NeutralityClaim,
    MonthlyEmissionSummary, EnergySummary, WaterUsage, WasteSummary,
)
 
 
class Command(BaseCommand):
    help = "Seed demo carbon accounting data for development/testing"
 
    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete seeded demo data before recreating it')
        parser.add_argument('--username', default='carbonadmin', help='Username for seeded user')
 
    @transaction.atomic
    def handle(self, *args, **options):
        username = options['username']
        User = get_user_model()
 
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                'email': 'carbonadmin@example.com',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if not user.has_usable_password():
            user.set_password('Admin@12345')
            user.save(update_fields=['password'])
 
        resource, _ = Resource.objects.get_or_create(
            url='https://example.com/carbonview',
            defaults={'name': 'CarbonView'}
        )
 
        country, _ = Country.objects.get_or_create(code='IN', defaults={'name': 'India'})
        state, _ = State.objects.get_or_create(country=country, name='Karnataka', defaults={'code': 'KA'})
        city, _ = City.objects.get_or_create(state=state, name='Bengaluru')
        location, _ = Location.objects.get_or_create(
            country=country,
            state=state,
            city=city,
            street_address='Outer Ring Road, Bengaluru',
            postal_code='560103',
        )
 
        org, _ = Organization.objects.get_or_create(
            name='CarbonView Demo Org',
            defaults={
                'legal_name': 'CarbonView Demo Org Pvt Ltd',
                'industry_type': IndustryType.TECHNOLOGY,
                'reporting_boundary': OrganizationBoundary.OPERATIONAL_CONTROL,
                'base_currency': 'INR',
                'base_year': 2024,
                'resource': resource,
            }
        )
 
        facility, _ = Facility.objects.get_or_create(
            organization=org,
            name='Bengaluru Campus',
            defaults={
                'location': location,
                'facility_code': 'BLR-01',
                'description': 'Primary engineering and operations facility',
                'is_active': True,
            }
        )
 
        dept_ops, _ = Department.objects.get_or_create(facility=facility, name='Operations')
        dept_eng, _ = Department.objects.get_or_create(facility=facility, name='Engineering')
 
        reporting_period, _ = ReportingPeriod.objects.get_or_create(
            organization=org,
            year=2026,
            name='FY 2026',
            defaults={
                'start_date': date(2026, 1, 1),
                'end_date': date(2026, 12, 31),
                'is_closed': False,
            }
        )
 
        u_litre, _ = UnitOfMeasure.objects.get_or_create(code='litre', defaults={'name': 'Litre', 'symbol': 'L'})
        u_kwh, _ = UnitOfMeasure.objects.get_or_create(code='kwh', defaults={'name': 'Kilowatt hour', 'symbol': 'kWh'})
        u_kg, _ = UnitOfMeasure.objects.get_or_create(code='kg', defaults={'name': 'Kilogram', 'symbol': 'kg'})
        u_kl, _ = UnitOfMeasure.objects.get_or_create(code='kl', defaults={'name': 'Kilolitre', 'symbol': 'kL'})
 
        cat_fuel, _ = EmissionCategory.objects.get_or_create(
            code='stationary_fuel',
            defaults={'name': 'Stationary Fuel', 'scope': EmissionScope.SCOPE_1}
        )
        cat_electricity, _ = EmissionCategory.objects.get_or_create(
            code='purchased_electricity',
            defaults={'name': 'Purchased Electricity', 'scope': EmissionScope.SCOPE_2}
        )
        cat_waste, _ = EmissionCategory.objects.get_or_create(
            code='waste_generated',
            defaults={'name': 'Waste Generated in Operations', 'scope': EmissionScope.SCOPE_3}
        )
 
        s3_waste, _ = Scope3Category.objects.get_or_create(
            code='C5', defaults={'name': 'Waste generated in operations'}
        )
 
        co2, _ = GasType.objects.get_or_create(
            code='CO2', defaults={'gas_name': 'Carbon dioxide', 'gwp_value': Decimal('1.000000'), 'gwp_reference': 'IPCC AR6'}
        )
        ch4, _ = GasType.objects.get_or_create(
            code='CH4', defaults={'gas_name': 'Methane', 'gwp_value': Decimal('27.000000'), 'gwp_reference': 'IPCC AR6'}
        )
        n2o, _ = GasType.objects.get_or_create(
            code='N2O', defaults={'gas_name': 'Nitrous Oxide', 'gwp_value': Decimal('273.000000'), 'gwp_reference': 'IPCC AR6'}
        )
 
        factor_source, _ = EmissionFactorSource.objects.get_or_create(
            name='Demo Factor Library',
            version='2026.1',
            defaults={
                'publisher': 'CarbonView',
                'reference_url': 'https://example.com/factors',
            }
        )
 
        factor_rows = [
            (cat_fuel, None, co2, 'diesel_stationary', 'Diesel stationary CO2', Decimal('2.68000000'), u_litre, 'kg gas/unit', country),
            (cat_fuel, None, ch4, 'diesel_stationary', 'Diesel stationary CH4', Decimal('0.00010000'), u_litre, 'kg gas/unit', country),
            (cat_fuel, None, n2o, 'diesel_stationary', 'Diesel stationary N2O', Decimal('0.00012000'), u_litre, 'kg gas/unit', country),
            (cat_electricity, None, co2, 'grid_electricity_india', 'India grid electricity CO2', Decimal('0.70800000'), u_kwh, 'kg gas/unit', country),
            (cat_waste, s3_waste, co2, 'landfill_mixed_waste', 'Landfill mixed waste CO2', Decimal('0.12000000'), u_kg, 'kg gas/unit', country),
            (cat_waste, s3_waste, ch4, 'landfill_mixed_waste', 'Landfill mixed waste CH4', Decimal('0.00200000'), u_kg, 'kg gas/unit', country),
        ]
 
        for category, s3cat, gas, fcode, fname, fval, activity_unit, funit, geo in factor_rows:
            EmissionFactor.objects.get_or_create(
                source=factor_source,
                category=category,
                scope3_category=s3cat,
                gas_type=gas,
                factor_code=fcode,
                activity_unit=activity_unit,
                geography=geo,
                valid_from=date(2026, 1, 1),
                defaults={
                    'factor_name': fname,
                    'factor_value': fval,
                    'factor_unit': funit,
                    'is_active': True,
                }
            )
 
        activity_specs = [
            {
                'department': dept_ops,
                'category': cat_fuel,
                'scope3_category': None,
                'activity_name': 'DG backup diesel consumption',
                'activity_date': date(2026, 1, 15),
                'quantity': Decimal('850.000000'),
                'unit': u_litre,
                'factor_code': 'diesel_stationary',
                'scope2_method': Scope2Method.NOT_APPLICABLE,
                'data_quality': ActivityDataQuality.ACTUAL,
                'supplier_name': 'ABC Fuels',
                'invoice_number': 'INV-DG-1001',
            },
            {
                'department': dept_eng,
                'category': cat_electricity,
                'scope3_category': None,
                'activity_name': 'Grid electricity consumption',
                'activity_date': date(2026, 1, 31),
                'quantity': Decimal('12500.000000'),
                'unit': u_kwh,
                'factor_code': 'grid_electricity_india',
                'scope2_method': Scope2Method.LOCATION_BASED,
                'data_quality': ActivityDataQuality.ACTUAL,
                'supplier_name': 'BESCOM',
                'invoice_number': 'ELEC-JAN-2026',
            },
            {
                'department': dept_ops,
                'category': cat_waste,
                'scope3_category': s3_waste,
                'activity_name': 'Mixed waste to landfill',
                'activity_date': date(2026, 2, 5),
                'quantity': Decimal('420.000000'),
                'unit': u_kg,
                'factor_code': 'landfill_mixed_waste',
                'scope2_method': Scope2Method.NOT_APPLICABLE,
                'data_quality': ActivityDataQuality.ESTIMATED,
                'supplier_name': 'GreenCycle Services',
                'invoice_number': 'WST-204',
            },
        ]
 
        created_activities = []
        for spec in activity_specs:
            activity, created = EmissionActivity.objects.get_or_create(
                organization=org,
                facility=facility,
                reporting_period=reporting_period,
                activity_name=spec['activity_name'],
                activity_date=spec['activity_date'],
                defaults={
                    'department': spec['department'],
                    'category': spec['category'],
                    'scope3_category': spec['scope3_category'],
                    'quantity': spec['quantity'],
                    'unit': spec['unit'],
                    'factor_code': spec['factor_code'],
                    'scope2_method': spec['scope2_method'],
                    'data_quality': spec['data_quality'],
                    'supplier_name': spec['supplier_name'],
                    'invoice_number': spec['invoice_number'],
                    'source_reference': spec['invoice_number'],
                    'status': RecordStatus.APPROVED,
                    'entered_by': user,
                    'approved_by': user,
                    'approved_at': timezone.now(),
                    'notes': 'Seeded demo record',
                }
            )
            if not created:
                for field, value in {
                    'department': spec['department'],
                    'category': spec['category'],
                    'scope3_category': spec['scope3_category'],
                    'quantity': spec['quantity'],
                    'unit': spec['unit'],
                    'factor_code': spec['factor_code'],
                    'scope2_method': spec['scope2_method'],
                    'data_quality': spec['data_quality'],
                    'supplier_name': spec['supplier_name'],
                    'invoice_number': spec['invoice_number'],
                    'source_reference': spec['invoice_number'],
                    'status': RecordStatus.APPROVED,
                    'entered_by': user,
                    'approved_by': user,
                    'approved_at': timezone.now(),
                    'notes': 'Seeded demo record',
                }.items():
                    setattr(activity, field, value)
                activity.save()
            created_activities.append(activity)
            DataEvidence.objects.get_or_create(
                activity=activity,
                name=f"Evidence for {activity.activity_name}",
                defaults={
                    'document_number': activity.invoice_number,
                    'uploaded_by': user,
                }
            )
 
        EnergySummary.objects.get_or_create(
            facility=facility,
            reporting_period=reporting_period,
            defaults={
                'total_energy': Decimal('13500.0000'),
                'renewable_energy': Decimal('2500.0000'),
                'non_renewable_energy': Decimal('11000.0000'),
                'unit': u_kwh,
            }
        )
        WaterUsage.objects.get_or_create(
            facility=facility,
            reporting_period=reporting_period,
            category='Fresh water withdrawal',
            defaults={'amount': Decimal('180.2500'), 'unit': u_kl}
        )
        WasteSummary.objects.get_or_create(
            facility=facility,
            reporting_period=reporting_period,
            defaults={
                'total_waste': Decimal('1.8500'),
                'hazardous': Decimal('0.1200'),
                'non_hazardous': Decimal('1.7300'),
                'recycled_percentage': Decimal('46.50'),
                'unit': u_kg,
            }
        )
 
        CarbonCredit.objects.get_or_create(
            facility=facility,
            serial_number='VCS-2026-BLR-0001',
            defaults={
                'project_name': 'Wind Energy Portfolio',
                'source': 'Verified Carbon Standard',
                'registry_name': 'Verra',
                'vintage_year': 2025,
                'quantity_tco2e': Decimal('5.5000'),
                'purchase_date': date(2026, 2, 1),
                'retirement_date': date(2026, 3, 1),
                'status': 'retired',
            }
        )
        ReductionProject.objects.get_or_create(
            facility=facility,
            name='LED Retrofit Program',
            defaults={
                'description': 'Lighting retrofit across engineering floors',
                'start_date': date(2026, 1, 10),
                'expected_reduction_tco2e': Decimal('2.0000'),
                'actual_reduction_tco2e': Decimal('1.2500'),
            }
        )
 
        claim, _ = NeutralityClaim.objects.get_or_create(
            organization=org,
            facility=facility,
            reporting_period=reporting_period,
            name='Bengaluru Campus FY2026 Claim',
            defaults={'status': RecordStatus.DRAFT}
        )
        claim.save()
 
        monthly_totals = {}
        approved = EmissionActivity.objects.filter(
            organization=org,
            reporting_period=reporting_period,
            status=RecordStatus.APPROVED,
        )
        for activity in approved.select_related('category'):
            key = (activity.activity_date.year, activity.activity_date.month, activity.category.scope)
            monthly_totals[key] = monthly_totals.get(key, Decimal('0')) + activity.total_co2e
 
        for (year, month, scope), total in monthly_totals.items():
            MonthlyEmissionSummary.objects.update_or_create(
                organization=org,
                facility=facility,
                reporting_period=reporting_period,
                year=year,
                month=month,
                scope=scope,
                defaults={'total_co2e': total}
            )
 
        self.stdout.write(self.style.SUCCESS('Seed data created successfully.'))
        self.stdout.write(f'User: {user.username}')
        self.stdout.write(f'Organization: {org.name}')
        self.stdout.write(f'Facility: {facility.name}')
        self.stdout.write(f'Emission activities: {EmissionActivity.objects.filter(organization=org).count()}')
        self.stdout.write(f'Emission calculations: {EmissionCalculation.objects.filter(activity__organization=org).count()}')
        self.stdout.write(f'Neutrality claim net emissions: {claim.net_emissions}')


if __name__ == "__main__":
    command = Command()
    command.handle(username="carbonadmin", reset=False)
 
 
