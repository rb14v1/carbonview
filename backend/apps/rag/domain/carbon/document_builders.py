from abc import ABC, abstractmethod

from apps.company.models import Department, Facility, Organization, ReportingPeriod
from apps.emission.models import (
    AirEmission,
    EmissionActivity,
    EmissionBreakdown,
    EmissionCategory,
    EmissionFactor,
    RecordStatus,
    Scope3Category,
)
from apps.summary.models import (
    CarbonCredit,
    EnergySummary,
    MonthlyEmissionSummary,
    NeutralityClaim,
    ReductionProject,
    WasteSummary,
    WaterUsage,
)

from ...core.common import decimal_to_float, make_document


class BaseDocumentBuilder(ABC):
    @abstractmethod
    def build(self) -> list[dict[str, object]]:
        """Return normalized RAG documents for the current data source."""
        raise NotImplementedError


class CarbonDocumentBuilder(BaseDocumentBuilder):
    def build(self) -> list[dict[str, object]]:
        """Build CarbonView-specific RAG documents from Django ORM data."""
        documents: list[dict[str, object]] = []

        def location_parts(facility: Facility) -> dict[str, str]:
            """Extract normalized location labels used in document metadata."""
            location = facility.location
            return {
                "location_label": str(location),
                "city": location.city.name if location.city_id else "",
                "state": location.state.name if location.state_id else "",
                "country": location.country.name if location.country_id else "",
            }

        def add_document(*, source: str, content: str, metadata: dict[str, object], keywords: set[str] | None = None) -> None:
            """Append a normalized document using the shared document factory."""
            documents.append(
                make_document(
                    source=source,
                    content=content,
                    metadata=metadata,
                    keywords=keywords,
                )
            )

        glossary_documents = [
            (
                "Glossary: Scope 1",
                "Scope 1 means direct emissions from sources the organization owns or controls, such as on-site fuel combustion and company vehicles.",
                {"entity": "glossary", "topic": "scope_1"},
                {"scope 1", "scope1", "s1", "definition", "direct emissions"},
            ),
            (
                "Glossary: Scope 2",
                "Scope 2 means indirect emissions from purchased electricity, steam, heating, or cooling consumed by the organization.",
                {"entity": "glossary", "topic": "scope_2"},
                {"scope 2", "scope2", "s2", "definition", "purchased electricity"},
            ),
            (
                "Glossary: Scope 3",
                "Scope 3 means all other indirect emissions across the value chain, including suppliers, transport, waste, business travel, and product use.",
                {"entity": "glossary", "topic": "scope_3"},
                {"scope 3", "scope3", "s3", "definition", "value chain"},
            ),
            (
                "Glossary: CarbonView",
                (
                    "CarbonView is a sustainability intelligence platform that helps organizations track, analyze, "
                    "and report their carbon emissions across Scope 1, Scope 2, and Scope 3. It provides tools for "
                    "facility-level emission tracking, energy and water usage monitoring, waste management insights, "
                    "and reduction project planning."
                ),
                {"entity": "glossary", "topic": "carbonview"},
                {
                    "carbonview",
                    "carbon view",
                    "platform",
                    "product",
                    "carbonview platform",
                    "sustainability intelligence platform",
                    "what is carbonview",
                    "what is carbon view",
                    "ai sustainability assistant",
                    "sustainability assistant",
                    "what can you do",
                    "what do you do",
                    "what's carbonview",
                    "what's carbon view",
                    "about carbonview",
                    "about carbon view",
                },
            ),
            (
                "Glossary: AI Sustainability Assistant",
                (
                    "The AI Sustainability Assistant is CarbonView's built-in chatbot powered by AI. "
                    "It helps users explore sustainability data including emissions (Scope 1, 2, 3), energy, water, "
                    "waste, facilities, reduction projects, and carbon credits. It can answer questions, show trends, "
                    "compare periods, and explain sustainability concepts. This is version 1 of the assistant."
                ),
                {"entity": "glossary", "topic": "assistant_identity"},
                {
                    "ai sustainability assistant",
                    "assistant",
                    "chatbot",
                    "version",
                    "version 1",
                    "what are you",
                    "what can you do",
                    "what is the assistant",
                    "carbonview assistant",
                    "what do you do",
                    "your capabilities",
                    "sustainability assistant",
                },
            ),
            (
                "Glossary: Resource and Transition Snapshot",
                (
                    "The Resource and transition snapshot is a dashboard section that summarizes operational resource "
                    "and transition indicators such as energy use, renewable energy share, water usage, waste handled, "
                    "retired credits, tracked reduction projects, and water category counts for the current dashboard selection."
                ),
                {"entity": "glossary", "topic": "resource_transition_snapshot"},
                {
                    "resource and transition snapshot",
                    "dashboard snapshot",
                    "energy",
                    "renewable energy",
                    "water usage",
                    "waste handled",
                    "renewable energy share",
                    "credits retired",
                    "projects tracked",
                    "water categories",
                },
            ),
            (
                "Glossary: Performance Signals",
                (
                    "The Performance signals section highlights dashboard trend indicators such as the latest reporting month, "
                    "peak period, top emission scope, and year-over-year emissions change so users can quickly interpret momentum."
                ),
                {"entity": "glossary", "topic": "performance_signals"},
                {
                    "performance signals",
                    "selected-year highlights",
                    "latest reporting month",
                    "peak period",
                    "top emission scope",
                    "year over year change",
                    "year-over-year change",
                },
            ),
            (
                "Glossary: Scope Breakdown",
                (
                    "The Scope breakdown view shows how the dashboard distributes emissions across the major greenhouse-gas scopes, "
                    "including each scope's share of the total footprint and the contributing emission categories underneath."
                ),
                {"entity": "glossary", "topic": "scope_breakdown"},
                {
                    "scope breakdown",
                    "scope-wise breakdown",
                    "scope split",
                },
            ),
            (
                "Glossary: Scope 2 Split",
                (
                    "The Scope 2 split compares location-based and market-based Scope 2 emissions for the current dashboard filters "
                    "so users can understand purchased-energy emissions under both accounting methods."
                ),
                {"entity": "glossary", "topic": "scope_2_split"},
                {
                    "scope 2 split",
                    "location based",
                    "market based",
                },
            ),
            (
                "Glossary: Facility Footprint Map",
                (
                    "The Facility footprint map displays the facilities in the current dashboard context with their geographic details, "
                    "activity status, and carbon-neutral indicators so users can inspect the physical footprint behind the data."
                ),
                {"entity": "glossary", "topic": "facility_footprint_map"},
                {
                    "facility footprint map",
                    "global facility map",
                    "facility locations",
                    "facility map",
                    "footprint map",
                    "dashboard geo",
                    "facility locations",
                },
            ),
            (
                "Glossary: Energy Summary",
                (
                    "Energy Summary is the dashboard concept and Django model that rolls up a facility's energy use for a reporting period. "
                    "It covers total_energy, renewable_energy, and non_renewable_energy, all stored in the linked unit such as kWh or MWh, and it powers the Energy and Renewable energy cards in the dashboard snapshot. "
                    "To get the actual values, ask 'What are the total, renewable, and non-renewable energy values for North Plant in FY2025?'"
                ),
                {"entity": "glossary", "topic": "energy_summary"},
                {
                    "energy summary",
                    "energy",
                    "renewable energy",
                    "non renewable energy",
                    "non-renewable energy",
                    "energysummary",
                    "total_energy",
                    "renewable_energy",
                    "non_renewable_energy",
                    "mwh",
                    "kwh",
                    "units",
                },
            ),
            (
                "Glossary: Water Usage",
                (
                    "Water Usage is the dashboard concept and Django model used to track a facility's water records for a reporting period. "
                    "It stores category, amount, and unit for each water line item, and the dashboard aggregates those records into total_water_usage plus the Water categories list. "
                    "To get the actual values, ask 'Show water usage by category for South Plant this year.'"
                ),
                {"entity": "glossary", "topic": "water_usage"},
                {
                    "water usage",
                    "water",
                    "water categories",
                    "wateruse",
                    "waterusage",
                    "category",
                    "amount",
                    "unit",
                    "total_water_usage",
                },
            ),
            (
                "Glossary: Waste Summary",
                (
                    "Waste Summary is the dashboard concept and Django model that summarizes waste handled by a facility for a reporting period. "
                    "It covers total_waste, hazardous, non_hazardous, recycled_percentage, and unit, so the dashboard can show both waste totals and recycling performance. "
                    "To get the actual values, ask 'What are the total, hazardous, and non-hazardous waste values for East Campus?'"
                ),
                {"entity": "glossary", "topic": "waste_summary"},
                {
                    "waste summary",
                    "waste",
                    "waste handled",
                    "hazardous waste",
                    "non hazardous waste",
                    "non-hazardous waste",
                    "wastesummary",
                    "total_waste",
                    "hazardous",
                    "non_hazardous",
                    "recycled_percentage",
                    "recycled percentage",
                },
            ),
            (
                "Glossary: Carbon Credits",
                (
                    "Carbon Credits are dashboard records for offset projects linked to a facility. "
                    "They store project_name, source, registry_name, serial_number, vintage_year, quantity_tco2e, purchase_date, retirement_date, and status, with quantity_tco2e measured in tCO2e. "
                    "To get the actual values, ask 'Show retired carbon credits for this facility with quantity and vintage year.'"
                ),
                {"entity": "glossary", "topic": "carbon_credits"},
                {
                    "carbon credits",
                    "carbon credit",
                    "credits retired",
                    "offset credits",
                    "offsets",
                    "carboncredit",
                    "project_name",
                    "registry_name",
                    "serial_number",
                    "vintage_year",
                    "quantity_tco2e",
                    "purchase_date",
                    "retirement_date",
                    "status",
                    "tco2e",
                },
            ),
            (
                "Glossary: Credits Retired",
                (
                    "Credits retired is the dashboard aggregate that sums the quantity_tco2e of retired carbon credits in the current dashboard selection. "
                    "It reflects retired credit quantities in tCO2e and is derived from carbon credit records rather than from emission-activity totals. "
                    "To get the actual values, ask 'How many credits were retired for this dashboard selection?'"
                ),
                {"entity": "glossary", "topic": "credits_retired"},
                {
                    "credits retired",
                    "retired credits",
                    "what is credits retired",
                    "what are credits retired",
                    "credits retired meaning",
                    "quantity_tco2e",
                    "retired",
                    "tco2e",
                },
            ),
            (
                "Glossary: Total Retired",
                (
                    "Total retired is the summary number shown in the Carbon credits card for the current dashboard filters. "
                    "It represents the total retired carbon-credit quantity in tCO2e, aggregated from credit records whose status is retired. "
                    "To get the actual values, ask 'Show the total retired carbon credits for this year.'"
                ),
                {"entity": "glossary", "topic": "total_retired"},
                {
                    "total retired",
                    "what is total retired",
                    "total retired credits",
                    "retired total",
                    "retired carbon credits total",
                    "quantity_tco2e",
                    "retired",
                    "tco2e",
                },
            ),
            (
                "Glossary: Reduction Projects",
                (
                    "Reduction Projects are dashboard initiatives that track expected and achieved emissions savings at a facility. "
                    "They store name, description, start_date, end_date, expected_reduction_tco2e, and actual_reduction_tco2e, with reduction values measured in tCO2e. "
                    "To see your active reduction projects, ask: 'What reduction projects are tracked?' or "
                    "'Show me reduction projects for [facility name]'."
                ),
                {"entity": "glossary", "topic": "reduction_projects"},
                {
                    "reduction projects",
                    "reduction project",
                    "projects tracked",
                    "project reductions",
                    "reductionproject",
                    "name",
                    "description",
                    "start_date",
                    "end_date",
                    "expected_reduction_tco2e",
                    "actual_reduction_tco2e",
                    "tco2e",
                },
            ),
            (
                "Glossary: Projects Tracked",
                (
                    "Projects tracked is the dashboard count of reduction projects included in the current filters. "
                    "It represents how many reduction-project records are in scope, while the project details themselves carry expected_reduction_tco2e and actual_reduction_tco2e in tCO2e. "
                    "To get the actual values, ask 'How many reduction projects are tracked on this dashboard?'"
                ),
                {"entity": "glossary", "topic": "projects_tracked"},
                {
                    "projects tracked",
                    "what is projects tracked",
                    "project count",
                    "tracked projects",
                    "reduction projects count",
                    "expected_reduction_tco2e",
                    "actual_reduction_tco2e",
                },
            ),
            (
                "Glossary: Water Categories",
                (
                    "Water categories is the dashboard count and grouping of distinct water-usage categories in the current selection. "
                    "Those categories come from Water Usage records, which store category, amount, and unit for each water entry and are commonly measured in units such as m3. "
                    "To get the actual values, ask 'Show water categories with their amounts and units for this dashboard.'"
                ),
                {"entity": "glossary", "topic": "water_categories"},
                {
                    "water categories",
                    "what is water categories",
                    "water category count",
                    "water category",
                    "water usage categories",
                    "category",
                    "amount",
                    "unit",
                    "m3",
                },
            ),
            (
                "Glossary: Neutrality Claims",
                (
                    "Neutrality Claims are dashboard records that show whether an organization or facility is carbon neutral for a reporting period. "
                    "They cover gross_emissions, reductions, offsets_retired, net_emissions, status, and notes, with the emissions values measured in tCO2e. "
                    "To find carbon neutral facilities, ask: 'Which facilities have neutrality claims?' or "
                    "'Show me neutrality status for [facility name]'."
                ),
                {"entity": "glossary", "topic": "neutrality_claims"},
                {
                    "neutrality claims",
                    "neutrality claim",
                    "carbon neutral",
                    "net emissions",
                    "gross emissions",
                    "offsets retired",
                    "neutralityclaim",
                    "gross_emissions",
                    "reductions",
                    "offsets_retired",
                    "net_emissions",
                    "status",
                    "notes",
                    "tco2e",
                },
            ),
            (
                "Glossary: Monthly Emission Summary",
                (
                    "Monthly Emission Summary is the model and dashboard series behind monthly and yearly emissions charts. "
                    "It stores year, month, scope, total_co2e, organization, facility, and reporting_period so CarbonView can build monthly_emissions, yearly_emissions, latest month, and peak period insights in tCO2e. "
                    "To get the actual values, ask 'Show the monthly emission summary for Scope 2 in 2025.'"
                ),
                {"entity": "glossary", "topic": "monthly_emission_summary"},
                {
                    "monthly emission summary",
                    "emissions trend",
                    "latest reporting month",
                    "peak period",
                    "monthlyemissionsummary",
                    "total_co2e",
                    "year",
                    "month",
                    "scope",
                    "monthly_emissions",
                    "yearly_emissions",
                    "tco2e",
                },
            ),
            (
                "Glossary: Emission Activity",
                (
                    "Emission Activity is the detailed transaction-level record that captures a specific emissions-producing event. "
                    "It stores activity_name, activity_date, quantity, unit, factor_code, scope2_method, data_quality, supplier_name, invoice_number, source_reference, total_co2e, and status, along with category, scope3_category, and facility context. "
                    "To get the actual values, ask 'Show approved emission activities for Scope 3 with quantity and total CO2e.'"
                ),
                {"entity": "glossary", "topic": "emission_activity"},
                {
                    "emission activity",
                    "emission activities",
                    "approved activities",
                    "activity record",
                    "emissionactivity",
                    "activity_name",
                    "activity_date",
                    "quantity",
                    "unit",
                    "factor_code",
                    "scope2_method",
                    "data_quality",
                    "supplier_name",
                    "invoice_number",
                    "source_reference",
                    "total_co2e",
                    "status",
                },
            ),
            (
                "Glossary: Emission Breakdown",
                (
                    "Emission Breakdown is the aggregated dataset behind scope-level and category-level dashboard splits. "
                    "It stores scope, category, subcategory, scope3_category, gas_type, fuel_type, total_co2e, and total_quantity for an organization, facility, and reporting_period so users can see what makes up each scope total. "
                    "To get the actual values, ask 'Give me the emission breakdown by category and gas type for Scope 1 this year.'"
                ),
                {"entity": "glossary", "topic": "emission_breakdown"},
                {
                    "emission breakdown",
                    "breakdown",
                    "scope-wise breakdown",
                    "scope split",
                    "emissionbreakdown",
                    "scope",
                    "category",
                    "subcategory",
                    "scope3_category",
                    "gas_type",
                    "fuel_type",
                    "total_co2e",
                    "total_quantity",
                },
            ),
            (
                "Glossary: Air Emission",
                (
                    "Air Emission is a facility-level pollutant record stored for a reporting period. "
                    "It tracks pollutant_type, amount, and unit for non-CO2 air pollutants, separate from the carbon total fields used for greenhouse-gas summaries. "
                    "To get the actual values, ask 'Show air emissions by pollutant type for West Plant.'"
                ),
                {"entity": "glossary", "topic": "air_emission"},
                {
                    "air emission",
                    "air emissions",
                    "pollutant",
                    "pollutant type",
                    "airemission",
                    "pollutant_type",
                    "amount",
                    "unit",
                },
            ),
            (
                "Glossary: Reporting Period",
                (
                    "A Reporting Period is the named time window CarbonView uses to group dashboard and emissions data for an organization. "
                    "It stores name, year, start_date, end_date, and is_closed, and many dashboard summaries are filtered or labeled by the linked reporting_period. "
                    "To get the actual values, ask 'What reporting periods are available for this organization and which one is the latest?'"
                ),
                {"entity": "glossary", "topic": "reporting_period"},
                {
                    "reporting period",
                    "reporting periods",
                    "reporting month",
                    "period",
                    "reportingperiod",
                    "name",
                    "year",
                    "start_date",
                    "end_date",
                    "is_closed",
                },
            ),
            (
                "Glossary: Reports & Analytics",
                (
                    "Reports & Analytics is the CarbonView reporting view that turns dashboard summary data into downloadable annual and quarterly reporting views. "
                    "It covers report title, date, type, emissions, and change, and it also supports ESG Excel export by start_date and end_date for custom reporting windows. "
                    "To get the actual values, ask 'Show the available annual and quarterly reports with emissions and change.'"
                ),
                {"entity": "glossary", "topic": "reports_analytics"},
                {
                    "report",
                    "reports",
                    "reports & analytics",
                    "reports and analytics",
                    "report analytics",
                    "annual report",
                    "quarterly report",
                    "sustainability report",
                    "esg report",
                    "report title",
                    "report date",
                    "report type",
                    "emissions",
                    "change",
                    "start_date",
                    "end_date",
                },
            ),
            (
                "Glossary: Organization",
                (
                    "An Organization is the top-level company entity CarbonView reports on. "
                    "It stores name, legal_name, industry_type, reporting_boundary, base_currency, base_year, and an optional resource link, and it owns the facilities and reporting periods used across the dashboard. "
                    "To get the actual values, ask 'Show the organization profile with industry type, reporting boundary, and base year.'"
                ),
                {"entity": "glossary", "topic": "organization"},
                {
                    "organization",
                    "company",
                    "org",
                    "legal_name",
                    "industry_type",
                    "reporting_boundary",
                    "base_currency",
                    "base_year",
                },
            ),
            (
                "Glossary: Facility",
                (
                    "A Facility is an operational site that belongs to an organization and anchors most dashboard metrics. "
                    "It stores facility_code, name, description, is_active, is_carbon_neutral, and location details, and it links emissions, energy, water, waste, projects, and credits to a physical site. "
                    "To get the actual values, ask 'List the facilities with facility code, active status, and carbon-neutral status.'"
                ),
                {"entity": "glossary", "topic": "facility"},
                {
                    "facility",
                    "facilities",
                    "site",
                    "plant",
                    "campus",
                    "facility_code",
                    "is_active",
                    "is_carbon_neutral",
                    "location",
                },
            ),
            (
                "Glossary: Department",
                (
                    "A Department is a subdivision inside a facility that can be attached to emission activities. "
                    "It stores a department name and its facility relationship so users can break activity records down beyond the site level when that context is available. "
                    "To get the actual values, ask 'Show departments for North Plant and their related emission activities.'"
                ),
                {"entity": "glossary", "topic": "department"},
                {
                    "department",
                    "departments",
                    "team",
                    "business unit",
                    "name",
                    "facility",
                },
            ),
            (
                "Glossary: Emission Category",
                (
                    "An Emission Category is the classification layer used to organize activities and breakdowns inside a scope. "
                    "It stores code, name, scope, parent, category_type, scope3_category_number, and description so CarbonView can group records into scope, category, and subcategory hierarchies. "
                    "To get the actual values, ask 'Show emission categories with code, scope, and parent category.'"
                ),
                {"entity": "glossary", "topic": "emission_category"},
                {
                    "emission category",
                    "emission categories",
                    "category",
                    "subcategory",
                    "emissioncategory",
                    "code",
                    "scope",
                    "parent",
                    "category_type",
                    "scope3_category_number",
                    "description",
                },
            ),
            (
                "Glossary: Scope 3 Category",
                (
                    "A Scope 3 Category is the value-chain classification used for Scope 3 activities and factors. "
                    "It stores code, name, and description so purchased goods, transport, waste, travel, and similar indirect emissions can be labeled consistently. "
                    "To get the actual values, ask 'List Scope 3 categories with their codes and names.'"
                ),
                {"entity": "glossary", "topic": "scope3_category"},
                {
                    "scope 3 category",
                    "scope3 category",
                    "scope 3 categories",
                    "scope3category",
                    "code",
                    "name",
                    "description",
                },
            ),
            (
                "Glossary: Emission Factor",
                (
                    "An Emission Factor is the conversion reference CarbonView uses to turn activity quantities into gas amounts and CO2e. "
                    "It stores source, category, scope3_category, gas_type, fuel_type, factor_code, factor_name, factor_value, activity_unit, factor_unit, geography, validity dates, and active status. "
                    "To get the actual values, ask 'Show the emission factor for diesel in India with factor value and unit.'"
                ),
                {"entity": "glossary", "topic": "emission_factor"},
                {
                    "emission factor",
                    "emission factors",
                    "factor",
                    "emissionfactor",
                    "factor_code",
                    "factor_name",
                    "factor_value",
                    "activity_unit",
                    "factor_unit",
                    "gas_type",
                    "fuel_type",
                    "geography",
                    "valid_from",
                    "valid_to",
                    "is_active",
                },
            ),
            (
                "Glossary: Total Emissions",
                (
                    "Total Emissions is the top KPI card for the selected dashboard filters. "
                    "It is built from gross_emissions and is often interpreted alongside offsets, reductions, net_emissions, approved_activities, and the scope shares shown on the card, all measured in tCO2e except approved_activities which is a count. "
                    "To get the actual values, ask 'What are the total emissions, net emissions, offsets, and reductions for this dashboard?'"
                ),
                {"entity": "glossary", "topic": "total_emissions"},
                {
                    "total emissions",
                    "gross emissions",
                    "net emissions",
                    "kpi",
                    "dashboard total",
                    "gross_emissions",
                    "offsets",
                    "reductions",
                    "net_emissions",
                    "approved_activities",
                    "tco2e",
                },
            ),
            (
                "Glossary: Emissions Forecast",
                (
                    "Emissions Forecast is the dashboard widget that estimates the next month's emissions from recent monthly summary data. "
                    "It uses recent monthly totals to show a next-month estimate, trendPercent, latestMonthLabel, latestMonthTotal, and short forecast insights, with emissions shown in tons CO2e. "
                    "To get the actual values, ask 'What is the emissions forecast and latest month total shown on the dashboard?'"
                ),
                {"entity": "glossary", "topic": "emissions_forecast"},
                {
                    "emissions forecast",
                    "forecast",
                    "forecast insights",
                    "next month estimate",
                    "recent trend estimate",
                    "trendpercent",
                    "latestmonthlabel",
                    "latestmonthtotal",
                    "tons co2e",
                },
            ),
            (
                "Glossary: Next Month Estimate",
                (
                    "Next Month Estimate is the headline number inside the Emissions Forecast widget. "
                    "It projects the next month's emissions in tons CO2e using recent monthly totals, and it is displayed alongside the recent trend estimate and latest month context. "
                    "To get the actual values, ask 'What is the next month estimate in the emissions forecast?'"
                ),
                {"entity": "glossary", "topic": "next_month_estimate"},
                {
                    "next month estimate",
                    "what is next month estimate",
                    "forecast estimate",
                    "emissions estimate",
                    "tons co2e",
                    "forecast",
                },
            ),
            (
                "Glossary: Forecast Insights",
                (
                    "Forecast Insights is the explanatory list underneath the Emissions Forecast widget. "
                    "It summarizes the latest recorded month, month-over-month change, latest month total, and the direction implied by the recent forecasting trend. "
                    "To get the actual values, ask 'Show the forecast insights including latest month and month-over-month change.'"
                ),
                {"entity": "glossary", "topic": "forecast_insights"},
                {
                    "forecast insights",
                    "what is forecast insights",
                    "forecast details",
                    "latest recorded month",
                    "month-over-month change",
                    "latest month total",
                    "forecast",
                },
            ),
        ]
        for source, content, metadata, keywords in glossary_documents:
            add_document(source=source, content=content, metadata=metadata, keywords=keywords)

        organizations = list(Organization.objects.order_by("name"))
        facilities = list(
            Facility.objects.select_related(
                "organization",
                "location",
                "location__city",
                "location__state",
                "location__country",
            ).prefetch_related("departments").order_by(
                "organization__name", "name"
            )
        )
        departments = list(
            Department.objects.select_related("facility", "facility__organization").order_by("facility__name", "name")
        )
        emission_categories = list(
            EmissionCategory.objects.select_related("parent").order_by("scope", "code")
        )
        scope3_categories = list(Scope3Category.objects.order_by("code"))
        emission_factors = list(
            EmissionFactor.objects.select_related(
                "source",
                "category",
                "scope3_category",
                "gas_type",
                "activity_unit",
                "geography",
            ).order_by("source__name", "factor_code", "valid_from")
        )
        reporting_periods = list(ReportingPeriod.objects.select_related("organization").order_by("-year", "-start_date"))
        monthly_summaries = list(
            MonthlyEmissionSummary.objects.select_related(
                "organization",
                "facility",
                "facility__location",
                "facility__location__city",
                "facility__location__state",
                "facility__location__country",
                "reporting_period",
            ).order_by("-year", "-month", "scope")
        )
        projects = list(ReductionProject.objects.select_related("facility", "facility__organization").order_by("name"))
        credits = list(
            CarbonCredit.objects.select_related("facility", "facility__organization").order_by("-vintage_year", "project_name")
        )
        claims = list(NeutralityClaim.objects.select_related("organization", "facility", "reporting_period").order_by("name"))
        energy_summaries = list(
            EnergySummary.objects.select_related("facility", "facility__organization", "reporting_period", "unit").order_by(
                "facility__organization__name", "facility__name"
            )
        )
        water_usages = list(
            WaterUsage.objects.select_related("facility", "facility__organization", "reporting_period", "unit").order_by(
                "facility__organization__name", "facility__name", "category"
            )
        )
        waste_summaries = list(
            WasteSummary.objects.select_related("facility", "facility__organization", "reporting_period", "unit").order_by(
                "facility__organization__name", "facility__name"
            )
        )
        activities = list(
            EmissionActivity.objects.select_related(
                "organization", "facility", "department", "reporting_period", "category", "scope3_category", "unit"
            ).filter(status=RecordStatus.APPROVED).order_by("-activity_date", "-id")
        )
        emission_breakdowns = list(
            EmissionBreakdown.objects.select_related(
                "organization", "facility", "reporting_period", "category", "subcategory", "scope3_category", "gas_type"
            ).order_by("organization__name", "reporting_period__year", "scope", "category__name", "subcategory__name")
        )
        air_emissions = list(
            AirEmission.objects.select_related("facility", "facility__organization", "reporting_period", "unit").order_by(
                "facility__organization__name", "facility__name", "pollutant_type"
            )
        )

        departments_by_facility: dict[int, list[Department]] = {}
        for department in departments:
            departments_by_facility.setdefault(department.facility_id, []).append(department)

        periods_by_org: dict[int, list[ReportingPeriod]] = {}
        for period in reporting_periods:
            periods_by_org.setdefault(period.organization_id, []).append(period)

        facility_count_by_org: dict[int, int] = {}
        for facility in facilities:
            facility_count_by_org[facility.organization_id] = facility_count_by_org.get(facility.organization_id, 0) + 1

        period_count_by_org: dict[int, int] = {}
        for period in reporting_periods:
            period_count_by_org[period.organization_id] = period_count_by_org.get(period.organization_id, 0) + 1

        monthly_by_org: dict[int, list[MonthlyEmissionSummary]] = {}
        monthly_by_facility: dict[int, list[MonthlyEmissionSummary]] = {}
        monthly_by_period: dict[int, list[MonthlyEmissionSummary]] = {}
        for summary in monthly_summaries:
            monthly_by_org.setdefault(summary.organization_id, []).append(summary)
            if summary.facility_id:
                monthly_by_facility.setdefault(summary.facility_id, []).append(summary)
            monthly_by_period.setdefault(summary.reporting_period_id, []).append(summary)

        for organization in organizations:
            org_monthly = monthly_by_org.get(organization.id, [])
            scope_totals_map: dict[str, float] = {}
            for summary in org_monthly:
                scope_totals_map.setdefault(summary.scope, 0.0)
                scope_totals_map[summary.scope] += decimal_to_float(summary.total_co2e)
            scope_summary = ", ".join(
                f"{scope}: {total:.2f} tCO2e" for scope, total in sorted(scope_totals_map.items())
            ) or "No monthly summary data available"
            latest_period = periods_by_org.get(organization.id, [])
            latest_period_name = latest_period[0].name if latest_period else "none"
            latest_year = latest_period[0].year if latest_period else "unknown"
            common_metadata = {"entity": "organization_overview", "organization": organization.name, "organization_id": organization.id}
            add_document(
                source=f"Organization Overview: {organization.name}",
                content=(
                    f"Organization {organization.name}. Industry type: {organization.industry_type}. "
                    f"Reporting boundary: {organization.reporting_boundary}. Base currency: {organization.base_currency}. "
                    f"Base year: {organization.base_year or 'not set'}."
                ),
                metadata=common_metadata,
                keywords={"organization", "overview", organization.name},
            )
            add_document(
                source=f"Organization Reporting: {organization.name}",
                content=(
                    f"Organization {organization.name}. Facilities: {facility_count_by_org.get(organization.id, 0)}. "
                    f"Reporting periods: {period_count_by_org.get(organization.id, 0)}. "
                    f"Latest reporting period: {latest_period_name} ({latest_year}). "
                    f"Monthly emission records available: {len(org_monthly)}. "
                    f"Aggregated scope totals: {scope_summary}. "
                    f"This reporting view is useful for comparing the organization's emissions coverage across available years and periods."
                ),
                metadata=common_metadata,
                keywords={
                    "organization",
                    "reporting",
                    "emissions",
                    "compare emissions",
                    "emission history",
                    "monthly emissions",
                    "yearly emissions",
                    "reporting periods",
                    organization.name,
                    str(latest_year),
                },
            )

        for category in emission_categories:
            parent_name = category.parent.name if category.parent_id else "none"
            documents.append(
                make_document(
                    source=f"Emission Category: {category.code}",
                    content=(
                        f"Emission category {category.code} named {category.name}. Scope: {category.scope}. "
                        f"Category type: {category.category_type}. Parent: {parent_name}. "
                        f"Scope 3 category number: {category.scope3_category_number or 'not set'}. "
                        f"Description: {category.description or 'not provided'}."
                    ),
                    metadata={
                        "entity": "emission_category",
                        "category_code": category.code,
                        "category": category.name,
                        "scope": category.scope,
                        "category_type": category.category_type,
                        "parent_category": parent_name if parent_name != "none" else None,
                    },
                    keywords={
                        "category",
                        "emission",
                        category.code,
                        category.name,
                        category.scope,
                        category.category_type,
                        parent_name,
                    },
                )
            )

        for scope3_category in scope3_categories:
            documents.append(
                make_document(
                    source=f"Scope 3 Category: {scope3_category.code}",
                    content=(
                        f"Scope 3 category {scope3_category.code} named {scope3_category.name}. "
                        f"Description: {scope3_category.description or 'not provided'}."
                    ),
                    metadata={
                        "entity": "scope3_category",
                        "scope3_code": scope3_category.code,
                        "scope3_category": scope3_category.name,
                    },
                    keywords={"scope3", "scope 3", scope3_category.code, scope3_category.name},
                )
            )

        for factor in emission_factors:
            documents.append(
                make_document(
                    source=f"Emission Factor: {factor.factor_code}",
                    content=(
                        f"Emission factor {factor.factor_code} named {factor.factor_name}. "
                        f"Source: {factor.source.name} {factor.source.version}. "
                        f"Category: {factor.category.name}. Scope: {factor.category.scope}. "
                        f"Scope 3 category: {factor.scope3_category.name if factor.scope3_category_id else 'not applicable'}. "
                        f"Gas type: {factor.gas_type.gas_name}. Factor value: {decimal_to_float(factor.factor_value):.8f}. "
                        f"Activity unit: {factor.activity_unit.code}. Factor unit: {factor.factor_unit}. "
                        f"Geography: {factor.geography.name if factor.geography_id else 'global'}. "
                        f"Valid from: {factor.valid_from}. Valid to: {factor.valid_to or 'open ended'}. "
                        f"Active: {'yes' if factor.is_active else 'no'}."
                    ),
                    metadata={
                        "entity": "emission_factor",
                        "factor_code": factor.factor_code,
                        "factor_name": factor.factor_name,
                        "category": factor.category.name,
                        "scope": factor.category.scope,
                        "scope3_category": factor.scope3_category.name if factor.scope3_category_id else None,
                        "gas_type": factor.gas_type.gas_name,
                        "country": factor.geography.name if factor.geography_id else None,
                    },
                    keywords={
                        "factor",
                        "emission factor",
                        factor.factor_code,
                        factor.factor_name,
                        factor.category.name,
                        factor.category.scope,
                        factor.gas_type.gas_name,
                        factor.activity_unit.code,
                        factor.geography.name if factor.geography_id else "global",
                    },
                )
            )

        for facility in facilities:
            facility_location = location_parts(facility)
            location_name = facility_location["location_label"]
            facility_monthly = monthly_by_facility.get(facility.id, [])
            total_co2e = sum(decimal_to_float(item.total_co2e) for item in facility_monthly)
            latest_summary = facility_monthly[0] if facility_monthly else None
            common_metadata = {
                "entity": "facility_overview",
                "organization": facility.organization.name,
                "organization_id": facility.organization_id,
                "facility": facility.name,
                "facility_id": facility.id,
                "location": location_name,
                "city": facility_location["city"],
                "state": facility_location["state"],
                "country": facility_location["country"],
                "is_active": facility.is_active,
                "is_carbon_neutral": facility.is_carbon_neutral,
            }
            add_document(
                source=f"Facility Overview: {facility.name}",
                content=(
                    f"Facility {facility.name} belongs to organization {facility.organization.name}. Location: {location_name}. "
                    f"Facility code: {facility.facility_code or 'not set'}. Description: {facility.description or 'not provided'}. "
                    f"Active: {'yes' if facility.is_active else 'no'}. Carbon neutral flag: {'yes' if facility.is_carbon_neutral else 'no'}."
                ),
                metadata=common_metadata,
                keywords={
                    "facility",
                    "site",
                    "overview",
                    "location",
                    "locations",
                    "located",
                    "map",
                    "facility map",
                    "facility footprint map",
                    "carbon neutral",
                    "carbon-neutral",
                    "active",
                    facility.name,
                    facility.organization.name,
                    facility_location["city"],
                    facility_location["state"],
                    facility_location["country"],
                },
            )
            add_document(
                source=f"Facility Emissions: {facility.name}",
                content=(
                    f"Facility {facility.name} in organization {facility.organization.name}. "
                    f"Department count: {len(departments_by_facility.get(facility.id, []))}. "
                    f"Tracked monthly emission total: {total_co2e:.2f} tCO2e. Latest monthly summary: "
                    f"{latest_summary.year}-{latest_summary.month:02d} {latest_summary.scope} "
                    f"{decimal_to_float(latest_summary.total_co2e):.2f} tCO2e."
                    if latest_summary
                    else (
                        f"Facility {facility.name} in organization {facility.organization.name}. "
                        f"Department count: {len(departments_by_facility.get(facility.id, []))}. "
                        "No monthly emission summaries are available for this facility yet."
                    )
                ),
                metadata=common_metadata,
                keywords={
                    "facility",
                    "emissions",
                    "monthly",
                    facility.name,
                    facility.organization.name,
                    facility_location["city"],
                    facility_location["state"],
                    facility_location["country"],
                },
            )

        for department in departments:
            add_document(
                source=f"Department: {department.name}",
                content=(
                    f"Department {department.name} is in facility {department.facility.name} under organization "
                    f"{department.facility.organization.name}."
                ),
                metadata={
                    "entity": "department",
                    "organization": department.facility.organization.name,
                    "organization_id": department.facility.organization_id,
                    "facility": department.facility.name,
                    "facility_id": department.facility_id,
                    "department": department.name,
                },
                keywords={"department", department.name, department.facility.name},
            )

        for period in reporting_periods:
            period_summaries = monthly_by_period.get(period.id, [])
            total_period_co2e = sum(decimal_to_float(item.total_co2e) for item in period_summaries)
            add_document(
                source=f"Reporting Period: {period.name}",
                content=(
                    f"Reporting period {period.name} for organization {period.organization.name}. Year: {period.year}. "
                    f"Start date: {period.start_date}. End date: {period.end_date}. "
                    f"Closed: {'yes' if period.is_closed else 'no'}. Monthly records in this period: {len(period_summaries)}. "
                    f"Total tracked emissions in this period: {total_period_co2e:.2f} tCO2e."
                ),
                metadata={
                    "entity": "reporting_period",
                    "organization": period.organization.name,
                    "organization_id": period.organization_id,
                    "reporting_period": period.name,
                    "reporting_period_id": period.id,
                    "year": period.year,
                },
                keywords={"reporting", "period", str(period.year), period.name, period.organization.name},
            )

        for summary in monthly_summaries:
            facility_name = summary.facility.name if summary.facility_id else "All facilities"
            facility_location = location_parts(summary.facility) if summary.facility_id else {
                "location_label": "",
                "city": "",
                "state": "",
                "country": "",
            }
            documents.append(
                make_document(
                    source=f"Monthly Summary: {summary.organization.name} {summary.year}-{summary.month:02d} {summary.scope}",
                    content=(
                        f"Monthly emission summary for {summary.organization.name}. Facility: {facility_name}. "
                        f"Location: {facility_location['city']}, {facility_location['state']}, {facility_location['country']}. "
                        f"Reporting period: {summary.reporting_period.name}. Year: {summary.year}. Month: {summary.month}. "
                        f"Scope: {summary.scope}. Total CO2e: {decimal_to_float(summary.total_co2e):.2f} tCO2e."
                    ),
                    metadata={
                        "entity": "monthly_summary",
                        "organization": summary.organization.name,
                        "organization_id": summary.organization_id,
                        "facility": facility_name,
                        "facility_id": summary.facility_id,
                        "reporting_period": summary.reporting_period.name,
                        "reporting_period_id": summary.reporting_period_id,
                        "year": summary.year,
                        "month": summary.month,
                        "scope": summary.scope,
                        "city": facility_location["city"],
                        "state": facility_location["state"],
                        "country": facility_location["country"],
                    },
                    keywords={
                        "monthly",
                        "summary",
                        "emissions",
                        summary.scope,
                        summary.organization.name,
                        facility_name,
                        str(summary.year),
                        facility_location["city"],
                        facility_location["state"],
                        facility_location["country"],
                    },
                )
            )

        for project in projects:
            documents.append(
                make_document(
                    source=f"Reduction Project: {project.name}",
                    content=(
                        f"Reduction project {project.name} in facility {project.facility.name}. Organization: "
                        f"{project.facility.organization.name}. Description: {project.description or 'not provided'}. "
                        f"Expected reduction: {decimal_to_float(project.expected_reduction_tco2e):.2f} tCO2e. "
                        f"Actual reduction: {decimal_to_float(project.actual_reduction_tco2e):.2f} tCO2e. "
                        f"Start date: {project.start_date or 'not set'}. End date: {project.end_date or 'not set'}."
                    ),
                    metadata={
                        "entity": "reduction_project",
                        "organization": project.facility.organization.name,
                        "organization_id": project.facility.organization_id,
                        "facility": project.facility.name,
                        "facility_id": project.facility_id,
                        "project": project.name,
                    },
                    keywords={"project", "reduction", project.name, project.facility.name},
                )
            )

        for credit in credits:
            documents.append(
                make_document(
                    source=f"Carbon Credit: {credit.project_name}",
                    content=(
                        f"Carbon credit project {credit.project_name} for facility {credit.facility.name}. "
                        f"Organization: {credit.facility.organization.name}. Registry: {credit.registry_name}. "
                        f"Quantity retired or purchased: {decimal_to_float(credit.quantity_tco2e):.2f} tCO2e. "
                        f"Status: {credit.status}. Source: {credit.source}. Vintage year: {credit.vintage_year}. "
                        f"Purchase date: {credit.purchase_date or 'not set'}. Retirement date: {credit.retirement_date or 'not set'}."
                    ),
                    metadata={
                        "entity": "carbon_credit",
                        "organization": credit.facility.organization.name,
                        "organization_id": credit.facility.organization_id,
                        "facility": credit.facility.name,
                        "facility_id": credit.facility_id,
                        "project": credit.project_name,
                        "status": credit.status,
                        "year": credit.vintage_year,
                    },
                    keywords={"credit", "offset", credit.project_name, credit.status, str(credit.vintage_year)},
                )
            )

        for claim in claims:
            facility_name = claim.facility.name if claim.facility_id else "Organization-wide"
            documents.append(
                make_document(
                    source=f"Neutrality Claim: {claim.name}",
                    content=(
                        f"Neutrality claim {claim.name} for organization {claim.organization.name}. Facility scope: {facility_name}. "
                        f"Reporting period: {claim.reporting_period.name}. Gross emissions: {decimal_to_float(claim.gross_emissions):.2f} tCO2e. "
                        f"Reductions: {decimal_to_float(claim.reductions):.2f} tCO2e. Offsets retired: "
                        f"{decimal_to_float(claim.offsets_retired):.2f} tCO2e. Net emissions: {decimal_to_float(claim.net_emissions):.2f} tCO2e. "
                        f"Status: {claim.status}. Notes: {claim.notes or 'none'}."
                    ),
                    metadata={
                        "entity": "neutrality_claim",
                        "organization": claim.organization.name,
                        "organization_id": claim.organization_id,
                        "facility": facility_name,
                        "facility_id": claim.facility_id,
                        "reporting_period": claim.reporting_period.name,
                        "reporting_period_id": claim.reporting_period_id,
                        "status": claim.status,
                    },
                    keywords={"neutral", "net", "claim", claim.name, claim.status},
                )
            )

        for summary in energy_summaries:
            documents.append(
                make_document(
                    source=f"Energy Summary: {summary.facility.name} {summary.reporting_period.name}",
                    content=(
                        f"Energy summary for facility {summary.facility.name} in organization {summary.facility.organization.name}. "
                        f"Reporting period: {summary.reporting_period.name}. Total energy: {decimal_to_float(summary.total_energy):.2f} {summary.unit.code}. "
                        f"Renewable energy: {decimal_to_float(summary.renewable_energy):.2f} {summary.unit.code}. "
                        f"Non-renewable energy: {decimal_to_float(summary.non_renewable_energy):.2f} {summary.unit.code}."
                    ),
                    metadata={
                        "entity": "energy_summary",
                        "organization": summary.facility.organization.name,
                        "organization_id": summary.facility.organization_id,
                        "facility": summary.facility.name,
                        "facility_id": summary.facility_id,
                        "reporting_period": summary.reporting_period.name,
                        "reporting_period_id": summary.reporting_period_id,
                    },
                    keywords={"energy", "renewable", "power", summary.facility.name, summary.reporting_period.name},
                )
            )

        for usage in water_usages:
            documents.append(
                make_document(
                    source=f"Water Usage: {usage.facility.name} {usage.category}",
                    content=(
                        f"Water usage for facility {usage.facility.name} in organization {usage.facility.organization.name}. "
                        f"Reporting period: {usage.reporting_period.name}. Category: {usage.category}. "
                        f"Amount: {decimal_to_float(usage.amount):.2f} {usage.unit.code}."
                    ),
                    metadata={
                        "entity": "water_usage",
                        "organization": usage.facility.organization.name,
                        "organization_id": usage.facility.organization_id,
                        "facility": usage.facility.name,
                        "facility_id": usage.facility_id,
                        "reporting_period": usage.reporting_period.name,
                        "reporting_period_id": usage.reporting_period_id,
                        "category": usage.category,
                    },
                    keywords={"water", "usage", "consumption", usage.category, usage.facility.name},
                )
            )

        for summary in waste_summaries:
            documents.append(
                make_document(
                    source=f"Waste Summary: {summary.facility.name} {summary.reporting_period.name}",
                    content=(
                        f"Waste summary for facility {summary.facility.name} in organization {summary.facility.organization.name}. "
                        f"Reporting period: {summary.reporting_period.name}. Total waste: {decimal_to_float(summary.total_waste):.2f} {summary.unit.code}. "
                        f"Hazardous waste: {decimal_to_float(summary.hazardous):.2f} {summary.unit.code}. "
                        f"Non-hazardous waste: {decimal_to_float(summary.non_hazardous):.2f} {summary.unit.code}. "
                        f"Recycled percentage: {decimal_to_float(summary.recycled_percentage):.2f}%."
                    ),
                    metadata={
                        "entity": "waste_summary",
                        "organization": summary.facility.organization.name,
                        "organization_id": summary.facility.organization_id,
                        "facility": summary.facility.name,
                        "facility_id": summary.facility_id,
                        "reporting_period": summary.reporting_period.name,
                        "reporting_period_id": summary.reporting_period_id,
                    },
                    keywords={"waste", "hazardous", "recycled", summary.facility.name},
                )
            )

        for activity in activities:
            documents.append(
                make_document(
                    source=f"Emission Activity: {activity.activity_name}",
                    content=(
                        f"Approved emission activity {activity.activity_name} for organization {activity.organization.name}. "
                        f"Facility: {activity.facility.name}. Department: "
                        f"{activity.department.name if activity.department_id else 'not set'}. "
                        f"Reporting period: {activity.reporting_period.name}. Category: {activity.category.name}. "
                        f"Scope 3 category: {activity.scope3_category.name if activity.scope3_category_id else 'not applicable'}. "
                        f"Activity date: {activity.activity_date}. Quantity: {decimal_to_float(activity.quantity):.2f} {activity.unit.code}. "
                        f"Total CO2e: {decimal_to_float(activity.total_co2e):.2f} tCO2e. Supplier: {activity.supplier_name or 'not set'}. "
                        f"Invoice number: {activity.invoice_number or 'not set'}. Factor code: {activity.factor_code}. "
                        f"Source reference: {activity.source_reference or 'not set'}. Data quality: {activity.data_quality}. "
                        f"Notes: {activity.notes or 'none'}."
                    ),
                    metadata={
                        "entity": "emission_activity",
                        "organization": activity.organization.name,
                        "organization_id": activity.organization_id,
                        "facility": activity.facility.name,
                        "facility_id": activity.facility_id,
                        "reporting_period": activity.reporting_period.name,
                        "reporting_period_id": activity.reporting_period_id,
                        "category": activity.category.name,
                        "scope": activity.category.scope,
                        "scope3_category": activity.scope3_category.name if activity.scope3_category_id else None,
                        "year": activity.activity_date.year,
                    },
                    keywords={
                        "activity",
                        "approved",
                        activity.activity_name,
                        activity.category.name,
                        activity.category.scope,
                        activity.scope3_category.name if activity.scope3_category_id else "",
                        activity.facility.name,
                        activity.factor_code,
                        activity.supplier_name,
                    },
                )
            )

        for breakdown in emission_breakdowns:
            facility_name = breakdown.facility.name if breakdown.facility_id else "All facilities"
            category_name = breakdown.category.name
            subcategory_name = breakdown.subcategory.name if breakdown.subcategory_id else "none"
            scope3_name = breakdown.scope3_category.name if breakdown.scope3_category_id else "none"
            gas_name = breakdown.gas_type.gas_name if breakdown.gas_type_id else "all gases"
            documents.append(
                make_document(
                    source=f"Emission Breakdown: {breakdown.organization.name} {breakdown.reporting_period.name} {breakdown.scope} {category_name}",
                    content=(
                        f"Emission breakdown for {breakdown.organization.name}. Facility: {facility_name}. "
                        f"Reporting period: {breakdown.reporting_period.name}. Scope: {breakdown.scope}. "
                        f"Category: {category_name}. Subcategory: {subcategory_name}. "
                        f"Scope 3 category: {scope3_name}. Gas type: {gas_name}. "
                        f"Total CO2e: {decimal_to_float(breakdown.total_co2e):.2f} tCO2e. "
                        f"Total quantity: {decimal_to_float(breakdown.total_quantity):.2f}."
                    ),
                    metadata={
                        "entity": "emission_breakdown",
                        "organization": breakdown.organization.name,
                        "organization_id": breakdown.organization_id,
                        "facility": facility_name,
                        "facility_id": breakdown.facility_id,
                        "reporting_period": breakdown.reporting_period.name,
                        "reporting_period_id": breakdown.reporting_period_id,
                        "scope": breakdown.scope,
                        "category": category_name,
                        "subcategory": subcategory_name if subcategory_name != "none" else None,
                        "scope3_category": scope3_name if scope3_name != "none" else None,
                        "gas_type": gas_name if gas_name != "all gases" else None,
                    },
                    keywords={
                        "breakdown",
                        "scope",
                        breakdown.scope,
                        category_name,
                        subcategory_name,
                        scope3_name,
                        gas_name,
                        facility_name,
                        breakdown.reporting_period.name,
                    },
                )
            )

        for air_emission in air_emissions:
            documents.append(
                make_document(
                    source=f"Air Emission: {air_emission.facility.name} {air_emission.pollutant_type}",
                    content=(
                        f"Air emission record for facility {air_emission.facility.name} in organization "
                        f"{air_emission.facility.organization.name}. Reporting period: {air_emission.reporting_period.name}. "
                        f"Pollutant type: {air_emission.pollutant_type}. Amount: {decimal_to_float(air_emission.amount):.2f} "
                        f"{air_emission.unit.code}."
                    ),
                    metadata={
                        "entity": "air_emission",
                        "organization": air_emission.facility.organization.name,
                        "organization_id": air_emission.facility.organization_id,
                        "facility": air_emission.facility.name,
                        "facility_id": air_emission.facility_id,
                        "reporting_period": air_emission.reporting_period.name,
                        "reporting_period_id": air_emission.reporting_period_id,
                        "pollutant_type": air_emission.pollutant_type,
                    },
                    keywords={
                        "air emission",
                        "pollutant",
                        air_emission.pollutant_type,
                        air_emission.facility.name,
                        air_emission.reporting_period.name,
                    },
                )
            )

        return documents


def build_documents() -> list[dict[str, object]]:
    """Preserve the legacy builder entrypoint for existing callers."""
    return CarbonDocumentBuilder().build()


DocumentBuilder = BaseDocumentBuilder
