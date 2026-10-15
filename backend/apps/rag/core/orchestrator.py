import logging
import os
import re
import time
import hashlib

from rest_framework.response import Response

from apps.company.models import Facility
from apps.summary.dashboard_views import DashboardViewSet, SCOPE_LABELS
from apps.summary.models import EnergySummary, MonthlyEmissionSummary, ReductionProject

from ..types import ChatTurn, RetrievedDocument, SearchScope
from .cache import TTLCache
from .common import (
    DEFAULT_EMPTY_RAG_FALLBACK,
    expand_relative_time_query,
    expand_temporal_query,
    extract_month_year_pairs,
    extract_scope_filters,
    extract_years,
    format_number,
    is_definition_query,
    tokenize,
)


logger = logging.getLogger(__name__)

OUT_OF_DOMAIN_RESPONSES = [
    (
        "I'm not sure I can help with that. "
        "I can answer CarbonView-related questions about emissions, energy, water, "
        "waste, facilities, and sustainability reports. "
        "What would you like to know?"
    ),
    (
        "That's outside my current scope. "
        "Try asking CarbonView-related questions about your Scope 1, 2, or 3 emissions, "
        "energy consumption, water usage, or reduction projects."
    ),
    (
        "I focus on CarbonView-related questions and sustainability data. "
        "You can ask me about emission totals, facility breakdowns, "
        "carbon credits, or monthly trends."
    ),
]
ASSISTANT_IDENTITY_FALLBACK = (
    "I am the CarbonView Assistant. I can help with CarbonView-related questions such as emissions, scopes, "
    "facilities, reporting periods, energy, water, waste, and sustainability insights."
)
DECLARATIVE_STATEMENT_FALLBACK = "Thanks for sharing! Got a question about your emissions data?"
GREETING_FALLBACK = (
    "Hello! I'm the CarbonView AI Sustainability Assistant. "
    "I can help you with emissions data, energy, water, waste, "
    "facilities, and sustainability insights. "
    "What would you like to know?"
)
UI_CONTEXT_QUESTION_FALLBACK = (
    "I can see you're pointing at something on the dashboard. Could you tell me which section or metric you mean? "
    "For example: 'explain the Scope breakdown' or 'what is the energy summary?'"
)
UNSUPPORTED_SCOPE_FALLBACK = (
    "CarbonView currently supports Scope 1, Scope 2, and Scope 3 emissions. "
    "Scope {scope} is not supported in this assistant."
)

_ASSISTANT_IDENTITY_PATTERNS = (
    r"\bwhat(?:'s| is)? your name\b",
    r"\bwho are you\b",
    r"\bare you (?:a |an )?assistant\b",
    r"\bwhat are you\b",
    r"\byour name\b",
)

_SCOPE_LIST_PATTERN = re.compile(r"\bscopes?\s*([123](?:\s*(?:,|and)?\s*[123]){1,2})\b")
_DASHBOARD_GLOSSARY_TOPIC_MAP = {
    "resource and transition snapshot": "resource_transition_snapshot",
    "performance signals": "performance_signals",
    "selected-year highlights": "performance_signals",
    "facility footprint map": "facility_footprint_map",
    "global facility map": "facility_footprint_map",
    "facility locations": "facility_footprint_map",
    "scope breakdown": "scope_breakdown",
    "scope-wise breakdown": "scope_breakdown",
    "scope 2 split": "scope_2_split",
    "energy": "energy_summary",
    "renewable energy": "energy_summary",
    "water usage": "water_usage",
    "waste handled": "waste_summary",
    "carbon credits": "carbon_credits",
    "credits retired": "credits_retired",
    "retired credits": "credits_retired",
    "total retired": "total_retired",
    "reduction projects": "reduction_projects",
    "projects tracked": "projects_tracked",
    "water categories": "water_categories",
    "emissions forecast": "emissions_forecast",
    "recent trend estimate": "emissions_forecast",
    "next month estimate": "next_month_estimate",
    "forecast insights": "forecast_insights",
    "latest recorded month": "forecast_insights",
    "month-over-month change": "forecast_insights",
    "latest month total": "forecast_insights",
    "latest reporting month": "performance_signals",
    "peak period": "performance_signals",
    "top emission scope": "performance_signals",
    "total emissions": "total_emissions",
    "emissions trend": "monthly_emission_summary",
}
_REPORT_DEFINITION_PATTERNS = (
    r"^what(?:'s| is)\s+reports?\b",
    r"^tell me about\s+reports?\b",
    r"^explain\s+reports?\b",
)
_DASHBOARD_HOME_SNAPSHOT_CACHE = TTLCache[tuple[object, ...], dict[str, object]](
    maxsize=64,
    ttl_secs=60.0,
)
_DASHBOARD_HOME_VALUE_TOPICS = (
    ("resource and transition snapshot", "resource_transition_snapshot_value"),
    ("selected-year highlights", "performance_signals_value"),
    ("performance signals", "performance_signals_value"),
    ("latest reporting month", "latest_reporting_month_value"),
    ("latest recorded month", "forecast_latest_recorded_month_value"),
    ("month-over-month change", "forecast_month_over_month_change_value"),
    ("latest month total", "forecast_latest_month_total_value"),
    ("peak period", "peak_period_value"),
    ("top emission scope", "top_emission_scope_value"),
    ("scope 2 split", "scope_2_split_value"),
    ("scope breakdown", "scope_breakdown_value"),
    ("emissions forecast", "emissions_forecast_value"),
    ("recent trend estimate", "emissions_forecast_value"),
    ("next month estimate", "next_month_estimate_value"),
    ("forecast insights", "forecast_insights_value"),
    ("facility footprint map", "facility_footprint_map_value"),
    ("global facility map", "facility_footprint_map_value"),
    ("facility locations", "facility_footprint_map_value"),
    ("total emissions", "total_emissions_value"),
    ("emissions trend", "emissions_trend_value"),
    ("renewable energy", "renewable_energy_value"),
    ("water usage", "water_usage_value"),
    ("waste handled", "waste_handled_value"),
    ("credits retired", "credits_retired_value"),
    ("retired credits", "credits_retired_value"),
    ("credits were retired", "credits_retired_value"),
    ("how many credits", "credits_retired_value"),
    ("credits have been retired", "credits_retired_value"),
    ("total retired", "total_retired_value"),
    ("projects tracked", "projects_tracked_value"),
    ("water categories", "water_categories_value"),
    ("carbon credits", "carbon_credits_value"),
    ("reduction projects", "reduction_projects_value"),
    ("scope 1", "scope_1_value"),
    ("scope 2", "scope_2_value"),
    ("scope 3", "scope_3_value"),
    ("energy", "energy_value"),
    ("energy source", "energy_value"),
    ("energy sources", "energy_value"),
)
_DASHBOARD_HOME_VALUE_INTENT_PHRASES = {
    "show",
    "show me",
    "give",
    "give me",
    "how much",
    "how many",
    "list",
    "current",
    "latest",
    "recent",
    "total",
    "totals",
    "value",
    "values",
    "count",
    "share",
    "status",
    "which",
    "where",
}
_DASHBOARD_HOME_NON_VALUE_PHRASES = {
    "what is",
    "what's",
    "what are",
    "define",
    "definition",
    "meaning",
    "tell me about",
    "explain",
}
_DASHBOARD_HOME_TOPIC_ALIAS_OVERRIDES = {
    "resource_transition_snapshot_value": ("transition snapshot", "resource snapshot"),
    "performance_signals_value": ("year highlights", "selected year highlights"),
    "facility_footprint_map_value": ("facility map", "footprint map"),
    "scope_2_split_value": ("scope two split", "scope2 split"),
    "scope_breakdown_value": ("emission breakdown", "scope wise breakdown"),
    "emissions_forecast_value": ("forecast", "emission forecast"),
    "latest_reporting_month_value": ("reporting month",),
    "carbon_credits_value": ("credits",),
    "reduction_projects_value": ("projects",),
    "energy_value": ("energy summary",),
}
_DASHBOARD_HOME_AMBIGUOUS_VALUE_TOPICS = {
    "scope_1_value",
    "scope_2_value",
    "scope_3_value",
    "energy_value",
    "carbon_credits_value",
    "reduction_projects_value",
}
_DASHBOARD_HOME_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {}
for _phrase, _topic in _DASHBOARD_HOME_VALUE_TOPICS:
    _DASHBOARD_HOME_TOPIC_ALIASES.setdefault(_topic, [])
    _DASHBOARD_HOME_TOPIC_ALIASES[_topic].append(_phrase)
for _topic, _aliases in _DASHBOARD_HOME_TOPIC_ALIAS_OVERRIDES.items():
    _DASHBOARD_HOME_TOPIC_ALIASES.setdefault(_topic, [])
    _DASHBOARD_HOME_TOPIC_ALIASES[_topic].extend(_aliases)
