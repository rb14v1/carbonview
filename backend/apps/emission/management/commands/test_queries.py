from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
 
from django.db import transaction, models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
 
from apps.shared.models import Resource, Country, State, City, Location
from apps.company.models import (
    Organization,
    Facility,
    Department,
    ReportingPeriod,
    IndustryType,
    OrganizationBoundary,
)
from apps.emission.models import (
    EmissionScope,
    Scope2Method,
    ActivityDataQuality,
    RecordStatus,
    EmissionCategory,
    Scope3Category,
    GasType,
    UnitOfMeasure,
    FuelType,
    EmissionFactorSource,
    EmissionFactor,
    EmissionActivity,
    EmissionBreakdown,
    DataEvidence,
    AirEmission,
)
from apps.summary.models import (
    AuditLog,
    MonthlyEmissionSummary,
    EnergySummary,
    WaterUsage,
    WasteSummary,
    NeutralityClaim,
    CarbonCredit,
    ReductionProject,
    Certificate,
)
 
D = Decimal
Q6 = Decimal("0.000001")
Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
 
ANNUAL_DASHBOARD = [
    {
        "year": 2020,
        "tak_s1_inventory": {
            "stationary_combustion": 14350,
            "mobile_combustion": 8610,
            "fugitive_emissions": 5740,
            "total": 28700,
        },
        "tak_s2_inventory": {
            "location_based": 33540,
            "market_based": 16770,
            "purchased_steam": 5590,
            "total": 55800,
        },
        "tak_s3_inventory": {
            "purchased_goods": 16240,
            "business_travel": 6670,
            "transportation": 5560,
            "waste": 8830,
            "total": 37300,
        },
    },
    {
        "year": 2021,
        "tak_s1_inventory": {
            "stationary_combustion": 13850,
            "mobile_combustion": 8310,
            "fugitive_emissions": 5540,
            "total": 27700,
        },
        "tak_s2_inventory": {
            "location_based": 32100,
            "market_based": 14700,
            "purchased_steam": 5350,
            "total": 52150,
        },
        "tak_s3_inventory": {
            "purchased_goods": 15720,
            "business_travel": 5330,
            "transportation": 5390,
            "waste": 8560,
            "total": 35000,
        },
    },
    {
        "year": 2022,
        "tak_s1_inventory": {
            "stationary_combustion": 13400,
            "mobile_combustion": 8040,
            "fugitive_emissions": 5360,
            "total": 26800,
        },
        "tak_s2_inventory": {
            "location_based": 30600,
            "market_based": 12600,
            "purchased_steam": 5100,
            "total": 48300,
        },
        "tak_s3_inventory": {
            "purchased_goods": 15260,
            "business_travel": 5760,
            "transportation": 5180,
            "waste": 8200,
            "total": 34400,
        },
    },
    {
        "year": 2023,
        "tak_s1_inventory": {
            "stationary_combustion": 12950,
            "mobile_combustion": 7770,
            "fugitive_emissions": 5180,
            "total": 25900,
        },
        "tak_s2_inventory": {
            "location_based": 29100,
            "market_based": 10200,
            "purchased_steam": 4850,
            "total": 44150,
        },
        "tak_s3_inventory": {
            "purchased_goods": 14720,
            "business_travel": 5460,
            "transportation": 4970,
            "waste": 7850,
            "total": 33000,
        },
    },
    {
        "year": 2024,
        "tak_s1_inventory": {
            "stationary_combustion": 12450,
            "mobile_combustion": 7470,
            "fugitive_emissions": 4980,
            "total": 24900,
        },
        "tak_s2_inventory": {
            "location_based": 27600,
            "market_based": 8100,
            "purchased_steam": 4600,
            "total": 40300,
        },
        "tak_s3_inventory": {
            "purchased_goods": 14210,
            "business_travel": 5190,
            "transportation": 4790,
            "waste": 7610,
            "total": 31800,
        },
    },
    {
        "year": 2025,
        "tak_s1_inventory": {
            "stationary_combustion": 11950,
            "mobile_combustion": 7170,
            "fugitive_emissions": 4780,
            "total": 23900,
        },
        "tak_s2_inventory": {
            "location_based": 25800,
            "market_based": 6300,
            "purchased_steam": 4300,
            "total": 36400,
        },
        "tak_s3_inventory": {
            "purchased_goods": 13620,
            "business_travel": 4930,
            "transportation": 4590,
            "waste": 7360,
            "total": 30500,
        },
    },
    {
        "year": 2026,
        "tak_s1_inventory": {
            "stationary_combustion": 11550,
            "mobile_combustion": 6930,
            "fugitive_emissions": 4620,
            "total": 23100,
        },
        "tak_s2_inventory": {
            "location_based": 24120,
            "market_based": 4920,
            "purchased_steam": 4020,
            "total": 33060,
        },
        "tak_s3_inventory": {
            "purchased_goods": 13020,
            "business_travel": 4710,
            "transportation": 4350,
            "waste": 6960,
            "total": 29040,
        },
    },
]
 
CATEGORY_BLUEPRINT = {
    "S1": {
        "name": "Direct emissions",
        "scope": EmissionScope.SCOPE_1,
        "children": {
            "stationary_combustion": "Stationary combustion",
            "mobile_combustion": "Mobile combustion",
            "fugitive_emissions": "Fugitive emissions",
        },
    },
    "S2": {
        "name": "Purchased energy",
        "scope": EmissionScope.SCOPE_2,
        "children": {
            "location_based": "Location-based electricity",
            "market_based": "Market-based electricity",
            "purchased_steam": "Purchased steam",
        },
    },
    "S3": {
        "name": "Value chain emissions",
        "scope": EmissionScope.SCOPE_3,
        "children": {
            "purchased_goods": "Purchased goods",
            "business_travel": "Business travel",
            "transportation": "Transportation and distribution",
            "waste": "Waste generated in operations",
        },
    },
}
 
SCOPE3_BLUEPRINT = {
    "purchased_goods": ("C1", "Purchased goods and services", 1),
    "business_travel": ("C6", "Business travel", 6),
    "transportation": ("C4", "Upstream transportation and distribution", 4),
    "waste": ("C5", "Waste generated in operations", 5),
}
 