_DASHBOARD_HOME_TOPIC_ALIASES = {
    topic: tuple(
        dict.fromkeys(alias.strip().lower() for alias in aliases if str(alias).strip())
    )
    for topic, aliases in _DASHBOARD_HOME_TOPIC_ALIASES.items()
}
_DASHBOARD_GLOSSARY_FALLBACKS = {
    "resource_transition_snapshot": (
        "Glossary: Resource and Transition Snapshot",
        "The Resource and transition snapshot is a dashboard section that summarizes operational resource "
        "and transition indicators such as energy use, renewable energy share, water usage, waste handled, "
        "retired credits, tracked reduction projects, and water category counts for the current dashboard selection.",
    ),
    "performance_signals": (
        "Glossary: Performance Signals",
        "The Performance signals section highlights dashboard trend indicators such as the latest reporting month, "
        "peak period, top emission scope, and year-over-year emissions change so users can quickly interpret momentum.",
    ),
    "facility_footprint_map": (
        "Glossary: Facility Footprint Map",
        "The Facility footprint map displays the facilities in the current dashboard context with their geographic details, "
        "activity status, and carbon-neutral indicators so users can inspect the physical footprint behind the data.",
    ),
    "scope_breakdown": (
        "Glossary: Scope Breakdown",
        "The Scope breakdown view shows how the dashboard distributes emissions across the major greenhouse-gas scopes, "
        "including each scope's share of the total footprint and the contributing emission categories underneath.",
    ),
    "scope_2_split": (
        "Glossary: Scope 2 Split",
        "The Scope 2 split compares location-based and market-based Scope 2 emissions for the current dashboard filters "
        "so users can understand purchased-energy emissions under both accounting methods.",
    ),
    "energy_summary": (
        "Glossary: Energy Summary",
        "Energy Summary is the dashboard concept and Django model that rolls up a facility's energy use for a reporting period. "
        "It covers total_energy, renewable_energy, and non_renewable_energy, all stored in the linked unit such as kWh or MWh, "
        "and it powers the Energy and Renewable energy cards in the dashboard snapshot. "
        "To get the actual values, ask 'What are the total, renewable, and non-renewable energy values for North Plant in FY2025?'",
    ),
    "water_usage": (
        "Glossary: Water Usage",
        "Water Usage is the dashboard concept and Django model used to track a facility's water records for a reporting period. "
        "It stores category, amount, and unit for each water line item, and the dashboard aggregates those records into total_water_usage "
        "plus the Water categories list. To get the actual values, ask 'Show water usage by category for South Plant this year.'",
    ),
    "waste_summary": (
        "Glossary: Waste Summary",
        "Waste Summary is the dashboard concept and Django model that summarizes waste handled by a facility for a reporting period. "
        "It covers total_waste, hazardous, non_hazardous, recycled_percentage, and unit, so the dashboard can show both waste totals "
        "and recycling performance. To get the actual values, ask 'What are the total, hazardous, and non-hazardous waste values for East Campus?'",
    ),
    "carbon_credits": (
        "Glossary: Carbon Credits",
        "Carbon Credits are dashboard records for offset projects linked to a facility. They store project_name, source, registry_name, "
        "serial_number, vintage_year, quantity_tco2e, purchase_date, retirement_date, and status, with quantity_tco2e measured in tCO2e. "
        "To get the actual values, ask 'Show retired carbon credits for this facility with quantity and vintage year.'",
    ),
    "credits_retired": (
        "Glossary: Credits Retired",
        "Credits retired is the dashboard aggregate that sums the quantity_tco2e of retired carbon credits in the current dashboard selection. "
        "It reflects retired credit quantities in tCO2e and is derived from carbon credit records rather than from emission-activity totals. "
        "To get the actual values, ask 'How many credits were retired for this dashboard selection?'",
    ),
    "total_retired": (
        "Glossary: Total Retired",
        "Total retired is the summary number shown in the Carbon credits card for the current dashboard filters. "
        "It represents the total retired carbon-credit quantity in tCO2e, aggregated from credit records whose status is retired. "
        "To get the actual values, ask 'Show the total retired carbon credits for this year.'",
    ),
    "reduction_projects": (
        "Glossary: Reduction Projects",
        "Reduction Projects are dashboard initiatives that track expected and achieved emissions savings at a facility. "
        "They store name, description, start_date, end_date, expected_reduction_tco2e, and actual_reduction_tco2e, with reduction values measured in tCO2e. "
        "To get the actual values, ask 'List the reduction projects for North Plant with expected and actual reductions.'",
    ),
    "projects_tracked": (
        "Glossary: Projects Tracked",
        "Projects tracked is the dashboard count of reduction projects included in the current filters. "
        "It represents how many reduction-project records are in scope, while the project details themselves carry expected_reduction_tco2e "
        "and actual_reduction_tco2e in tCO2e. To get the actual values, ask 'How many reduction projects are tracked on this dashboard?'",
    ),
    "water_categories": (
        "Glossary: Water Categories",
        "Water categories is the dashboard count and grouping of distinct water-usage categories in the current selection. "
        "Those categories come from Water Usage records, which store category, amount, and unit for each water entry and are commonly measured in units such as m3. "
        "To get the actual values, ask 'Show water categories with their amounts and units for this dashboard.'",
    ),
    "emissions_forecast": (
        "Glossary: Emissions Forecast",
        "Emissions Forecast is the dashboard widget that estimates the next month's emissions from recent monthly summary data. "
        "It uses recent monthly totals to show a next-month estimate, trendPercent, latestMonthLabel, latestMonthTotal, and short forecast insights, "
        "with emissions shown in tons CO2e. To get the actual values, ask 'What is the emissions forecast and latest month total shown on the dashboard?'",
    ),
    "next_month_estimate": (
        "Glossary: Next Month Estimate",
        "Next Month Estimate is the headline number inside the Emissions Forecast widget. "
        "It projects the next month's emissions in tons CO2e using recent monthly totals, and it is displayed alongside the recent trend estimate "
        "and latest month context. To get the actual values, ask 'What is the next month estimate in the emissions forecast?'",
    ),
    "forecast_insights": (
        "Glossary: Forecast Insights",
        "Forecast Insights is the explanatory list underneath the Emissions Forecast widget. "
        "It summarizes the latest recorded month, month-over-month change, latest month total, and the direction implied by the recent forecasting trend. "
        "To get the actual values, ask 'Show the forecast insights including latest month and month-over-month change.'",
    ),
    "monthly_emission_summary": (
        "Glossary: Monthly Emission Summary",
        "Monthly Emission Summary is the model and dashboard series behind monthly and yearly emissions charts. "
        "It stores year, month, scope, total_co2e, organization, facility, and reporting_period so CarbonView can build monthly_emissions, "
        "yearly_emissions, latest month, and peak period insights in tCO2e. To get the actual values, ask 'Show the monthly emission summary for Scope 2 in 2025.'",
    ),
    "reports_analytics": (
        "Glossary: Reports & Analytics",
        "Reports & Analytics is the CarbonView reporting view that turns dashboard summary data into downloadable annual and quarterly reporting views. "
        "It covers report title, date, type, emissions, and change, and it also supports ESG Excel export by start_date and end_date for custom reporting windows. "
        "To get the actual values, ask 'Show the available annual and quarterly reports with emissions and change.'",
    ),
}


def _extract_scope_mentions(query: str) -> set[str]:
    normalized = (query or "").lower()
    scopes = set(extract_scope_filters(normalized))
    for match in _SCOPE_LIST_PATTERN.finditer(normalized):
        for scope_number in re.findall(r"[123]", match.group(1)):
            scopes.add(f"S{scope_number}")
    return scopes


def _unsupported_scope_number(query: str) -> int | None:
    normalized = (query or "").lower()
    if "scope" not in normalized and not re.search(r"\bs\d\b", normalized):
        return None
    match = re.search(r"\b(?:scope|scop|cope)\s*(\d)\b|\bs\s*(\d)\b|\bs(\d)\b", normalized)
    if not match:
        return None
    for group in match.groups():
        if group is not None:
            value = int(group)
            if value not in {1, 2, 3}:
                return value
    return None


def unsupported_scope_message(query: str) -> str | None:
    scope_number = _unsupported_scope_number(query)
    if scope_number is None:
        return None
    return UNSUPPORTED_SCOPE_FALLBACK.format(scope=scope_number)

def _preferred_glossary_topic(query: str) -> str | None:
    normalized = (query or "").lower()
    if any(re.search(pattern, normalized) for pattern in _REPORT_DEFINITION_PATTERNS):
        return "reports_analytics"
    if "carbon view" in normalized or "carbonview" in normalized:
        return "carbonview"
    if "breakdown" in normalized and _extract_scope_mentions(normalized):
        return "scope_breakdown"
    if any(
        phrase in normalized
        for phrase in {
            "ai sustainability assistant",
            "sustainability assistant",
            "version",
            "chatbot",
            "what can you do",
            "what do you do",
            "what are you capable of",
        }
    ):
        return "assistant_identity"
    for phrase, topic in _DASHBOARD_GLOSSARY_TOPIC_MAP.items():
        if phrase in normalized:
            return topic
    scopes = sorted(_extract_scope_mentions(query or ""))
    if len(scopes) != 1:
        return None
    return f"scope_{scopes[0][-1]}"


def _dashboard_glossary_document(topic: str | None) -> RetrievedDocument | None:
    if not topic:
        return None
    fallback = _DASHBOARD_GLOSSARY_FALLBACKS.get(topic)
    if fallback is None:
        return None
    source, content = fallback
    return RetrievedDocument(
        source=source,
        content=content,
        metadata={"entity": "glossary", "topic": topic, "synthesized": True},
        score=1.0,
    )


def _prioritize_definition_documents(query: str, documents):
    preferred_topic = _preferred_glossary_topic(query)
    if not preferred_topic:
        return documents

    preferred = [doc for doc in documents if doc.metadata.get("entity") == "glossary" and doc.metadata.get("topic") == preferred_topic]
    if not preferred:
        return documents

    remaining = [doc for doc in documents if doc not in preferred]
    return preferred + remaining


def _documents_are_glossary_only(documents) -> bool:
    return bool(documents) and all(doc.metadata.get("entity") == "glossary" for doc in documents)


def _documents_contain_numeric_evidence(documents) -> bool:
    evidence_entities = {
        "emission_activity",
        "emission_breakdown",
        "monthly_summary",
        "energy_summary",
        "water_usage",
        "waste_summary",
        "carbon_credit",
        "reduction_project",
    }
    evidence_metadata_fields = {
        "year",
        "month",
        "reporting_period",
        "scope",
        "total_co2e",
        "amount",
        "quantity_tco2e",
        "vintage_year",
    }
    for doc in documents or []:
        entity = str((doc.metadata or {}).get("entity") or "")
        if entity in evidence_entities:
            return True
        if any((doc.metadata or {}).get(field) not in {None, ""} for field in evidence_metadata_fields):
            return True
    return False


def _is_explicit_numeric_lookup(query: str) -> bool:
    normalized = (query or "").lower()
    if any(term in normalized for term in {"compare", "comparison", "vs", "versus", "graph", "chart", "plot", "trend"}):
        return False
    has_metric = any(term in normalized for term in {"emission", "emissions", "total", "value", "values", "amount", "summary"})
    has_scope = bool(_extract_scope_mentions(normalized))
    has_time = bool(
        extract_month_year_pairs(normalized)
        or extract_years(normalized)
        or any(term in normalized for term in {"this year", "current year", "last year", "previous year", "reporting period", "fy"})
    )
    return has_metric and (has_scope or has_time)


def _dashboard_query_filter_values(query: str, scope: SearchScope) -> tuple[int | None, int | None]:
    years = sorted(extract_years(query))
    month_year_pairs = extract_month_year_pairs(query)
    if scope.reporting_period_id:
        return None, None
    if len(month_year_pairs) == 1:
        year, month = month_year_pairs[0]
        return int(year), int(month)
    if len(years) == 1:
        return int(years[0]), None
    return None, None


def _dashboard_context_label(snapshot: dict[str, object]) -> str:
    entity = dict(snapshot.get("entity") or {})
    facility = dict(entity.get("facility") or {})
    organization = dict(entity.get("organization") or {})
    reporting_period = dict(entity.get("reporting_period") or {})
    filters = dict(snapshot.get("filters") or {})

    context = "for the current dashboard selection"
    if facility.get("name"):
        context = f"for {facility['name']}"
    elif organization.get("name"):
        context = f"for {organization['name']}"

    if reporting_period.get("name"):
        context = f"{context} in {reporting_period['name']}"
    elif filters.get("year"):
        context = f"{context} in {filters['year']}"
    return context


def _dashboard_units_text(units: list[str]) -> str:
    cleaned = [str(unit).strip() for unit in units if str(unit).strip()]
    return ", ".join(cleaned) if cleaned else "units"


def _dashboard_forecast(monthly_emissions: list[dict[str, object]]) -> dict[str, object] | None:
    if not monthly_emissions:
        return None

    sorted_months = sorted(
        monthly_emissions,
        key=lambda item: (int(item.get("year") or 0), int(item.get("month") or 0)),
    )
    latest_month = sorted_months[-1]
    recent_months = sorted_months[-3:]
    month_changes: list[float] = []
    for index in range(1, len(recent_months)):
        month_changes.append(float(recent_months[index]["total_co2e"]) - float(recent_months[index - 1]["total_co2e"]))

    average_monthly_change = sum(month_changes) / len(month_changes) if month_changes else 0.0
    latest_total = float(latest_month["total_co2e"])
    next_month = max(latest_total + average_monthly_change, 0.0)
    previous_month = sorted_months[-2] if len(sorted_months) > 1 else None
    trend_percent = 0.0
    if previous_month and float(previous_month["total_co2e"]) > 0:
        trend_percent = ((latest_total - float(previous_month["total_co2e"])) / float(previous_month["total_co2e"])) * 100

    insight = (
        "Recent trend suggests lower emissions next month."
        if average_monthly_change <= 0
        else "Recent trend suggests emissions may rise next month."
    )
    return {
        "next_month": round(next_month),
        "trend_percent": trend_percent,
        "latest_month_label": f"{latest_month.get('month_name')} {latest_month.get('year')}",
        "latest_month_total": latest_total,
        "insights": [insight],
    }


def _build_dashboard_home_snapshot(scope: SearchScope, query: str) -> dict[str, object]:
    year, month = _dashboard_query_filter_values(query, scope)
    cache_key = (
        scope.organization_id,
        scope.facility_id,
        scope.reporting_period_id,
        year,
        month,
    )
    cached = _DASHBOARD_HOME_SNAPSHOT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    view = DashboardViewSet()
    filters = view._resolve_default_filters(
        {
            "organization_id": scope.organization_id,
            "facility_id": scope.facility_id,
            "reporting_period_id": scope.reporting_period_id,
            "year": year,
            "month": month,
        }
    )

    entity = view._build_entity(filters)
    activity_qs = view._activity_queryset(filters)
    period_qs = view._reporting_period_queryset(filters)
    facility_qs = view._facility_queryset(filters)
    credit_qs = view._credit_queryset(filters)
    reduction_qs = view._reduction_queryset(filters)
    claim_qs = view._claim_queryset(filters)
    energy_qs = view._energy_queryset(filters)
    water_qs = view._water_queryset(filters)
    waste_qs = view._waste_queryset(filters)
    calculation_qs = view._calculation_queryset(filters)

    gross_emissions = view._sum(calculation_qs, "co2e_amount")
    offsets = view._sum(credit_qs, "quantity_tco2e")
    reductions = view._sum(reduction_qs, "actual_reduction_tco2e")
    net_emissions = gross_emissions - offsets - reductions

    scope_totals = {
        code: view._sum(calculation_qs.filter(activity__category__scope=code), "co2e_amount")
        for code in SCOPE_LABELS
    }
    emission_breakdown = view._get_emission_breakdown(calculation_qs)
    scope_breakdown = []
    for code, label in SCOPE_LABELS.items():
        total = scope_totals[code]
        percentage = float((total / gross_emissions * 100) if gross_emissions else 0)
        scope_breakdown.append(
            {
                "code": code,
                "label": label,
                "total_co2e": float(total),
                "percentage": round(percentage, 2),
                "breakdown": emission_breakdown.get(code, []),
            }
        )

    scope2_split = {
        "location_based": float(
            view._sum(
                calculation_qs.filter(
                    activity__category__scope="S2",
                    activity__scope2_method="location_based",
                ),
                "co2e_amount",
            )
        ),
        "market_based": float(
            view._sum(
                calculation_qs.filter(
                    activity__category__scope="S2",
                    activity__scope2_method="market_based",
                ),
                "co2e_amount",
            )
        ),
    }

    yearly_emissions = view._build_yearly_emissions(filters, calculation_qs)
    monthly_emissions = view._build_monthly_emissions(filters, calculation_qs)
    snapshot = {
        "filters": filters,
        "entity": entity,
        "geo": view._build_geo(filters, facility_qs),
        "kpis": {
            "gross_emissions": float(gross_emissions),
            "offsets": float(offsets),
            "reductions": float(reductions),
            "net_emissions": float(net_emissions),
            "is_carbon_neutral": net_emissions <= 0,
            "approved_activities": activity_qs.count(),
            "facilities_count": facility_qs.count(),
            "reporting_periods_count": period_qs.count(),
        },
        "highlights": view._build_highlights(
            gross_emissions=gross_emissions,
            net_emissions=net_emissions,
            scope_totals=scope_totals,
            yearly_emissions=yearly_emissions,
            monthly_emissions=monthly_emissions,
            energy_qs=energy_qs,
            water_qs=water_qs,
            waste_qs=waste_qs,
        ),
        "scope_breakdown": scope_breakdown,
        "scope2_split": scope2_split,
        "yearly_emissions": yearly_emissions,
        "monthly_emissions": monthly_emissions,
        "energy": view._build_energy_card(energy_qs),
        "water": view._build_water_card(water_qs),
        "waste": view._build_waste_card(waste_qs),
        "carbon_credits": [
            {
                "project_name": item.project_name,
                "registry_name": item.registry_name,
                "serial_number": item.serial_number,
                "quantity_tco2e": float(item.quantity_tco2e),
                "status": item.status,
            }
            for item in credit_qs.order_by("-vintage_year", "project_name")[:10]
        ],
        "reduction_projects": [
            {
                "name": item.name,
                "expected_reduction_tco2e": float(item.expected_reduction_tco2e),
                "actual_reduction_tco2e": float(item.actual_reduction_tco2e),
            }
            for item in reduction_qs[:10]
        ],
        "neutrality_claims": [
            {
                "name": item.name,
                "status": item.status,
                "reporting_period": item.reporting_period.name,
                "gross_emissions": float(item.gross_emissions),
                "reductions": float(item.reductions),
                "offsets_retired": float(item.offsets_retired),
                "net_emissions": float(item.net_emissions),
            }
            for item in claim_qs.select_related("reporting_period").order_by("-created_at")[:10]
        ],
    }
    snapshot["forecast"] = _dashboard_forecast(snapshot["monthly_emissions"])
    _DASHBOARD_HOME_SNAPSHOT_CACHE.set(cache_key, snapshot)
    return snapshot