ACTIVITY_META = {
    "stationary_combustion": {
        "scope": EmissionScope.SCOPE_1,
        "activity_name": "Stationary combustion - boilers and backup generators",
        "factor_code": "S1-STATIONARY-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Global Pharma Utilities",
        "invoice_number": "STAT-COMB",
        "source_reference": "Boiler fuel logs and diesel generator runtime records",
        "notes": "Includes natural gas boilers and diesel standby generators at pharma manufacturing sites.",
    },
    "mobile_combustion": {
        "scope": EmissionScope.SCOPE_1,
        "activity_name": "Mobile combustion - company fleet vehicles",
        "factor_code": "S1-MOBILE-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Global Fleet Services",
        "invoice_number": "MOB-FLEET",
        "source_reference": "Fleet fuel cards and mileage logs",
        "notes": "Includes sales fleet, medical outreach vehicles, and internal logistics vans.",
    },
    "fugitive_emissions": {
        "scope": EmissionScope.SCOPE_1,
        "activity_name": "Fugitive emissions - HVAC, refrigeration, cold storage leakage",
        "factor_code": "S1-FUGITIVE-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ESTIMATED,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Cold Chain Refrigeration Partners",
        "invoice_number": "FUG-HVAC",
        "source_reference": "Refrigerant top-up logs, maintenance records, and loss assumptions",
        "notes": "Material source for pharma due to laboratory refrigeration, cleanroom HVAC, and cold storage systems.",
    },
    "location_based": {
        "scope": EmissionScope.SCOPE_2,
        "activity_name": "Purchased electricity - location based",
        "factor_code": "S2-LOC-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.LOCATION_BASED,
        "supplier_name": "Regional Grid Utilities",
        "invoice_number": "ELEC-LOC",
        "source_reference": "Grid electricity consumption with regional grid factors",
        "notes": "Represents electricity emissions using grid-average location-based accounting.",
    },
    "market_based": {
        "scope": EmissionScope.SCOPE_2,
        "activity_name": "Purchased electricity - market based",
        "factor_code": "S2-MKT-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.SUPPLIER_SPECIFIC,
        "scope2_method": Scope2Method.MARKET_BASED,
        "supplier_name": "Renewable Power Portfolio",
        "invoice_number": "ELEC-MKT",
        "source_reference": "Supplier-specific residual mix and renewable procurement instruments",
        "notes": "Decreases faster over time due to increased renewable contracts and EAC/REC procurement.",
    },
    "purchased_steam": {
        "scope": EmissionScope.SCOPE_2,
        "activity_name": "Purchased steam - pharma manufacturing utilities",
        "factor_code": "S2-STEAM-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.LOCATION_BASED,
        "supplier_name": "Industrial Steam Services",
        "invoice_number": "STEAM-PROC",
        "source_reference": "Purchased steam utility bills for sterilization and process heating",
        "notes": "Steam used in sterilization, process heat, and controlled manufacturing environments.",
    },
    "purchased_goods": {
        "scope": EmissionScope.SCOPE_3,
        "activity_name": "Purchased goods - APIs, chemicals, packaging materials",
        "factor_code": "S3-PG-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.SPEND_BASED,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Global API and Packaging Suppliers",
        "invoice_number": "S3-PG",
        "source_reference": "Procurement ledger and supplier mix for pharmaceutical inputs",
        "notes": "Largest Scope 3 source driven by API synthesis, chemicals, and packaging materials.",
    },
    "business_travel": {
        "scope": EmissionScope.SCOPE_3,
        "activity_name": "Business travel - domestic and international aviation",
        "factor_code": "S3-BT-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Corporate Travel Desk",
        "invoice_number": "S3-BT",
        "source_reference": "Travel booking records for employee air travel",
        "notes": "Includes domestic flights, international flights, and limited rail substitution.",
    },
    "transportation": {
        "scope": EmissionScope.SCOPE_3,
        "activity_name": "Transportation - cold-chain logistics and medicine distribution",
        "factor_code": "S3-TRANS-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ESTIMATED,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Third-Party Cold Chain Logistics Providers",
        "invoice_number": "S3-LOG",
        "source_reference": "Freight records for air, sea, road, and refrigerated transport",
        "notes": "Includes third-party distribution, cold-chain logistics, and product shipping.",
    },
    "waste": {
        "scope": EmissionScope.SCOPE_3,
        "activity_name": "Waste - hazardous pharma waste, chemical disposal, incineration",
        "factor_code": "S3-WASTE-TCO2E",
        "unit_code": "tco2e",
        "quality": ActivityDataQuality.ACTUAL,
        "scope2_method": Scope2Method.NOT_APPLICABLE,
        "supplier_name": "Hazardous Waste Processors",
        "invoice_number": "S3-WASTE",
        "source_reference": "Waste manifests, hazardous disposal contracts, and incineration logs",
        "notes": "Includes hazardous waste treatment, solvent disposal, and regulated incineration.",
    },
}

FUEL_TYPE_BLUEPRINT = {
    "stationary_combustion": {
        "code": "NATURAL_GAS",
        "name": "Natural Gas",
        "description": "Primary boiler and process-heat fuel used across Takeda Ireland manufacturing operations.",
        "default_unit_code": "m3",
    },
    "mobile_combustion": {
        "code": "DIESEL",
        "name": "Diesel",
        "description": "Fleet and on-site logistics fuel used by Takeda Ireland operational vehicles.",
        "default_unit_code": "litre",
    },
    "fugitive_emissions": {
        "code": "R134A",
        "name": "R-134a Refrigerant",
        "description": "Representative refrigerant used for synthetic fugitive-emission seed records.",
        "default_unit_code": "kg",
    },
}
 
MONTH_WEIGHTS = [
    D("0.072"), D("0.074"), D("0.079"), D("0.082"), D("0.084"), D("0.086"),
    D("0.087"), D("0.086"), D("0.085"), D("0.084"), D("0.091"), D("0.090"),
]