def _dashboard_home_definition_query(normalized: str) -> bool:
    has_definition_phrase = any(phrase in normalized for phrase in _DASHBOARD_HOME_NON_VALUE_PHRASES)
    if not has_definition_phrase:
        return False
    has_value_cue = any(phrase in normalized for phrase in _DASHBOARD_HOME_VALUE_INTENT_PHRASES)
    has_filter_cue = bool(
        extract_month_year_pairs(normalized)
        or extract_years(normalized)
        or any(term in normalized for term in {"this year", "last year", "current year", "reporting period"})
    )
    return not (has_value_cue or has_filter_cue)


def _dashboard_home_topic_score(normalized: str, query_tokens: set[str], topic: str) -> float:
    best_score = 0.0
    for alias in _DASHBOARD_HOME_TOPIC_ALIASES.get(topic, ()):
        alias_tokens = set(tokenize(alias))
        if not alias_tokens:
            continue
        if alias in normalized:
            best_score = max(best_score, 3.0 + (0.1 * min(len(alias_tokens), 4)))
            continue

        overlap = len(query_tokens & alias_tokens)
        if overlap == 0:
            continue

        coverage = overlap / len(alias_tokens)
        query_coverage = overlap / max(len(query_tokens), 1)
        if len(alias_tokens) == 1:
            score = 1.1 + query_coverage
        elif overlap >= 2 and coverage >= 0.5:
            score = coverage + min(query_coverage, 0.8) + (0.15 * overlap)
        else:
            continue
        best_score = max(best_score, score)
    return best_score


def _dashboard_home_candidate_topic(normalized: str) -> str | None:
    query_tokens = set(tokenize(normalized))
    if not query_tokens:
        return None

    explicit_value_intent = any(phrase in normalized for phrase in _DASHBOARD_HOME_VALUE_INTENT_PHRASES)
    has_filter_cue = bool(
        extract_month_year_pairs(normalized)
        or extract_years(normalized)
    )
    is_short_lookup = len(query_tokens) <= 6

    best_topic: str | None = None
    best_score = 0.0
    for topic in _DASHBOARD_HOME_TOPIC_ALIASES:
        score = _dashboard_home_topic_score(normalized, query_tokens, topic)
        if score > best_score:
            best_score = score
            best_topic = topic

    if best_topic is None:
        return None

    if best_topic in _DASHBOARD_HOME_AMBIGUOUS_VALUE_TOPICS and not (explicit_value_intent or has_filter_cue):
        return None

    if best_score >= 3.0:
        return best_topic
    if explicit_value_intent and best_score >= 1.6:
        return best_topic
    if has_filter_cue and best_score >= 1.6:
        return best_topic
    if is_short_lookup and best_score >= 2.0:
        return best_topic
    return None


def _dashboard_home_value_topic(query: str) -> str | None:
    normalized = (query or "").strip().lower()
    if not normalized:
        return None
    scope_mentions = sorted(_extract_scope_mentions(normalized))
    if "breakdown" in normalized:
        if len(scope_mentions) == 1:
            return f"scope_{scope_mentions[0][-1]}_value"
        if "scope breakdown" in normalized or "scope-wise breakdown" in normalized:
            return "scope_breakdown_value"
    if (
        ("reduction project" in normalized or "reduction projects" in normalized or "projects tracked" in normalized)
        and not any(term in normalized for term in {"facility", "facilities", "site", "sites", "plant", "plants", "campus", "hub", "centre", "center"})
    ):
        return "reduction_projects_value"
    if _dashboard_home_definition_query(normalized):
        return None
    if any(term in normalized for term in {"compare", "comparison", "vs", "versus", "graph", "chart", "plot"}):
        return None

    return _dashboard_home_candidate_topic(normalized)


def _format_dashboard_home_value(topic: str, snapshot: dict[str, object]) -> str | None:
    context = _dashboard_context_label(snapshot)
    kpis = dict(snapshot.get("kpis") or {})
    highlights = dict(snapshot.get("highlights") or {})
    energy = dict(snapshot.get("energy") or {})
    water = dict(snapshot.get("water") or {})
    waste = dict(snapshot.get("waste") or {})
    scope_breakdown = list(snapshot.get("scope_breakdown") or [])
    scope2_split = dict(snapshot.get("scope2_split") or {})
    carbon_credits = list(snapshot.get("carbon_credits") or [])
    reduction_projects = list(snapshot.get("reduction_projects") or [])
    geo = dict(snapshot.get("geo") or {})
    forecast = dict(snapshot.get("forecast") or {})

    def scope_item(scope_code: str) -> dict[str, object] | None:
        return next((item for item in scope_breakdown if item.get("code") == scope_code), None)

    def scope_breakdown_lines(item: dict[str, object]) -> list[str]:
        breakdown_rows = list(item.get("breakdown") or [])
        lines: list[str] = []
        for row in breakdown_rows[:5]:
            category = str(row.get("category") or "Uncategorized").strip()
            subcategory = str(row.get("subcategory") or "").strip()
            gas_type = str(row.get("gas_type") or "").strip()
            detail_parts = [part for part in [subcategory, gas_type] if part]
            detail = " | ".join(detail_parts)
            amount = format_number(float(row.get("total_co2e") or 0.0))
            lines.append(f"{category}: {detail + ' | ' if detail else ''}{amount} tCO2e")
        return lines

    if topic == "total_emissions_value":
        if "gross_emissions" not in kpis:
            return None
        scope_summary = "; ".join(
            f"{item['label']} {format_number(float(item['total_co2e']))} tCO2e ({float(item['percentage']):.2f}% share)"
            for item in scope_breakdown
            if item.get("label")
        )
        return (
            f"Total emissions {context} are {format_number(float(kpis['gross_emissions']))} tCO2e. "
            f"Scope breakdown: {scope_summary}."
        )

    if topic in {"scope_1_value", "scope_2_value", "scope_3_value"}:
        scope_code = topic.split("_")[1].upper()
        item = scope_item(f"S{scope_code}")
        if item is None:
            return None
        summary = (
            f"{item['label']} emissions {context} are {format_number(float(item['total_co2e']))} tCO2e "
            f"({float(item['percentage']):.2f}% of total footprint)."
        )
        breakdown_lines = scope_breakdown_lines(item)
        if not breakdown_lines:
            return summary
        return summary + " Breakdown: " + "; ".join(breakdown_lines) + "."

    if topic == "scope_breakdown_value":
        if not scope_breakdown:
            return None
        parts = [
            f"{item['label']} {format_number(float(item['total_co2e']))} tCO2e ({float(item['percentage']):.2f}% share)"
            for item in scope_breakdown
        ]
        return f"Scope breakdown {context}: " + "; ".join(parts) + "."

    if topic == "scope_2_split_value":
        return (
            f"Scope 2 split {context}: location-based {format_number(float(scope2_split.get('location_based') or 0.0))} tCO2e; "
            f"market-based {format_number(float(scope2_split.get('market_based') or 0.0))} tCO2e."
        )

    if topic == "performance_signals_value":
        latest_month = dict(highlights.get("latest_month") or {})
        peak_month = dict(highlights.get("peak_month") or {})
        top_scope = dict(highlights.get("top_emission_scope") or {})
        if not latest_month and not peak_month and not top_scope:
            return None
        return (
            f"Performance signals {context}: latest reporting month {latest_month.get('month_name', 'Not available')} "
            f"{latest_month.get('year', '')}; peak period {peak_month.get('month_name', 'Not available')} "
            f"{peak_month.get('year', '')}"
            + (
                f" at {format_number(float(peak_month.get('total_co2e') or 0.0))} tCO2e"
                if peak_month.get("total_co2e") is not None
                else ""
            )
            + f"; top emission scope {top_scope.get('label') or 'Not available'}"
            + (
                f" at {format_number(float(top_scope.get('total_co2e') or 0.0))} tCO2e"
                if top_scope.get("total_co2e") is not None
                else ""
            )
            + f"; year-over-year change {float(highlights.get('year_over_year_change_percentage') or 0.0):.2f}%."
        )

    if topic == "latest_reporting_month_value":
        latest_month = dict(highlights.get("latest_month") or {})
        if not latest_month:
            return None
        return f"The latest reporting month {context} is {latest_month.get('month_name')} {latest_month.get('year')}."

    if topic == "peak_period_value":
        peak_month = dict(highlights.get("peak_month") or {})
        if not peak_month:
            return None
        return (
            f"The peak period {context} is {peak_month.get('month_name')} {peak_month.get('year')} "
            f"with {format_number(float(peak_month.get('total_co2e') or 0.0))} tCO2e."
        )

    if topic == "top_emission_scope_value":
        top_scope = dict(highlights.get("top_emission_scope") or {})
        if not top_scope:
            return None
        return (
            f"The top emission scope {context} is {top_scope.get('label') or 'Not available'} "
            f"at {format_number(float(top_scope.get('total_co2e') or 0.0))} tCO2e."
        )

    if topic == "resource_transition_snapshot_value":
        renewable_share = float(highlights.get("renewable_energy_share_percentage") or 0.0)
        credits_total = sum(float(item.get("quantity_tco2e") or 0.0) for item in carbon_credits)
        return (
            f"Resource and transition snapshot {context}: energy {format_number(float(energy.get('total_energy') or 0.0))} "
            f"{_dashboard_units_text(list(energy.get('units') or []))}; renewable energy "
            f"{format_number(float(energy.get('renewable_energy') or 0.0))} {_dashboard_units_text(list(energy.get('units') or []))} "
            f"({renewable_share:.2f}% share); water usage {format_number(float(water.get('total_water_usage') or 0.0))} "
            f"{_dashboard_units_text(list(water.get('units') or []))}; waste handled {format_number(float(waste.get('total_waste') or 0.0))} "
            f"{_dashboard_units_text(list(waste.get('units') or []))} with average recycled "
            f"{float(waste.get('average_recycled_percentage') or 0.0):.2f}%; credits retired {format_number(credits_total)} tCO2e; "
            f"projects tracked {len(reduction_projects)}; water categories {len(list(water.get('categories') or []))}."
        )

    if topic == "energy_value":
        return (
            f"Energy {context} totals {format_number(float(energy.get('total_energy') or 0.0))} "
            f"{_dashboard_units_text(list(energy.get('units') or []))}. Renewable energy is "
            f"{format_number(float(energy.get('renewable_energy') or 0.0))} {_dashboard_units_text(list(energy.get('units') or []))}, "
            f"and non-renewable energy is {format_number(float(energy.get('non_renewable_energy') or 0.0))} "
            f"{_dashboard_units_text(list(energy.get('units') or []))}."
        )

    if topic == "renewable_energy_value":
        return (
            f"Renewable energy {context} is {format_number(float(energy.get('renewable_energy') or 0.0))} "
            f"{_dashboard_units_text(list(energy.get('units') or []))}, which is "
            f"{float(highlights.get('renewable_energy_share_percentage') or 0.0):.2f}% of total energy."
        )

    if topic == "water_usage_value":
        return (
            f"Water usage {context} is {format_number(float(water.get('total_water_usage') or 0.0))} "
            f"{_dashboard_units_text(list(water.get('units') or []))} across {len(list(water.get('categories') or []))} categories."
        )

    if topic == "waste_handled_value":
        return (
            f"Waste handled {context} is {format_number(float(waste.get('total_waste') or 0.0))} "
            f"{_dashboard_units_text(list(waste.get('units') or []))}. Hazardous waste is "
            f"{format_number(float(waste.get('hazardous') or 0.0))}, non-hazardous waste is "
            f"{format_number(float(waste.get('non_hazardous') or 0.0))}, and average recycled is "
            f"{float(waste.get('average_recycled_percentage') or 0.0):.2f}%."
        )

    if topic in {"credits_retired_value", "total_retired_value"}:
        credits_total = sum(
            float(item.get("quantity_tco2e") or 0.0)
            for item in carbon_credits
            if str(item.get("status") or "").lower() == "retired"
        )
        if not any(str(item.get("status") or "").lower() == "retired" for item in carbon_credits):
            return f"No retired carbon credits found {context}."
        return f"Credits retired {context} total {format_number(credits_total)} tCO2e."

    if topic == "projects_tracked_value":
        project_names = [str(item.get("name") or "").strip() for item in reduction_projects if str(item.get("name") or "").strip()]
        if project_names:
            return (
                f"Projects tracked {context}: {len(project_names)}. "
                f"Current projects include {', '.join(project_names[:3])}."
            )
        return f"Projects tracked {context}: {len(reduction_projects)}."

    if topic == "water_categories_value":
        categories = list(water.get("categories") or [])
        if not categories:
            return f"Water categories {context}: 0."
        category_summary = "; ".join(
            f"{item.get('category')}: {format_number(float(item.get('amount') or 0.0))} {item.get('unit') or ''}".strip()
            for item in categories[:3]
        )
        return f"Water categories {context}: {len(categories)}. {category_summary}."

    if topic == "carbon_credits_value":
        credits_total = sum(
            float(item.get("quantity_tco2e") or 0.0)
            for item in carbon_credits
            if str(item.get("status") or "").lower() == "retired"
        )
        if not carbon_credits:
            return f"I could not find carbon-credit records {context}."
        project_summary = "; ".join(
            f"{item.get('project_name')}: {format_number(float(item.get('quantity_tco2e') or 0.0))} tCO2e ({item.get('status') or 'status not set'})"
            for item in carbon_credits[:3]
        )
        return (
            f"Carbon credits {context} total {format_number(credits_total)} tCO2e. "
            f"Top listed credits: {project_summary}."
        )

    if topic == "reduction_projects_value":
        if not reduction_projects:
            return f"I could not find reduction projects {context}."
        project_summary = "; ".join(
            f"{item.get('name')}: expected {format_number(float(item.get('expected_reduction_tco2e') or 0.0))} tCO2e, "
            f"actual {format_number(float(item.get('actual_reduction_tco2e') or 0.0))} tCO2e"
            for item in reduction_projects[:3]
        )
        return f"Reduction projects {context}: {len(reduction_projects)} tracked. {project_summary}."

    if topic == "emissions_trend_value":
        latest_year = dict(highlights.get("latest_year") or {})
        latest_month = dict(highlights.get("latest_month") or {})
        if not latest_year and not latest_month:
            return None
        parts: list[str] = []
        if latest_year:
            parts.append(
                f"latest yearly total {format_number(float(latest_year.get('total_co2e') or 0.0))} tCO2e in {latest_year.get('year')}"
            )
        if latest_month:
            parts.append(
                f"latest reporting month {latest_month.get('month_name')} {latest_month.get('year')} at "
                f"{format_number(float(latest_month.get('total_co2e') or 0.0))} tCO2e"
            )
        parts.append(f"year-over-year change {float(highlights.get('year_over_year_change_percentage') or 0.0):.2f}%")
        return f"Emissions trend {context}: " + "; ".join(parts) + "."

    if topic == "emissions_forecast_value":
        if not forecast:
            return None
        return (
            f"Emissions forecast {context}: next month estimate {int(forecast.get('next_month') or 0)} tons CO2e; "
            f"latest recorded month {forecast.get('latest_month_label')}; latest month total "
            f"{format_number(float(forecast.get('latest_month_total') or 0.0))} tons CO2e; month-over-month change "
            f"{float(forecast.get('trend_percent') or 0.0):.2f}%."
        )

    if topic == "next_month_estimate_value":
        if not forecast:
            return None
        return f"The next month estimate {context} is {int(forecast.get('next_month') or 0)} tons CO2e."

    if topic == "forecast_insights_value":
        if not forecast:
            return None
        insights = list(forecast.get("insights") or [])
        insight_text = f" {insights[0]}" if insights else ""
        return (
            f"Forecast insights {context}: latest recorded month {forecast.get('latest_month_label')}; "
            f"month-over-month change {float(forecast.get('trend_percent') or 0.0):.2f}%; latest month total "
            f"{format_number(float(forecast.get('latest_month_total') or 0.0))} tons CO2e.{insight_text}"
        )

    if topic == "forecast_latest_recorded_month_value":
        if not forecast:
            return None
        return f"The latest recorded month in the forecast {context} is {forecast.get('latest_month_label')}."

    if topic == "forecast_month_over_month_change_value":
        if not forecast:
            return None
        return (
            f"The forecast month-over-month change {context} is "
            f"{float(forecast.get('trend_percent') or 0.0):.2f}%."
        )

    if topic == "forecast_latest_month_total_value":
        if not forecast:
            return None
        return (
            f"The latest month total in the forecast {context} is "
            f"{format_number(float(forecast.get('latest_month_total') or 0.0))} tons CO2e."
        )

    if topic == "facility_footprint_map_value":
        locations = list(geo.get("facility_locations") or [])
        if not locations:
            return None
        location_summary = "; ".join(
            ", ".join(
                part
                for part in [item.get("facility_name"), item.get("city"), item.get("state"), item.get("country")]
                if part
            )
            for item in locations[:3]
        )
        return (
            f"Facility footprint map {context} shows {len(locations)} facilities. "
            f"Current locations include {location_summary}."
        )

    return None