SEED_START_YEAR = 2022
SEED_END_YEAR = 2026
PARTIAL_END_YEAR = 2026
PARTIAL_END_MONTH = 3
IRELAND_COUNTRY_CODE = "IE"
 
 
def quantize(value, places=Q6):
    return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)
 
 
def field_decimal_places(model_cls, field_name, default=6):
    field = model_cls._meta.get_field(field_name)
    return getattr(field, "decimal_places", default) or default
 
 
def field_quantizer(model_cls, field_name, default=6):
    places = field_decimal_places(model_cls, field_name, default)
    return Decimal("1").scaleb(-places)
 
 
def quantize_for_field(value, model_cls, field_name, default=6):
    q = field_quantizer(model_cls, field_name, default)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def seed_dashboard_rows():
    return [row for row in ANNUAL_DASHBOARD if SEED_START_YEAR <= row["year"] <= SEED_END_YEAR]


def months_in_year(year):
    return PARTIAL_END_MONTH if year == PARTIAL_END_YEAR else 12


def scaled_for_period(value, year):
    months = months_in_year(year)
    if months == 12:
        return D(str(value))
    return (D(str(value)) * D(str(months)) / D("12")).quantize(Q6, rounding=ROUND_HALF_UP)
 
 
def first_active_user(username=None):
    User = get_user_model()
    qs = User.objects.filter(is_active=True).order_by("id")
    if username:
        qs = qs.filter(username=username)
    user = qs.first()
    if user:
        return user

    fallback_username = username or "takeda_ireland_seed"
    user, created = User.objects.get_or_create(
        username=fallback_username,
        defaults={
            "email": f"{fallback_username}@example.com",
            "is_active": True,
            "is_staff": True,
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user
 
 
def normalize_dashboard_totals():
    for row in ANNUAL_DASHBOARD:
        s1 = row["tak_s1_inventory"]
        s2 = row["tak_s2_inventory"]
        s3 = row["tak_s3_inventory"]
 
        s1["total"] = s1["stationary_combustion"] + s1["mobile_combustion"] + s1["fugitive_emissions"]
        s2["total"] = s2["location_based"] + s2["market_based"] + s2["purchased_steam"]
        s3["total"] = s3["purchased_goods"] + s3["business_travel"] + s3["transportation"] + s3["waste"]
 
 
def get_or_create_geo():
    resource, _ = Resource.objects.get_or_create(
        name="Takeda Ireland ESG Data Source",
        defaults={
            "url": "https://www.takeda.com/who-we-are/company-information/worldwide-offices/europe/ireland/",
            "description": "Synthetic but realistic Takeda Ireland emissions and operations seed data for January 2022 to March 2026.",
        },
    )
    if resource.url != "https://www.takeda.com/who-we-are/company-information/worldwide-offices/europe/ireland/":
        resource.url = "https://www.takeda.com/who-we-are/company-information/worldwide-offices/europe/ireland/"
        resource.description = "Synthetic but realistic Takeda Ireland emissions and operations seed data for January 2022 to March 2026."
        resource.save(update_fields=["url", "description"])
 
    locations = {}
    geo_rows = [
        (IRELAND_COUNTRY_CODE, "Ireland", "County Dublin", "D", "Dublin", "Grange Castle Business Park, Dublin", "D22", D("53.338198"), D("-6.443401")),
        (IRELAND_COUNTRY_CODE, "Ireland", "County Wicklow", "WW", "Bray", "Finisklin Industrial Estate, Bray", "A98", D("53.202778"), D("-6.098889")),
        (IRELAND_COUNTRY_CODE, "Ireland", "County Cork", "CO", "Cork", "Little Island Logistics Campus, Cork", "T45", D("51.901493"), D("-8.366221")),
    ]
 
    for c_code, c_name, s_name, s_code, city_name, street, postal, latitude, longitude in geo_rows:
        country, _ = Country.objects.get_or_create(code=c_code, defaults={"name": c_name})
        if country.name != c_name:
            country.name = c_name
            country.save(update_fields=["name"])
 
        state, _ = State.objects.get_or_create(country=country, name=s_name, defaults={"code": s_code})
        if s_code and getattr(state, "code", None) != s_code:
            state.code = s_code
            state.save(update_fields=["code"])
 
        city, _ = City.objects.get_or_create(state=state, name=city_name)
        location, _ = Location.objects.get_or_create(
            country=country,
            state=state,
            city=city,
            street_address=street,
            postal_code=postal,
        )
        location.latitude = latitude
        location.longitude = longitude
        location.save(update_fields=["latitude", "longitude"])
        locations[city_name] = location
 
    return resource, locations
 
 
def get_or_create_org_and_facilities(resource):
    org, _ = Organization.objects.get_or_create(
        name="Takeda Pharmaceutical Company Limited - Ireland",
        defaults={
            "legal_name": "Takeda Pharmaceutical Company Limited - Ireland Operations",
            "industry_type": IndustryType.HEALTHCARE,
            "reporting_boundary": OrganizationBoundary.OPERATIONAL_CONTROL,
            "base_currency": "EUR",
            "base_year": SEED_START_YEAR,
            "resource": resource,
        },
    )
 
    if not org.resource_id:
        org.resource = resource
        org.save(update_fields=["resource"])
 
    _, locations = get_or_create_geo()
 
    facility_specs = [
        ("DUB-BIO", "Dublin Biologics Manufacturing Campus", locations["Dublin"], "Large-scale biologics manufacturing, cleanroom operations, and controlled-temperature warehousing."),
        ("BRY-PKG", "Bray Packaging and Device Assembly Centre", locations["Bray"], "Secondary packaging, device assembly, QA release, and engineering utilities."),
        ("CRK-HUB", "Cork Distribution and Cold Chain Hub", locations["Cork"], "Ireland distribution, cold-chain logistics, and outbound product staging."),
    ]
 
    facilities = []
    for code, name, location, description in facility_specs:
        facility, _ = Facility.objects.get_or_create(
            organization=org,
            name=name,
            defaults={
                "facility_code": code,
                "location": location,
                "description": description,
                "is_active": True,
                "is_carbon_neutral": False,
            },
        )
        changed = False
        if facility.location_id != location.id:
            facility.location = location
            changed = True
        if getattr(facility, "facility_code", None) != code:
            facility.facility_code = code
            changed = True
        if getattr(facility, "description", None) != description:
            facility.description = description
            changed = True
        if changed:
            facility.save()
        facilities.append(facility)
 
    department_names = [
        "Manufacturing Operations",
        "Quality and Compliance",
        "Supply Chain and Logistics",
        "Engineering Utilities",
        "Corporate Services",
    ]
    for facility in facilities:
        for dept_name in department_names:
            Department.objects.get_or_create(facility=facility, name=dept_name)
 
    return org, facilities
 
 
def create_reporting_periods(org):
    periods = {}
    for year in range(SEED_START_YEAR, SEED_END_YEAR + 1):
        period_end_month = months_in_year(year)
        period_end_day = monthrange(year, period_end_month)[1]
        period, _ = ReportingPeriod.objects.get_or_create(
            organization=org,
            year=year,
            name=f"FY{year}",
            defaults={
                "start_date": date(year, 1, 1),
                "end_date": date(year, period_end_month, period_end_day),
                "is_closed": year < PARTIAL_END_YEAR,
            },
        )
        desired_end_date = date(year, period_end_month, period_end_day)
        if period.end_date != desired_end_date or period.start_date != date(year, 1, 1) or period.is_closed != (year < PARTIAL_END_YEAR):
            period.start_date = date(year, 1, 1)
            period.end_date = desired_end_date
            period.is_closed = year < PARTIAL_END_YEAR
            period.save(update_fields=["start_date", "end_date", "is_closed"])
        periods[year] = period
    return periods
 
 
def get_or_create_units():
    rows = [
        ("tco2e", "Tonnes carbon dioxide equivalent", "tCO2e"),
        ("mwh", "Megawatt hour", "MWh"),
        ("m3", "Cubic metre", "m3"),
        ("tonne", "Metric tonne", "t"),
        ("litre", "Litre", "L"),
        ("kg", "Kilogram", "kg"),
    ]
    units = {}
    for code, name, symbol in rows:
        unit, _ = UnitOfMeasure.objects.get_or_create(code=code, defaults={"name": name, "symbol": symbol})
        changed = False
        if unit.name != name:
            unit.name = name
            changed = True
        if unit.symbol != symbol:
            unit.symbol = symbol
            changed = True
        if changed:
            unit.save(update_fields=["name", "symbol"])
        units[code] = unit
    return units
 
 
def get_or_create_gases():
    gas_rows = [
        ("CO2", "Carbon dioxide", D("1.0"), "IPCC AR6"),
        ("CH4", "Methane", D("27.0"), "IPCC AR6"),
        ("N2O", "Nitrous oxide", D("273.0"), "IPCC AR6"),
        ("HFC", "Hydrofluorocarbons", D("1430.0"), "IPCC AR6 representative refrigerant blend"),
    ]
    gases = {}
    for code, gas_name, gwp, ref in gas_rows:
        gas, _ = GasType.objects.get_or_create(
            code=code,
            defaults={"gas_name": gas_name, "gwp_value": gwp, "gwp_reference": ref},
        )
        gases[code] = gas
    return gases


def get_or_create_fuel_types(units):
    fuel_types = {}
    for label, cfg in FUEL_TYPE_BLUEPRINT.items():
        fuel_type, _ = FuelType.objects.get_or_create(
            code=cfg["code"],
            defaults={
                "name": cfg["name"],
                "description": cfg["description"],
                "default_unit": units[cfg["default_unit_code"]],
            },
        )
        changed = False
        if fuel_type.name != cfg["name"]:
            fuel_type.name = cfg["name"]
            changed = True
        if fuel_type.description != cfg["description"]:
            fuel_type.description = cfg["description"]
            changed = True
        if fuel_type.default_unit_id != units[cfg["default_unit_code"]].id:
            fuel_type.default_unit = units[cfg["default_unit_code"]]
            changed = True
        if changed:
            fuel_type.save(update_fields=["name", "description", "default_unit"])
        fuel_types[label] = fuel_type
    return fuel_types
 
 
def get_or_create_factor_source():
    source, _ = EmissionFactorSource.objects.get_or_create(
        name="Takeda Ireland Synthetic Seed Factors",
        version="2026.3",
        defaults={
            "publisher": "CarbonView Seed Generator",
            "published_on": date(2026, 3, 31),
            "reference_url": "https://example.com/factors/takeda-ireland-seed",
        },
    )
    return source
 
 
def get_or_create_categories():
    categories = {}
    scope_nodes = {}
 
    for code, cfg in CATEGORY_BLUEPRINT.items():
        scope_node, _ = EmissionCategory.objects.get_or_create(
            code=code,
            defaults={
                "name": cfg["name"],
                "scope": cfg["scope"],
                "category_type": "scope",
                "description": f"Top level node for {cfg['name']}",
            },
        )
        scope_nodes[code] = scope_node
 
    for scope_code, cfg in CATEGORY_BLUEPRINT.items():
        category_code = f"{scope_code}-CAT"
        parent = scope_nodes[scope_code]
        category, _ = EmissionCategory.objects.get_or_create(
            code=category_code,
            defaults={
                "name": cfg["name"],
                "scope": cfg["scope"],
                "parent": parent,
                "category_type": "category",
                "description": f"Category bucket for {cfg['name']}",
            },
        )
        categories[scope_code] = category
 
        for key, name in cfg["children"].items():
            sub_code = f"{scope_code}-{key}".upper().replace("_", "-")[:30]
            subcategory, _ = EmissionCategory.objects.get_or_create(
                code=sub_code,
                defaults={
                    "name": name,
                    "scope": cfg["scope"],
                    "parent": category,
                    "category_type": "subcategory",
                    "description": name,
                },
            )
            categories[key] = subcategory
 
    return categories
 
 
def get_or_create_scope3_categories():
    result = {}
    for key, (code, name, num) in SCOPE3_BLUEPRINT.items():
        obj, _ = Scope3Category.objects.get_or_create(
            code=code,
            defaults={"name": name, "description": f"Scope 3 category {num}: {name}"},
        )
        result[key] = obj
    return result
 
 
def activity_factor_code(label, fuel_type=None):
    base_code = ACTIVITY_META[label]["factor_code"]
    if fuel_type:
        return f"{base_code}-{fuel_type.code}"
    return base_code


def monthly_activity_date(year, month):
    return date(year, month, min(15, monthrange(year, month)[1]))


def create_emission_factors(categories, scope3_map, units, gases, source, geography, fuel_types):
    factor_specs = [
        ("stationary_combustion", "CO2", D("1.00000000")),
        ("mobile_combustion", "CO2", D("1.00000000")),
        ("fugitive_emissions", "HFC", D("1.00000000") / gases["HFC"].gwp_value),
        ("location_based", "CO2", D("1.00000000")),
        ("market_based", "CO2", D("1.00000000")),
        ("purchased_steam", "CO2", D("1.00000000")),
        ("purchased_goods", "CO2", D("1.00000000")),
        ("business_travel", "CO2", D("1.00000000")),
        ("transportation", "CO2", D("1.00000000")),
        ("waste", "CH4", D("1.00000000") / gases["CH4"].gwp_value),
    ]
    factors = {}
    for key, gas_code, factor_value in factor_specs:
        meta = ACTIVITY_META[key]
        fuel_type = fuel_types.get(key)
        factor_code = activity_factor_code(key, fuel_type)
        factor_name = meta["activity_name"] if not fuel_type else f"{meta['activity_name']} ({fuel_type.name})"
        factor, _ = EmissionFactor.objects.get_or_create(
            source=source,
            category=categories[key],
            scope3_category=scope3_map.get(key),
            gas_type=gases[gas_code],
            fuel_type=fuel_type,
            factor_code=factor_code,
            activity_unit=units[meta["unit_code"]],
            geography=geography,
            valid_from=date(SEED_START_YEAR, 1, 1),
            defaults={
                "factor_name": factor_name,
                "factor_value": quantize(factor_value, Decimal("0.00000001")),
                "factor_unit": "tCO2e-per-unit synthetic factor",
                "valid_to": date(SEED_END_YEAR, 12, 31),
                "is_active": True,
            },
        )
        factor.fuel_type = fuel_type
        factor.factor_name = factor_name
        factor.factor_value = quantize(factor_value, Decimal("0.00000001"))
        factor.factor_unit = "tCO2e-per-unit synthetic factor"
        factor.valid_to = date(SEED_END_YEAR, 12, 31)
        factor.is_active = True
        factor.geography = geography
        factor.save(update_fields=["fuel_type", "factor_name", "factor_value", "factor_unit", "valid_to", "is_active", "geography"])
        factors[key] = factor
    return factors
 
 
def allocate_to_facilities(total, weights):
    total = D(str(total))
    parts = []
    for weight in weights[:-1]:
        parts.append((total * weight).quantize(Q6, rounding=ROUND_HALF_UP))
    parts.append((total - sum(parts)).quantize(Q6, rounding=ROUND_HALF_UP))
    return parts
 
 
def monthly_split(total, months_count=12):
    total = D(str(total))
    weights = MONTH_WEIGHTS[:months_count]
    weight_total = sum(weights)
    normalized_weights = [weight / weight_total for weight in weights]
    values = []
    for weight in normalized_weights[:-1]:
        values.append((total * weight).quantize(Q6, rounding=ROUND_HALF_UP))
    values.append((total - sum(values)).quantize(Q6, rounding=ROUND_HALF_UP))
    return values
 
 
def pick_department(facility, label):
    name_map = {
        "stationary_combustion": "Engineering Utilities",
        "mobile_combustion": "Corporate Services",
        "fugitive_emissions": "Engineering Utilities",
        "location_based": "Engineering Utilities",
        "market_based": "Engineering Utilities",
        "purchased_steam": "Manufacturing Operations",
        "purchased_goods": "Supply Chain and Logistics",
        "business_travel": "Corporate Services",
        "transportation": "Supply Chain and Logistics",
        "waste": "Quality and Compliance",
    }
    return Department.objects.get(facility=facility, name=name_map[label])
 
 
def create_or_update_activity(
    org,
    facility,
    department,
    period,
    category,
    scope3_category,
    unit,
    user,
    year,
    month,
    label,
    amount,
    fuel_type=None,
):
    meta = ACTIVITY_META[label]
    activity_date = monthly_activity_date(year, month)

    quantity_value = quantize_for_field(amount, EmissionActivity, "quantity")
    total_co2e_value = quantize_for_field(amount, EmissionActivity, "total_co2e")
    factor_code = activity_factor_code(label, fuel_type)

    defaults = {
        "department": department,
        "category": category,
        "scope3_category": scope3_category,
        "quantity": quantity_value,
        "unit": unit,
        "factor_code": factor_code,
        "scope2_method": meta["scope2_method"],
        "data_quality": meta["quality"],
        "fuel_type": fuel_type,
        "supplier_name": meta["supplier_name"],
        "invoice_number": f"{meta['invoice_number']}-{facility.facility_code}-{year}-{month:02d}",
        "source_reference": meta["source_reference"],
        "notes": meta["notes"],
        "total_co2e": total_co2e_value,
        "status": RecordStatus.APPROVED,
        "approved_at": timezone.now(),
    }
 
    activity_fields = {f.name for f in EmissionActivity._meta.get_fields()}
 
    if "entered_by" in activity_fields:
        defaults["entered_by"] = user
    if "approved_by" in activity_fields:
        defaults["approved_by"] = user
 
    obj = EmissionActivity.objects.filter(
        organization=org,
        facility=facility,
        reporting_period=period,
        activity_name=meta["activity_name"],
        activity_date=activity_date,
    ).first()
    created = obj is None
    if created:
        obj = EmissionActivity(
            organization=org,
            facility=facility,
            reporting_period=period,
            activity_name=meta["activity_name"],
            activity_date=activity_date,
        )

    for field_name, field_value in defaults.items():
        setattr(obj, field_name, field_value)

    obj._needs_recalc = True
    obj.save()
    return obj, created
 
 
def rebuild_breakdowns(org, period):
    EmissionBreakdown.objects.filter(organization=org, reporting_period=period).delete()
 
    activities = EmissionActivity.objects.filter(
        organization=org,
        reporting_period=period,
        status=RecordStatus.APPROVED,
    ).select_related("facility", "category", "scope3_category", "fuel_type").prefetch_related("calculations__gas_type")

    grouped = {}
    for activity in activities:
        parent, sub = activity.get_category_hierarchy()
        first_calculation = activity.calculations.first()
        gas_type = first_calculation.gas_type if first_calculation else None
        for facility in (activity.facility, None):
            key = (
                facility.id if facility else None,
                activity.category.scope,
                parent.id if parent else activity.category.id,
                sub.id if sub else None,
                activity.scope3_category_id,
                gas_type.id if gas_type else None,
                activity.fuel_type_id,
            )
            if key not in grouped:
                grouped[key] = {
                    "facility": facility,
                    "scope": activity.category.scope,
                    "category": parent if parent else activity.category,
                    "subcategory": sub,
                    "scope3_category": activity.scope3_category,
                    "gas_type": gas_type,
                    "fuel_type": activity.fuel_type,
                    "total_co2e": D("0"),
                    "total_quantity": D("0"),
                }
            grouped[key]["total_co2e"] += activity.total_co2e
            grouped[key]["total_quantity"] += activity.quantity

    for payload in grouped.values():
        EmissionBreakdown.objects.create(
            organization=org,
            facility=payload["facility"],
            reporting_period=period,
            scope=payload["scope"],
            category=payload["category"],
            subcategory=payload["subcategory"],
            scope3_category=payload["scope3_category"],
            gas_type=payload["gas_type"],
            fuel_type=payload["fuel_type"],
            total_co2e=payload["total_co2e"],
            total_quantity=payload["total_quantity"],
        )
 
 
def rebuild_monthly_summaries(org, facilities, period):
    MonthlyEmissionSummary.objects.filter(organization=org, reporting_period=period).delete()
    months_count = months_in_year(period.year)
    scopes = [
        EmissionScope.SCOPE_1,
        EmissionScope.SCOPE_2,
        EmissionScope.SCOPE_3,
    ]
    monthly_totals = {}

    activities = EmissionActivity.objects.filter(
        organization=org,
        reporting_period=period,
        status=RecordStatus.APPROVED,
    ).select_related("category", "facility")

    for activity in activities:
        scope = activity.category.scope
        month = activity.activity_date.month
        facility_key = (activity.facility_id, month, scope)
        org_key = (None, month, scope)
        monthly_totals[facility_key] = monthly_totals.get(facility_key, D("0")) + activity.total_co2e
        monthly_totals[org_key] = monthly_totals.get(org_key, D("0")) + activity.total_co2e

    for facility in [*facilities, None]:
        facility_id = facility.id if facility else None
        for scope in scopes:
            for month in range(1, months_count + 1):
                amount = monthly_totals.get((facility_id, month, scope), D("0"))
                MonthlyEmissionSummary.objects.create(
                    organization=org,
                    facility=facility,
                    reporting_period=period,
                    year=period.year,
                    month=month,
                    scope=scope,
                    total_co2e=quantize_for_field(amount, MonthlyEmissionSummary, "total_co2e"),
                )
 
 
def rebuild_operational_summaries(facilities, periods, units):
    mwh_unit = units["mwh"]
    m3_unit = units["m3"]
    tonne_unit = units["tonne"]
 
    for row in seed_dashboard_rows():
        year = row["year"]
        period = periods[year]
        scope2_total = scaled_for_period(row["tak_s2_inventory"]["total"], year)
        waste_total = scaled_for_period(row["tak_s3_inventory"]["waste"], year)
 
        facility_weights = [D("0.34"), D("0.46"), D("0.20")]
        energy_parts = allocate_to_facilities(scope2_total * D("14.2"), facility_weights)
 
        renewable_ratio = D("0.22") + D(str(year - SEED_START_YEAR)) * D("0.06")
        if renewable_ratio > D("0.70"):
            renewable_ratio = D("0.70")

        water_total = D("640000") - D(str(year - SEED_START_YEAR)) * D("18000")
        water_total = scaled_for_period(water_total, year)
        water_parts = allocate_to_facilities(water_total, facility_weights)
        waste_parts = allocate_to_facilities(waste_total * D("0.135"), facility_weights)
 
        for idx, facility in enumerate(facilities):
            total_energy = quantize(energy_parts[idx], Q4)
            renewable_energy = quantize(total_energy * renewable_ratio, Q4)
            non_renewable_energy = quantize(total_energy - renewable_energy, Q4)
 
            EnergySummary.objects.update_or_create(
                facility=facility,
                reporting_period=period,
                defaults={
                    "total_energy": total_energy,
                    "renewable_energy": renewable_energy,
                    "non_renewable_energy": non_renewable_energy,
                    "unit": mwh_unit,
                },
            )
 
            WaterUsage.objects.update_or_create(
                facility=facility,
                reporting_period=period,
                category="withdrawal",
                defaults={"amount": quantize(water_parts[idx], Q4), "unit": m3_unit},
            )
 
            total_waste = quantize(waste_parts[idx], Q4)
            hazardous = quantize(total_waste * D("0.72"), Q4)
            non_hazardous = quantize(total_waste - hazardous, Q4)
            recycled_percentage = quantize(D("18.00") + D(str(year - 2020)) * D("2.50"), Q2)
 
            WasteSummary.objects.update_or_create(
                facility=facility,
                reporting_period=period,
                defaults={
                    "total_waste": total_waste,
                    "hazardous": hazardous,
                    "non_hazardous": non_hazardous,
                    "recycled_percentage": recycled_percentage,
                    "unit": tonne_unit,
                },
            )
 
 
def rebuild_reductions_and_credits(facilities, periods):
    for year, period in periods.items():
        for idx, facility in enumerate(facilities, start=1):
            expected = quantize(D("280") + D(str(year - SEED_START_YEAR)) * D(str(48 * idx)), Q4)
            expected = quantize(scaled_for_period(expected, year), Q4)
            actual = quantize(expected * D("0.78"), Q4)
 
            ReductionProject.objects.update_or_create(
                facility=facility,
                name=f"Efficiency Program {year} - {facility.facility_code}",
                defaults={
                    "description": "Takeda Ireland energy efficiency, HVAC optimization, and process improvement program.",
                    "start_date": date(year, 2, 1),
                    "end_date": period.end_date,
                    "expected_reduction_tco2e": expected,
                    "actual_reduction_tco2e": actual,
                },
            )
 
            if year >= 2024:
                qty = quantize(D("140") + D(str(idx * 32)) + D(str((year - 2024) * 40)), Q4)
                qty = quantize(scaled_for_period(qty, year), Q4)
                CarbonCredit.objects.update_or_create(
                    serial_number=f"CC-{facility.facility_code}-{year}",
                    defaults={
                        "facility": facility,
                        "project_name": f"Takeda Ireland Renewable and Nature Credit Portfolio {year}",
                        "source": "Portfolio purchase - Ireland operations",
                        "registry_name": "Verified Carbon Standard",
                        "vintage_year": year,
                        "quantity_tco2e": qty,
                        "purchase_date": date(year, min(3, period.end_date.month), min(28, period.end_date.day)),
                        "retirement_date": period.end_date,
                        "status": "retired",
                    },
                )
 
 
def rebuild_neutrality_claims(org, facilities, periods):
    for year, period in periods.items():
        NeutralityClaim.objects.update_or_create(
            organization=org,
            facility=None,
            reporting_period=period,
            name=f"Takeda Ireland neutrality ledger FY{year}",
            defaults={
                "status": RecordStatus.APPROVED,
                "notes": "Organization-level claim generated from approved Takeda Ireland emissions, reductions, and retired credits.",
            },
        )
        for facility in facilities:
            NeutralityClaim.objects.update_or_create(
                organization=org,
                facility=facility,
                reporting_period=period,
                name=f"{facility.facility_code} neutrality ledger FY{year}",
                defaults={
                    "status": RecordStatus.APPROVED,
                    "notes": "Facility-level claim generated from approved Takeda Ireland emissions, reductions, and retired credits.",
                },
            )


def rebuild_data_evidence(org, user):
    DataEvidence.objects.filter(activity__organization=org).delete()
    for activity in EmissionActivity.objects.filter(organization=org).order_by("reporting_period_id", "facility_id", "activity_name"):
        month_code = f"{activity.activity_date.month:02d}"
        DataEvidence.objects.create(
            activity=activity,
            name=f"{activity.activity_name} evidence {activity.reporting_period.year}-{month_code}",
            file_url=f"https://example.com/evidence/{activity.facility.facility_code.lower()}/{activity.reporting_period.year}/{month_code}/{activity.factor_code.lower()}.pdf",
            document_number=f"EV-{activity.facility.facility_code}-{activity.reporting_period.year}-{month_code}-{activity.id}",
            uploaded_by=user,
        )


def rebuild_air_emissions(facilities, periods, units):
    AirEmission.objects.filter(facility__in=facilities, reporting_period__in=periods.values()).delete()
    pollutant_profiles = [
        ("NOx", D("18.0")),
        ("SOx", D("6.5")),
        ("VOC", D("3.8")),
    ]
    air_unit = units["tonne"]
    for year, period in periods.items():
        scale = D(str(months_in_year(year))) / D("12")
        for idx, facility in enumerate(facilities, start=1):
            for pollutant, base_amount in pollutant_profiles:
                AirEmission.objects.create(
                    facility=facility,
                    reporting_period=period,
                    pollutant_type=pollutant,
                    amount=quantize((base_amount + D(str(idx))) * scale, Q4),
                    unit=air_unit,
                )


def rebuild_audit_logs(user, org, facilities, periods):
    AuditLog.objects.filter(changed_by=user, message__icontains="Takeda Ireland seed").delete()
    audit_targets = [org, *facilities, *periods.values()]
    for target in audit_targets:
        AuditLog.objects.create(
            content_type=ContentType.objects.get_for_model(target.__class__),
            object_id=target.pk,
            action="seed_sync",
            message="Takeda Ireland seed data refreshed from management command.",
            changed_by=user,
        )


def rebuild_certificates():
    if getattr(settings, "USE_AZURE_STORAGE", False):
        return

    certificate_payloads = [
        ("Takeda Ireland ISO 14001 Certificate", "Environmental management certification for Takeda Ireland operations.", "takeda-ireland-iso14001.txt"),
        ("Takeda Ireland Renewable Energy Attestation", "Renewable electricity procurement attestation supporting Ireland operations.", "takeda-ireland-renewable-energy.txt"),
    ]
    for name, description, filename in certificate_payloads:
        certificate, _ = Certificate.objects.get_or_create(
            name=name,
            defaults={"description": description},
        )
        certificate.description = description
        certificate.file.save(
            filename,
            ContentFile(f"{name}\n{description}\nGenerated on {timezone.now().date()}".encode("utf-8")),
            save=True,
        )
 
 
def delete_existing_activities(org):
    DataEvidence.objects.filter(activity__organization=org).delete()
    AirEmission.objects.filter(facility__organization=org).delete()
    EmissionActivity.objects.filter(organization=org).delete()
    MonthlyEmissionSummary.objects.filter(organization=org).delete()
    EmissionBreakdown.objects.filter(organization=org).delete()
    NeutralityClaim.objects.filter(organization=org).delete()
    EnergySummary.objects.filter(facility__organization=org).delete()
    WaterUsage.objects.filter(facility__organization=org).delete()
    WasteSummary.objects.filter(facility__organization=org).delete()
    ReductionProject.objects.filter(facility__organization=org).delete()
    CarbonCredit.objects.filter(facility__organization=org).delete()
    AuditLog.objects.filter(message__icontains="Takeda Ireland seed").delete()
 
 
def populate(username=None, purge_existing=True, skip_full_clean=False):
    normalize_dashboard_totals()
 
    user = first_active_user(username=username)
    resource, locations = get_or_create_geo()
    org, facilities = get_or_create_org_and_facilities(resource)
    periods = create_reporting_periods(org)
    units = get_or_create_units()
    gases = get_or_create_gases()
    fuel_types = get_or_create_fuel_types(units)
    source = get_or_create_factor_source()
    categories = get_or_create_categories()
    scope3_map = get_or_create_scope3_categories()
    create_emission_factors(categories, scope3_map, units, gases, source, Country.objects.get(code=IRELAND_COUNTRY_CODE), fuel_types)
 
    if purge_existing:
        delete_existing_activities(org)
 
    facility_weights = {
        "stationary_combustion": [D("0.25"), D("0.55"), D("0.20")],
        "mobile_combustion": [D("0.45"), D("0.25"), D("0.30")],
        "fugitive_emissions": [D("0.38"), D("0.22"), D("0.40")],
        "location_based": [D("0.30"), D("0.50"), D("0.20")],
        "market_based": [D("0.28"), D("0.47"), D("0.25")],
        "purchased_steam": [D("0.12"), D("0.76"), D("0.12")],
        "purchased_goods": [D("0.20"), D("0.62"), D("0.18")],
        "business_travel": [D("0.44"), D("0.18"), D("0.38")],
        "transportation": [D("0.12"), D("0.33"), D("0.55")],
        "waste": [D("0.28"), D("0.42"), D("0.30")],
    }
 
    created_count = 0
 
    for row in seed_dashboard_rows():
        year = row["year"]
        period = periods[year]
        months_count = months_in_year(year)
        year_values = {
            "stationary_combustion": scaled_for_period(row["tak_s1_inventory"]["stationary_combustion"], year),
            "mobile_combustion": scaled_for_period(row["tak_s1_inventory"]["mobile_combustion"], year),
            "fugitive_emissions": scaled_for_period(row["tak_s1_inventory"]["fugitive_emissions"], year),
            "location_based": scaled_for_period(row["tak_s2_inventory"]["location_based"], year),
            "market_based": scaled_for_period(row["tak_s2_inventory"]["market_based"], year),
            "purchased_steam": scaled_for_period(row["tak_s2_inventory"]["purchased_steam"], year),
            "purchased_goods": scaled_for_period(row["tak_s3_inventory"]["purchased_goods"], year),
            "business_travel": scaled_for_period(row["tak_s3_inventory"]["business_travel"], year),
            "transportation": scaled_for_period(row["tak_s3_inventory"]["transportation"], year),
            "waste": scaled_for_period(row["tak_s3_inventory"]["waste"], year),
        }
 
        for label, amount in year_values.items():
            split = allocate_to_facilities(amount, facility_weights[label])
            fuel_type = fuel_types.get(label)

            for facility, facility_amount in zip(facilities, split):
                department = pick_department(facility, label)
                monthly_amounts = monthly_split(facility_amount, months_count=months_count)

                for month, monthly_amount in enumerate(monthly_amounts, start=1):
                    obj, created = create_or_update_activity(
                        org=org,
                        facility=facility,
                        department=department,
                        period=period,
                        category=categories[label],
                        scope3_category=scope3_map.get(label),
                        unit=units[ACTIVITY_META[label]["unit_code"]],
                        user=user,
                        year=year,
                        month=month,
                        label=label,
                        amount=monthly_amount,
                        fuel_type=fuel_type,
                    )

                    if not skip_full_clean:
                        obj.full_clean()

                    if created:
                        created_count += 1

        rebuild_breakdowns(org, period)
        rebuild_monthly_summaries(org, facilities, period)

    rebuild_operational_summaries(facilities, periods, units)
    rebuild_reductions_and_credits(facilities, periods)
    rebuild_neutrality_claims(org, facilities, periods)
    rebuild_data_evidence(org, user)
    rebuild_air_emissions(facilities, periods, units)
    rebuild_audit_logs(user, org, facilities, periods)
    rebuild_certificates()
 
    annual_totals = []
    for row in seed_dashboard_rows():
        year = row["year"]
        period = periods[year]
        total = EmissionActivity.objects.filter(
            organization=org,
            reporting_period=period,
            status=RecordStatus.APPROVED,
        ).aggregate(total=models.Sum("total_co2e"))["total"] or D("0")
        annual_totals.append((year, total))
 
    return {
        "organization": org.name,
        "facilities": [f.name for f in facilities],
        "reporting_years": [row["year"] for row in seed_dashboard_rows()],
        "activity_rows": EmissionActivity.objects.filter(organization=org).count(),
        "created_activity_rows": created_count,
        "monthly_summary_rows": MonthlyEmissionSummary.objects.filter(organization=org).count(),
        "breakdown_rows": EmissionBreakdown.objects.filter(organization=org).count(),
        "neutrality_claim_rows": NeutralityClaim.objects.filter(organization=org).count(),
        "evidence_rows": DataEvidence.objects.filter(activity__organization=org).count(),
        "air_emission_rows": AirEmission.objects.filter(facility__organization=org).count(),
        "annual_totals": annual_totals,
    }
 
 
class Command(BaseCommand):
    help = "Populate synthetic ESG pharma data"
 
    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, default=None, help="Optional active username")
        parser.add_argument("--no-purge", action="store_true", help="Do not delete existing seeded data")
        parser.add_argument(
            "--skip-full-clean",
            action="store_true",
            help="Skip model full_clean() before save if your model has strict validators",
        )
 
    @transaction.atomic
    def handle(self, *args, **options):
       
        result = populate(
                username=options["username"],
                purge_existing=not options["no_purge"],
                skip_full_clean=options["skip_full_clean"],
            )
 
 
        self.stdout.write(self.style.SUCCESS("Data population completed successfully."))
        self.stdout.write(str(result))
 