def _dashboard_home_value_document(query: str, scope: SearchScope) -> RetrievedDocument | None:
    topic = _dashboard_home_value_topic(query)
    if not topic:
        return None
    snapshot = _build_dashboard_home_snapshot(scope, query)
    answer = _format_dashboard_home_value(topic, snapshot)
    if not answer:
        return None
    return RetrievedDocument(
        source=f"Dashboard Home: {topic}",
        content=answer,
        metadata={"entity": "dashboard_home_value", "topic": topic, "source": "dashboard_home"},
        score=1.0,
    )


def _should_prefer_dashboard_home_value(query: str) -> bool:
    normalized = (query or "").strip().lower()
    if not normalized:
        return False
    return _dashboard_home_value_topic(normalized) is not None


def resolve_response_mode(request) -> str:
    value = str(request.data.get("response_mode") or os.getenv("RAG_RESPONSE_MODE", "enriched")).strip().lower()
    return "minimal" if value == "minimal" else "enriched"


def standardize_tool_result(
    *,
    tool: str,
    route: str,
    data,
    metadata: dict[str, object] | None = None,
    fallback_answer: str = "",
    source: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    return {
        "tool": tool,
        "route": route,
        "data": data,
        "metadata": metadata or {},
        "fallback_answer": fallback_answer,
        "source": source or {},
        **extra,
    }


def best_rag_fallback(query: str, documents):
    wants_definition = is_definition_query(query) or any(
        term in (query or "").lower() for term in {"explain", "simple words", "easy words", "tell me about"}
    )
    documents = _prioritize_definition_documents(query, documents)
    glossary_doc = next((doc for doc in documents if doc.metadata.get("entity") == "glossary"), None)
    if wants_definition and glossary_doc is not None:
        return glossary_doc.content
    return documents[0].content if documents else DEFAULT_EMPTY_RAG_FALLBACK


def build_rag_tool_result(query: str, documents) -> dict[str, object]:
    payload = [
        {
            "source": doc.source,
            "content": doc.content,
            "snippet": doc.snippet,
            "metadata": doc.metadata,
            "score": round(doc.score, 2),
        }
        for doc in documents
    ]
    return standardize_tool_result(
        tool="rag",
        route="rag",
        data=payload,
        metadata={"document_count": len(payload)},
        fallback_answer=best_rag_fallback(query, documents),
        documents=payload,
    )


def sql_has_data(result: dict[str, object]) -> bool:
    return bool((result or {}).get("data"))


def empty_rag_tool_result() -> dict[str, object]:
    return standardize_tool_result(
        tool="rag",
        route="rag",
        data=[],
        metadata={"document_count": 0},
        fallback_answer=DEFAULT_EMPTY_RAG_FALLBACK,
        documents=[],
    )


def _is_assistant_identity_question(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _ASSISTANT_IDENTITY_PATTERNS)


def _varied_out_of_domain(query: str) -> str:
    normalized = str(query or "").strip().lower()
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(OUT_OF_DOMAIN_RESPONSES)
    return OUT_OF_DOMAIN_RESPONSES[index]


def out_of_domain_tool_result(query: str = "", reason: str = "out_of_domain_query") -> dict[str, object]:
    if reason == "declarative_statement":
        fallback = DECLARATIVE_STATEMENT_FALLBACK
    elif reason == "greeting":
        fallback = GREETING_FALLBACK
    elif reason == "ui_context_question":
        fallback = UI_CONTEXT_QUESTION_FALLBACK
    elif reason == "low_confidence":
        fallback = (
            "I couldn't find a confident answer for that. "
            "Try rephrasing or ask about emissions, energy, water, "
            "waste, facilities, or reporting periods."
        )
    else:
        fallback = ASSISTANT_IDENTITY_FALLBACK if _is_assistant_identity_question(query) else _varied_out_of_domain(query)
    metadata: dict[str, object] = {"document_count": 0}
    if _is_assistant_identity_question(query):
        metadata["identity_question"] = True
    if reason == "declarative_statement":
        metadata["declarative_statement"] = True
    if reason == "greeting":
        metadata["greeting"] = True
    if reason == "ui_context_question":
        metadata["ui_context_question"] = True
    if reason == "low_confidence":
        metadata["low_confidence"] = True
    return standardize_tool_result(
        tool="guardrail",
        route="out_of_domain",
        data=[],
        metadata=metadata,
        fallback_answer=fallback,
        documents=[],
    )


def _low_confidence_semantic_query(documents, query: str) -> bool:
    normalized = (query or "").strip().lower()
    if not normalized:
        return True
    if not documents:
        return True
    top_score = max(float(getattr(doc, "score", 0.0) or 0.0) for doc in documents)
    return top_score < 0.85


def unsupported_scope_tool_result(query: str) -> dict[str, object]:
    message = unsupported_scope_message(query) or DEFAULT_EMPTY_RAG_FALLBACK
    return standardize_tool_result(
        tool="rag",
        route="rag",
        data=[],
        metadata={"document_count": 0, "unsupported_scope": True},
        fallback_answer=message,
        documents=[],
    )


def safe_search(search_fn, query: str, limit: int, scope: SearchScope):
    try:
        return search_fn(query, limit=limit, scope=scope)
    except Exception:
        logger.exception("RAG retrieval failed")
        return None


def definition_search_query(query: str) -> str:
    normalized_query = (query or "").strip()
    return f"{normalized_query} definition glossary".strip()


def ensure_definition_doc(query: str, documents, scope: SearchScope, limit: int, *, search_fn):
    preferred_topic = _preferred_glossary_topic(query)
    wants_definition = is_definition_query(query) or (
        preferred_topic is not None and any(
            phrase in (query or "").lower()
            for phrase in {"explain", "tell me about"}
        )
    )
    if not wants_definition:
        return documents
    if preferred_topic:
        preferred_documents = [
            doc for doc in documents
            if doc.metadata.get("entity") == "glossary" and doc.metadata.get("topic") == preferred_topic
        ]
        if preferred_documents:
            return preferred_documents
    if not preferred_topic and any(doc.metadata.get("entity") == "glossary" for doc in documents):
        return _prioritize_definition_documents(query, documents)

    definition_docs = safe_search(search_fn, definition_search_query(query), max(3, min(limit, 6)), scope)
    if not definition_docs:
        dashboard_doc = _dashboard_glossary_document(preferred_topic)
        return [dashboard_doc, *documents] if dashboard_doc is not None else documents
    glossary_docs = [doc for doc in definition_docs if doc.metadata.get("entity") == "glossary"]
    if preferred_topic:
        preferred_glossary_docs = [
            doc for doc in glossary_docs
            if doc.metadata.get("topic") == preferred_topic
        ]
        if preferred_glossary_docs:
            return preferred_glossary_docs
        dashboard_doc = _dashboard_glossary_document(preferred_topic)
        if dashboard_doc is not None:
            return [dashboard_doc]
    if not glossary_docs:
        return documents
    return _prioritize_definition_documents(
        query,
        glossary_docs + [doc for doc in documents if doc.metadata.get("entity") != "glossary"],
    )


def coerce_int(value):
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_scope(request) -> SearchScope:
    user = getattr(request, "user", None)
    user_org_id = coerce_int(getattr(user, "organization_id", None))
    user_facility_id = coerce_int(getattr(user, "facility_id", None))
    user_period_id = coerce_int(getattr(user, "reporting_period_id", None))

    return SearchScope(
        organization_id=coerce_int(request.data.get("organization_id")) or user_org_id,
        facility_id=coerce_int(request.data.get("facility_id")) or user_facility_id,
        reporting_period_id=coerce_int(request.data.get("reporting_period_id")) or user_period_id,
    )


def parse_history(raw_history) -> list[ChatTurn]:
    if not isinstance(raw_history, list):
        return []

    history: list[ChatTurn] = []
    for item in raw_history[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append(ChatTurn(role=role, content=content))
    return history


def apply_scope(
    queryset,
    scope: SearchScope,
    org_field: str | None = "organization_id",
    facility_field: str | None = "facility_id",
    period_field: str | None = "reporting_period_id",
):
    if scope.organization_id and org_field is not None:
        queryset = queryset.filter(**{org_field: scope.organization_id})
    if scope.facility_id and facility_field is not None:
        queryset = queryset.filter(**{facility_field: scope.facility_id})
    if scope.reporting_period_id and period_field is not None:
        queryset = queryset.filter(**{period_field: scope.reporting_period_id})
    return queryset


def build_suggested_questions(scope: SearchScope) -> list[str]:
    suggestions: list[str] = []

    latest_summary = apply_scope(
        MonthlyEmissionSummary.objects.select_related("facility", "organization", "reporting_period").order_by("-year", "-month", "scope"),
        scope,
    ).first()
    latest_energy = apply_scope(
        EnergySummary.objects.select_related("facility", "reporting_period", "facility__organization").order_by("-id"),
        scope,
        org_field="facility__organization_id",
    ).first()
    latest_project = apply_scope(
        ReductionProject.objects.select_related("facility", "facility__organization").order_by("-id"),
        scope,
        org_field="facility__organization_id",
        period_field=None,
    ).first()
    featured_facility = apply_scope(
        Facility.objects.select_related("organization").order_by("organization__name", "name"),
        scope,
        org_field="organization_id",
        period_field=None,
    ).first()

    if latest_summary:
        facility_name = latest_summary.facility.name if latest_summary.facility_id else latest_summary.organization.name
        suggestions.append(
            f"What were {latest_summary.get_scope_display().lower()} emissions for {facility_name} in {latest_summary.reporting_period.name}?"
        )
        suggestions.append(f"Compare {facility_name} emissions for {latest_summary.reporting_period.name}.")

    if latest_energy:
        suggestions.append(f"What is the energy summary for {latest_energy.facility.name} in {latest_energy.reporting_period.name}?")

    if latest_project:
        suggestions.append(f"What reduction projects are available for {latest_project.facility.name}?")

    if featured_facility:
        suggestions.append(f"Show monthly emissions for {featured_facility.name}.")

    fallback_suggestions = [
        "Show my latest monthly emissions.",
        "Compare this month's emissions with the previous month.",
        "What is the latest energy summary?",
        "Suggest emission reduction opportunities.",
    ]

    ordered_unique = list(dict.fromkeys(suggestions + fallback_suggestions))
    return ordered_unique[:4]


def contextualize_scoped_value_query(query: str, scope: SearchScope) -> str:
    normalized_query = str(query).strip()
    lowered = normalized_query.lower()
    has_scope_context = bool(scope.organization_id or scope.facility_id or scope.reporting_period_id)
    references_current_entity = any(
        phrase in lowered
        for phrase in {
            "this company",
            "the company",
            "this organization",
            "the organization",
            "this facility",
            "the facility",
            "this plant",
            "the plant",
            "this site",
            "the site",
        }
    )
    asks_for_value = any(
        phrase in lowered
        for phrase in {
            "emission",
            "emissions",
            "value",
            "values",
            "amount",
            "total",
        }
    )
    mentions_scope = "scope" in lowered or any(scope_code in lowered for scope_code in {"s1", "s2", "s3"})
    has_aggregate_signal = any(
        phrase in lowered
        for phrase in {
            "total",
            "summary",
            "compare",
            "comparison",
            "trend",
            "breakdown",
        }
    )
    already_specific = any(
        phrase in lowered
        for phrase in {
            "latest",
            "current",
            "recent",
            "this month",
            "this year",
            "reporting period",
            "monthly",
            "fy20",
            "2020",
            "2021",
            "2022",
            "2023",
            "2024",
            "2025",
            "2026",
        }
    )

    if has_scope_context and references_current_entity and asks_for_value and mentions_scope and not already_specific and not has_aggregate_signal:
        return f"{normalized_query} latest monthly emissions".strip()

    return normalized_query


def resolve_result_limit(normalized_query: str) -> int:
    if any(term in normalized_query for term in {"breakdown", "break down", "category", "subcategory", "detail"}):
        return 12
    if any(term in normalized_query for term in {"location", "locations", "city", "cities", "country", "countries", "where"}):
        return 12
    if any(term in normalized_query for term in {"graph", "chart", "plot", "trend", "compare"}):
        return 12
    return 8


def _result_source(tool_result: dict[str, object]) -> dict[str, object]:
    if str(tool_result.get("route") or "") == "sql_rag":
        return dict((tool_result.get("sql_result") or {}).get("source") or {})
    return dict(tool_result.get("source") or {})


def _tool_chart(tool_result: dict[str, object]) -> dict[str, object] | None:
    chart = tool_result.get("chart")
    return dict(chart) if isinstance(chart, dict) and chart else None


def _retrieved_docs_payload(documents) -> list[dict[str, object]]:
    return [
        {
            "source": doc.source,
            "content": doc.content,
            "snippet": doc.snippet,
            "metadata": doc.metadata,
            "score": round(doc.score, 2),
        }
        for doc in documents
    ]


def _retrieved_docs_payload_minimal(documents) -> list[dict[str, object]]:
    return [
        {
            "source": doc.source,
            "content": doc.content,
            "metadata": doc.metadata,
            "score": round(doc.score, 2),
        }
        for doc in documents
    ]


def _chart_query_type(normalized_query: str) -> str:
    if any(term in normalized_query for term in {"compare", "comparison"}):
        return "comparison"
    has_multi_scope = len(_extract_scope_mentions(normalized_query)) > 1
    if has_multi_scope or any(term in normalized_query for term in {"breakdown", "split by", "scope breakdown"}):
        return "breakdown"
    if any(term in normalized_query for term in {"latest", "current", "recent"}) and any(
        term in normalized_query for term in {"energy", "renewable", "non-renewable", "power"}
    ):
        return "latest"
    return "trend"


def build_final_response_payload(
    *,
    query: str,
    resolved_query: str,
    tool_result: dict[str, object],
    documents,
    answer: str,
    provider: str,
    route_reason: str,
    response_mode: str = "enriched",
) -> dict[str, object]:
    source = _result_source(tool_result)
    base_payload = {
        "query": query,
        "resolved_query": resolved_query,
        "route": tool_result.get("route"),
        "route_reason": route_reason,
        "answer": answer,
         "explanation": tool_result.get("explanation"),
        "retrieved_docs": _retrieved_docs_payload_minimal(documents) if response_mode == "minimal" else _retrieved_docs_payload(documents),
        "tool_output": tool_result,
        "provider": provider,
    }
    if response_mode != "minimal":
        base_payload["chart"] = _tool_chart(tool_result)
        base_payload["source"] = {
            "line": source.get("line"),
            "example": source.get("example"),
        }
    return base_payload


def handle_ask_ai(
    request,
    *,
    router,
    sql_tool,
    search_fn,
    generate_answer_fn,
    rewrite_query_with_history_fn,
    build_chart_payload_from_sql_result_fn,
):
    request_started_at = time.monotonic()
    query = request.data.get("query")
    if not query:
        return Response({"error": "Query is required"}, status=400)

    response_mode = resolve_response_mode(request)
    scope = resolve_scope(request)
    history = parse_history(request.data.get("history"))
    logger.info(
        "RAG request start query=%r history_turns=%s scope=%s",
        str(query),
        len(history),
        {
            "organization_id": scope.organization_id,
            "facility_id": scope.facility_id,
            "reporting_period_id": scope.reporting_period_id,
        },
    )
    resolved_query = rewrite_query_with_history_fn(str(query), history)
    resolved_query = contextualize_scoped_value_query(resolved_query, scope)
    resolved_query = expand_temporal_query(resolved_query)
    resolved_query = expand_relative_time_query(resolved_query)
    decision = router.decide(resolved_query)
    route_reason = decision.reason
    documents = []
    normalized_query = str(resolved_query).lower()
    logger.info("RAG request routed route=%s reason=%s resolved_query=%r", decision.route, decision.reason, resolved_query)

    def safe_sql_execute(query_text: str, sql_scope: SearchScope, *, query_type: str | None = None):
        try:
            return sql_tool.execute(query_text, sql_scope, query_type=query_type)
        except Exception:
            logger.exception("SQL tool execution failed")
            return None

    if unsupported_scope_message(resolved_query) and decision.route == "rag":
        tool_result = unsupported_scope_tool_result(resolved_query)
    elif decision.route == "out_of_domain":
        tool_result = out_of_domain_tool_result(str(query), reason=decision.reason)
    elif decision.route == "chart":
        chart_query_type = _chart_query_type(normalized_query)
        analysis = safe_sql_execute(resolved_query, scope, query_type=chart_query_type)
        chart = build_chart_payload_from_sql_result_fn(analysis)
        tool_result = standardize_tool_result(
            tool="chart",
            route="chart",
            data=chart or {},
            metadata={
                "analysis": analysis.get("metadata", {}) if analysis else {},
                "has_chart": chart is not None,
            },
            fallback_answer=analysis.get("fallback_answer") if analysis else (
                chart.get("summary") if chart else "I could not build a chart from the matched data."
            ),
            source=(analysis or {}).get("source") or {},
            analysis=analysis,
            chart=chart,
        )
    elif decision.route == "sql_rag":
        sql_result = safe_sql_execute(
            resolved_query,
            scope,
            query_type=None,
        )
        chart = build_chart_payload_from_sql_result_fn(sql_result) if sql_result and decision.needs_chart else None
        limit = resolve_result_limit(normalized_query)
        retrieval_started_at = time.monotonic()
        logger.info("RAG retrieval start query=%r limit=%s route=%s", resolved_query, limit, decision.route)
        searched_documents = safe_search(search_fn, resolved_query, limit=limit, scope=scope)
        logger.info(
            "RAG retrieval end query=%r docs=%s latency_ms=%.2f route=%s",
            resolved_query,
            len(searched_documents or []),
            (time.monotonic() - retrieval_started_at) * 1000,
            decision.route,
        )
        if searched_documents is not None:
            documents = searched_documents
        rag_result = build_rag_tool_result(str(query), documents) if searched_documents is not None else empty_rag_tool_result()

        if sql_result and sql_has_data(sql_result) and searched_documents is not None:
            tool_result = standardize_tool_result(
                tool="sql_rag",
                route="sql_rag",
                data={
                    "sql": sql_result.get("data", []),
                    "rag": rag_result.get("data", []),
                },
                metadata={
                    "sql": sql_result.get("metadata", {}),
                    "rag": rag_result.get("metadata", {}),
                },
                fallback_answer=sql_result.get("fallback_answer") or rag_result.get("fallback_answer"),
                source=sql_result.get("source") or {},
                chart=chart,
                sql_result=sql_result,
                rag_result=rag_result,
            )
        elif searched_documents is not None:
            tool_result = rag_result
        elif sql_result:
            tool_result = {
                **sql_result,
                "chart": chart,
            } if chart is not None else sql_result
        else:
            return Response(
                {
                    "query": query,
                    "resolved_query": resolved_query,
                    "error": "The AI assistant could not retrieve supporting data right now.",
                    "retrieved_doc_count": 0,
                    "provider": "error",
                },
                status=502,
            )
    elif decision.route == "sql":
        tool_result = safe_sql_execute(
            resolved_query,
            scope,
            query_type=None,
        )
        if tool_result is None:
            limit = resolve_result_limit(normalized_query)
            retrieval_started_at = time.monotonic()
            logger.info("RAG retrieval start query=%r limit=%s route=sql_fallback", resolved_query, limit)
            searched_documents = safe_search(search_fn, resolved_query, limit=limit, scope=scope)
            logger.info(
                "RAG retrieval end query=%r docs=%s latency_ms=%.2f route=sql_fallback",
                resolved_query,
                len(searched_documents or []),
                (time.monotonic() - retrieval_started_at) * 1000,
            )
            if searched_documents is not None:
                documents = searched_documents
                tool_result = build_rag_tool_result(str(query), documents)
            else:
                return Response(
                    {
                        "query": query,
                        "resolved_query": resolved_query,
                        "error": "The AI assistant could not retrieve supporting data right now.",
                        "retrieved_doc_count": 0,
                        "provider": "error",
                    },
                    status=502,
                )
        if not sql_has_data(tool_result):
            limit = resolve_result_limit(normalized_query)
            retrieval_started_at = time.monotonic()
            logger.info("RAG retrieval start query=%r limit=%s route=sql_empty", resolved_query, limit)
            searched_documents = safe_search(search_fn, resolved_query, limit=limit, scope=scope)
            logger.info(
                "RAG retrieval end query=%r docs=%s latency_ms=%.2f route=sql_empty",
                resolved_query,
                len(searched_documents or []),
                (time.monotonic() - retrieval_started_at) * 1000,
            )
            if searched_documents is not None:
                documents = searched_documents
                has_time_or_scope = bool(
                    extract_scope_filters(resolved_query)
                    or extract_years(resolved_query)
                    or extract_month_year_pairs(resolved_query)
                    or any(
                        term in normalized_query
                        for term in {"this year", "last year", "this month", "reporting period", "fy"}
                    )
                )
                has_metric = any(
                    term in normalized_query
                    for term in {
                        "energy",
                        "water",
                        "waste",
                        "emission",
                        "emissions",
                        "credit",
                        "credits",
                        "renewable",
                    }
                )
                if _is_explicit_numeric_lookup(resolved_query) and not _documents_contain_numeric_evidence(documents):
                    tool_result = {
                        **tool_result,
                        "fallback_answer": (
                            tool_result.get("fallback_answer")
                            or "No data found for that period. Try a different date range or facility."
                        ),
                    }
                else:
                    tool_result = build_rag_tool_result(str(query), documents)
            else:
                tool_result = {
                    **tool_result,
                    "fallback_answer": tool_result.get("fallback_answer") or "I could not find matching data for that request.",
                }
        elif decision.needs_chart:
            tool_result = {
                **tool_result,
                "chart": build_chart_payload_from_sql_result_fn(tool_result),
            }
    else:
        limit = resolve_result_limit(normalized_query)
        retrieval_started_at = time.monotonic()
        logger.info("RAG retrieval start query=%r limit=%s route=%s", resolved_query, limit, decision.route)
        searched_documents = safe_search(search_fn, resolved_query, limit=limit, scope=scope)
        logger.info(
            "RAG retrieval end query=%r docs=%s latency_ms=%.2f route=%s",
            resolved_query,
            len(searched_documents or []),
            (time.monotonic() - retrieval_started_at) * 1000,
            decision.route,
        )
        if searched_documents is not None:
            documents = ensure_definition_doc(str(query), searched_documents, scope, limit, search_fn=search_fn)
            if _should_prefer_dashboard_home_value(str(query)):
                dashboard_home_doc = _dashboard_home_value_document(str(query), scope)
                if dashboard_home_doc is not None:
                    documents = [dashboard_home_doc] + [doc for doc in documents if doc is not dashboard_home_doc]
            top_score = max(
                (float(getattr(doc, "score", 0.0) or 0.0) for doc in documents),
                default=0.0,
            )
            is_low_confidence = top_score < 0.72
            if is_low_confidence and decision.reason not in {"product_question", "neutrality_location_query"} and not is_definition_query(str(query)):
                tool_result = out_of_domain_tool_result(str(query), reason="low_confidence")
                documents = []
            else:
                tool_result = build_rag_tool_result(str(query), documents)
        else:
            if decision.reason == "semantic_default":
                tool_result = out_of_domain_tool_result(str(query), reason=decision.reason)
            else:
                tool_result = empty_rag_tool_result()

    if decision.reason in {"greeting", "ui_context_question"}:
        payload = build_final_response_payload(
            query=str(query),
            resolved_query=resolved_query,
            tool_result=tool_result,
            documents=[],
            answer=str(
                tool_result.get("fallback_answer")
                or (GREETING_FALLBACK if decision.reason == "greeting" else UI_CONTEXT_QUESTION_FALLBACK)
            ),
            provider="guardrail-local",
            route_reason=route_reason,
            response_mode=response_mode,
        )
        logger.info(
            "RAG request end route=%s provider=%s docs=%s total_latency_ms=%.2f",
            payload.get("route"),
            payload.get("provider"),
            0,
            (time.monotonic() - request_started_at) * 1000,
        )
        return Response(payload)

    try:
        llm_started_at = time.monotonic()
        logger.info("RAG answer generation start route=%s", tool_result.get("route"))
        generated = generate_answer_fn(str(query), tool_result, history=history)
        if isinstance(generated, tuple) and len(generated) == 3:
            answer, provider, tool_result = generated
        else:
            answer, provider = generated
        logger.info(
            "RAG answer generation end route=%s provider=%s latency_ms=%.2f",
            tool_result.get("route"),
            provider,
            (time.monotonic() - llm_started_at) * 1000,
        )
    except Exception:
        logger.exception("Unexpected RAG failure")
        return Response(
            {
                "query": query,
                "resolved_query": resolved_query,
                "error": "The AI assistant could not generate a response right now.",
                "retrieved_doc_count": len(documents),
                "provider": "error",
            },
            status=502,
        )

    payload = build_final_response_payload(
        query=str(query),
        resolved_query=resolved_query,
        tool_result=tool_result,
        documents=documents,
        answer=answer,
        provider=provider,
        route_reason=route_reason,
        response_mode=response_mode,
    )
    logger.info(
        "RAG request end route=%s provider=%s docs=%s total_latency_ms=%.2f",
        payload.get("route"),
        payload.get("provider"),
        len(documents),
        (time.monotonic() - request_started_at) * 1000,
    )
    return Response(payload)


def handle_chart_data(
    request,
    *,
    generate_chart_payload_fn,
    rewrite_query_with_history_fn,
):
    request_started_at = time.monotonic()
    query = request.data.get("query")
    if not query:
        return Response({"error": "Query is required"}, status=400)

    scope = resolve_scope(request)
    history = parse_history(request.data.get("history"))
    logger.info("RAG chart request start query=%r history_turns=%s", str(query), len(history))
    resolved_query = rewrite_query_with_history_fn(str(query), history)
    resolved_query = expand_temporal_query(resolved_query)
    try:
        chart = generate_chart_payload_fn(resolved_query, scope)
    except Exception:
        logger.exception("Chart generation failed")
        chart = None

    if chart is None:
        return Response(
            {
                "query": query,
                "resolved_query": resolved_query,
                "error": "I could not build a chart from the matched data.",
                "retrieved_doc_count": 0,
            },
            status=404,
        )

    logger.info(
        "RAG chart request end query=%r total_latency_ms=%.2f",
        resolved_query,
        (time.monotonic() - request_started_at) * 1000,
    )
    return Response(
        {
            "query": query,
            "resolved_query": resolved_query,
            "chart": chart,
            "source": {
                "line": chart.get("source_line"),
                "example": chart.get("example"),
            },
            "retrieved_docs": [],
            "provider": "rag-chart-local",
        }
    )
