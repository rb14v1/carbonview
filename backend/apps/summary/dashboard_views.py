from calendar import month_name
from decimal import Decimal

from django.db.models import Avg, Sum
from django.db.models.functions import Coalesce, ExtractMonth, ExtractYear
from django.db.utils import OperationalError, ProgrammingError
from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.company.models import Facility, Organization, ReportingPeriod
from apps.emission.models import EmissionActivity, EmissionCalculation

from .dashboard_serializers import DashboardSerializer
from .models import (
    CarbonCredit,
    EnergySummary,
    NeutralityClaim,
    ReductionProject,
    WasteSummary,
    WaterUsage,
)

ZERO = Decimal("0")
SCOPE_LABELS = {
    "S1": "Scope 1",
    "S2": "Scope 2",
    "S3": "Scope 3",
}


class DashboardViewSet(viewsets.ViewSet):
    serializer_class = DashboardSerializer

    def list(self, request):
        """Assemble the dashboard payload by validating filters, collecting datasets, and shaping summary cards and charts."""
        organization_id = request.query_params.get("organization_id")
        facility_id = request.query_params.get("facility_id")
        reporting_period_id = request.query_params.get("reporting_period_id")
        year = request.query_params.get("year")
        month = request.query_params.get("month")

        try:
            filters = self._validated_filters(
                organization_id=organization_id,
                facility_id=facility_id,
                reporting_period_id=reporting_period_id,
                year=year,
                month=month,
            )
            filters = self._resolve_default_filters(filters)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        entity = self._build_entity(filters)
        activity_qs = self._activity_queryset(filters)
        period_qs = self._reporting_period_queryset(filters)
        facility_qs = self._facility_queryset(filters)
        credit_qs = self._credit_queryset(filters)
        reduction_qs = self._reduction_queryset(filters)
        claim_qs = self._claim_queryset(filters)
        energy_qs = self._energy_queryset(filters)
        water_qs = self._water_queryset(filters)
        waste_qs = self._waste_queryset(filters)
        calculation_qs = self._calculation_queryset(filters)

        gross_emissions = self._sum(calculation_qs, "co2e_amount")
        offsets = self._sum(credit_qs, "quantity_tco2e")
        reductions = self._sum(reduction_qs, "actual_reduction_tco2e")
        net_emissions = gross_emissions - offsets - reductions

        scope_totals = {
            code: self._sum(calculation_qs.filter(activity__category__scope=code), "co2e_amount")
            for code in SCOPE_LABELS
        }
        emission_breakdown = self._get_emission_breakdown(calculation_qs)
        scope_breakdown = []
        for code, label in SCOPE_LABELS.items():
            total = scope_totals[code]
            percentage = float((total / gross_emissions * 100) if gross_emissions else ZERO)
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
                self._sum(
                    calculation_qs.filter(
                        activity__category__scope="S2",
                        activity__scope2_method="location_based",
                    ),
                    "co2e_amount",
                )
            ),
            "market_based": float(
                self._sum(
                    calculation_qs.filter(
                        activity__category__scope="S2",
                        activity__scope2_method="market_based",
                    ),
                    "co2e_amount",
                )
            ),
        }

        geo = self._build_geo(filters, facility_qs)
        highlights = self._build_highlights(
            gross_emissions=gross_emissions,
            net_emissions=net_emissions,
            scope_totals=scope_totals,
            yearly_emissions=self._build_yearly_emissions(filters, calculation_qs),
            monthly_emissions=self._build_monthly_emissions(filters, calculation_qs),
            energy_qs=energy_qs,
            water_qs=water_qs,
            waste_qs=waste_qs,
        )
        data = {
            "filters": filters,
            "entity": entity,
            "geo": geo,
            "kpis": {
                "gross_emissions": float(gross_emissions),
                "offsets": float(offsets),
                "reductions": float(reductions),
                "net_emissions": float(net_emissions),
                "is_carbon_neutral": net_emissions <= ZERO,
                "approved_activities": activity_qs.count(),
                "facilities_count": facility_qs.count(),
                "reporting_periods_count": period_qs.count(),
            },
            "highlights": highlights,
            "scope_breakdown": scope_breakdown,
            "scope2_split": scope2_split,
            "yearly_emissions": highlights["yearly_emissions"],
            "monthly_emissions": highlights["monthly_emissions"],
            "energy": self._build_energy_card(energy_qs),
            "water": self._build_water_card(water_qs),
            "waste": self._build_waste_card(waste_qs),
            "carbon_credits": [
                {
                    "id": item.id,
                    "project_name": item.project_name,
                    "source": item.source,
                    "registry_name": item.registry_name + " - "+ item.serial_number,
                    "registry_name": item.registry_name + " - "+ item.serial_number,
                    "vintage_year": item.vintage_year,
                    "quantity_tco2e": float(item.quantity_tco2e),
                    "status": item.status,
                }
                for item in credit_qs.order_by("-vintage_year", "project_name")[:10]
            ],
            "reduction_projects": [
                {
                    "id": item.id,
                    "name": item.name,
                    "expected_reduction_tco2e": float(item.expected_reduction_tco2e),
                    "actual_reduction_tco2e": float(item.actual_reduction_tco2e),
                }
                for item in reduction_qs[:10]
            ],
            "neutrality_claims": [
                {
                    "id": item.id,
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

        serializer = self.serializer_class(data)
        return Response(serializer.data)
    

    def _get_emission_breakdown(self, calculation_qs):
        """Build scope drill-down rows from aggregated calculations only."""
        breakdown = {"S1": [], "S2": [], "S3": []}
        try:
            calc_rows = list(
                calculation_qs.values(
                    "activity__category__scope",
                    "activity__category__parent__name",
                    "activity__category__name",
                    "activity__scope3_category__name",
                    "gas_type__gas_name",
                ).annotate(total=Coalesce(Sum("co2e_amount"), ZERO))
            )
            if calc_rows:
                breakdown = self._build_breakdown_from_calculations(calc_rows)
        except (ProgrammingError, OperationalError):
            return breakdown

        return breakdown

    def _validated_filters(self, organization_id=None, facility_id=None, reporting_period_id=None, year=None, month=None):
        """Parse query parameters into integers and enforce valid organization, facility, period, and month combinations."""
        parsed = {
            "organization_id": self._parse_optional_int(organization_id, "organization_id"),
            "facility_id": self._parse_optional_int(facility_id, "facility_id"),
            "reporting_period_id": self._parse_optional_int(reporting_period_id, "reporting_period_id"),
            "year": self._parse_optional_int(year, "year"),
            "month": self._parse_optional_int(month, "month"),
        }

        facility = None
        period = None
        organization = None

        if parsed["organization_id"] is not None:
            organization = Organization.objects.filter(pk=parsed["organization_id"]).first()
            if organization is None:
                raise ValueError("organization_id is invalid")

        if parsed["facility_id"] is not None:
            facility = Facility.objects.select_related("organization").filter(pk=parsed["facility_id"]).first()
            if facility is None:
                raise ValueError("facility_id is invalid")
            if organization and facility.organization_id != organization.id:
                raise ValueError("facility_id does not belong to organization_id")
            if organization is None:
                parsed["organization_id"] = facility.organization_id
                organization = facility.organization

        if parsed["reporting_period_id"] is not None:
            period = ReportingPeriod.objects.select_related("organization").filter(pk=parsed["reporting_period_id"]).first()
            if period is None:
                raise ValueError("reporting_period_id is invalid")
            if organization and period.organization_id != organization.id:
                raise ValueError("reporting_period_id does not belong to organization_id")
            if facility and facility.organization_id != period.organization_id:
                raise ValueError("facility_id and reporting_period_id do not belong to the same organization")
            if organization is None:
                parsed["organization_id"] = period.organization_id

        if parsed["month"] is not None:
            if parsed["month"] < 1 or parsed["month"] > 12:
                raise ValueError("month must be an integer between 1 and 12")

        return parsed

    def _resolve_default_filters(self, filters):
        """Fill in sensible default organization, facility, and reporting-period filters when the request omits them."""
        resolved = dict(filters)

        if resolved["organization_id"] is None:
            organizations = list(Organization.objects.order_by("name").values_list("id", flat=True)[:2])
            if len(organizations) == 1:
                resolved["organization_id"] = organizations[0]

        if resolved["facility_id"] is None and resolved["organization_id"] is not None:
            facilities = list(
                Facility.objects.filter(organization_id=resolved["organization_id"])
                .order_by("name")
                .values_list("id", flat=True)[:2]
            )
            if len(facilities) == 1:
                resolved["facility_id"] = facilities[0]

        if (
            resolved["reporting_period_id"] is None
            and resolved["organization_id"] is not None
            and resolved["year"] is not None
        ):
            reporting_period = (
                ReportingPeriod.objects.filter(
                    organization_id=resolved["organization_id"],
                    year=resolved["year"],
                )
                .order_by("-start_date", "-id")
                .values_list("id", flat=True)
                .first()
            )
            if reporting_period is not None:
                resolved["reporting_period_id"] = reporting_period

        if resolved["month"] is not None and resolved["year"] is None:
            resolved["month"] = None

        return resolved

    def _build_entity(self, filters):
        """Return lightweight organization, facility, and reporting-period details for the active dashboard context."""
        organization = None
        facility = None
        reporting_period = None

        if filters["organization_id"]:
            organization = Organization.objects.filter(pk=filters["organization_id"]).values(
                "id",
                "name",
                "legal_name",
                "industry_type",
                "reporting_boundary",
                "base_currency",
                "base_year",
            ).first()
        if filters["facility_id"]:
            facility = (
                Facility.objects.select_related("location", "location__country", "location__state", "location__city")
                .filter(pk=filters["facility_id"])
                .values(
                    "id",
                    "name",
                    "facility_code",
                    "is_active",
                    "is_carbon_neutral",
                    "location__street_address",
                    "location__postal_code",
                    "location__latitude",
                    "location__longitude",
                    "location__country__name",
                    "location__state__name",
                    "location__city__name",
                )
                .first()
            )
        if filters["reporting_period_id"]:
            reporting_period = ReportingPeriod.objects.filter(pk=filters["reporting_period_id"]).values(
                "id", "name", "year", "start_date", "end_date"
            ).first()

        if facility:
            facility = {
                "id": facility["id"],
                "name": facility["name"],
                "facility_code": facility["facility_code"],
                "is_active": facility["is_active"],
                "is_carbon_neutral": facility["is_carbon_neutral"],
                "location": {
                    "street_address": facility["location__street_address"],
                    "postal_code": facility["location__postal_code"],
                    "country": facility["location__country__name"],
                    "state": facility["location__state__name"],
                    "city": facility["location__city__name"],
                    "latitude": self._to_float_or_none(facility["location__latitude"]),
                    "longitude": self._to_float_or_none(facility["location__longitude"]),
                },
            }

        return {
            "organization": organization,
            "facility": facility,
            "reporting_period": reporting_period,
        }

    def _activity_queryset(self, filters):
        """Build the approved-activity queryset and apply the selected organization, facility, period, year, and month filters."""
        qs = EmissionActivity.objects.filter(status="approved").select_related(
            "category",
            "facility",
            "organization",
            "reporting_period",
        )

        if filters["organization_id"]:
            qs = qs.filter(organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(activity_date__year=filters["year"])
        if filters["month"]:
            qs = qs.filter(activity_date__month=filters["month"])

        return qs

    def _reporting_period_queryset(self, filters):
        """Return reporting periods limited to the current dashboard selection for counts and lookup details."""
        qs = ReportingPeriod.objects.all()
        if filters["organization_id"]:
            qs = qs.filter(organization_id=filters["organization_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(year=filters["year"])
        return qs

    def _facility_queryset(self, filters):
        """Return facilities with location data for the chosen organization or facility context."""
        qs = Facility.objects.select_related("location", "location__country", "location__state", "location__city")
        if filters["organization_id"]:
            qs = qs.filter(organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(id=filters["facility_id"])
        return qs

    def _credit_queryset(self, filters):
        """Return carbon credits filtered by organization, facility, and optional vintage year for dashboard totals."""
        qs = CarbonCredit.objects.select_related("facility", "facility__organization")
        if filters["organization_id"]:
            qs = qs.filter(facility__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["year"]:
            qs = qs.filter(vintage_year=filters["year"])
        return qs

    def _reduction_queryset(self, filters):
        """Return reduction projects filtered to the current organization, facility, and optional reporting year."""
        qs = ReductionProject.objects.select_related("facility", "facility__organization")
        if filters["organization_id"]:
            qs = qs.filter(facility__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["year"]:
            qs = qs.filter(start_date__year=filters["year"])
        qs = qs.order_by("-start_date")
        return qs

    def _claim_queryset(self, filters):
        """Return neutrality claims scoped to the selected organization, facility, reporting period, and year."""
        qs = NeutralityClaim.objects.select_related("organization", "facility", "reporting_period")
        if filters["organization_id"]:
            qs = qs.filter(organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(reporting_period__year=filters["year"])
        return qs

    def _energy_queryset(self, filters):
        """Return energy summaries narrowed to the active dashboard context for KPI and card calculations."""
        qs = EnergySummary.objects.select_related("facility", "reporting_period", "unit")
        if filters["organization_id"]:
            qs = qs.filter(facility__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(reporting_period__year=filters["year"])
        return qs

    def _water_queryset(self, filters):
        """Return water-usage summaries for the selected organization, facility, reporting period, and year."""
        qs = WaterUsage.objects.select_related("facility", "reporting_period", "unit")
        if filters["organization_id"]:
            qs = qs.filter(facility__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(reporting_period__year=filters["year"])
        return qs

    def _waste_queryset(self, filters):
        """Return waste summaries for the active dashboard filters so waste cards use the same scope as the rest of the page."""
        qs = WasteSummary.objects.select_related("facility", "reporting_period", "unit")
        if filters["organization_id"]:
            qs = qs.filter(facility__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(reporting_period__year=filters["year"])
        return qs

    def _build_yearly_emissions(self, filters, calculation_qs):
        """Build yearly emission trend rows from calculations only."""
        rows = (
            calculation_qs.annotate(year_value=ExtractYear("activity__activity_date"))
            .values("year_value", "activity__category__scope")
            .annotate(total=Coalesce(Sum("co2e_amount"), ZERO))
            .order_by("year_value", "activity__category__scope")
        )

        if rows:
            return self._merge_scope_rows(rows, year_key="year_value", scope_key="activity__category__scope")

        return []

    def _build_monthly_emissions(self, filters, calculation_qs):
        """Build monthly trend rows from calculations only."""
        rows = (
            calculation_qs.annotate(
                year_value=ExtractYear("activity__activity_date"),
                month_value=ExtractMonth("activity__activity_date"),
            )
            .values("year_value", "month_value", "activity__category__scope")
            .annotate(total=Coalesce(Sum("co2e_amount"), ZERO))
            .order_by("year_value", "month_value", "activity__category__scope")
        )

        if rows:
            return self._merge_month_rows(
                rows,
                year_key="year_value",
                month_key="month_value",
                scope_key="activity__category__scope",
            )
        return []

    def _calculation_queryset(self, filters):
        """Return approved activity calculations scoped to the current dashboard filters."""
        qs = EmissionCalculation.objects.select_related(
            "activity__category",
            "activity__facility",
            "activity__organization",
            "activity__reporting_period",
            "gas_type",
        )

        qs = qs.filter(activity__status="approved")

        if filters["organization_id"]:
            qs = qs.filter(activity__organization_id=filters["organization_id"])
        if filters["facility_id"]:
            qs = qs.filter(activity__facility_id=filters["facility_id"])
        if filters["reporting_period_id"]:
            qs = qs.filter(activity__reporting_period_id=filters["reporting_period_id"])
        if filters["year"]:
            qs = qs.filter(activity__activity_date__year=filters["year"])
        if filters["month"]:
            qs = qs.filter(activity__activity_date__month=filters["month"])

        return qs

    def _breakdown_labels(self, category_name, subcategory_name):
        """Normalize the category hierarchy so breakdown keys match the stored breakdown layout."""
        if category_name and subcategory_name:
            return category_name, subcategory_name
        if category_name:
            return category_name, None
        return subcategory_name, None

    def _normalize_scope(self, raw_scope):
        """Normalize scope values to the canonical dashboard scope codes."""
        if raw_scope in SCOPE_LABELS:
            return raw_scope
        return None

    def _build_breakdown_from_calculations(self, calc_rows):
        """Aggregate calculation rows into the dashboard breakdown structure."""
        breakdown = {"S1": [], "S2": [], "S3": []}

        for row in calc_rows:
            scope = self._normalize_scope(row["activity__category__scope"])
            if scope is None:
                continue

            category_label, subcategory_label = self._breakdown_labels(
                row["activity__category__parent__name"],
                row["activity__category__name"],
            )
            total_co2e = float(row["total"])
            if total_co2e == 0.0:
                continue

            breakdown[scope].append(
                {
                    "category": category_label,
                    "subcategory": subcategory_label,
                    "scope3_category": row["activity__scope3_category__name"],
                    "gas_type": row["gas_type__gas_name"],
                    "total_co2e": total_co2e,
                }
            )

        return breakdown

    def _merge_scope_rows(self, rows, year_key, scope_key):
        """Merge per-scope aggregate rows into one yearly record containing Scope 1, 2, 3, and total values."""
        grouped = {}
        for row in rows:
            year = row[year_key]
            scope = row[scope_key]
            bucket = grouped.setdefault(
                year,
                {
                    "year": year,
                    "scope_1": 0.0,
                    "scope_2": 0.0,
                    "scope_3": 0.0,
                    "total_co2e": 0.0,
                },
            )
            total = float(row["total"])
            if scope == "S1":
                bucket["scope_1"] = total
            elif scope == "S2":
                bucket["scope_2"] = total
            elif scope == "S3":
                bucket["scope_3"] = total
            bucket["total_co2e"] += total
        return list(grouped.values())

    def _merge_month_rows(self, rows, year_key, month_key, scope_key):
        """Merge per-scope monthly aggregates into one row per month with derived month labels and totals."""
        grouped = {}
        for row in rows:
            year = row[year_key]
            month = row[month_key]
            key = (year, month)
            scope = row[scope_key]
            bucket = grouped.setdefault(
                key,
                {
                    "year": year,
                    "month": month,
                    "month_name": month_name[month],
                    "scope_1": 0.0,
                    "scope_2": 0.0,
                    "scope_3": 0.0,
                    "total_co2e": 0.0,
                },
            )
            total = float(row["total"])
            if scope == "S1":
                bucket["scope_1"] = total
            elif scope == "S2":
                bucket["scope_2"] = total
            elif scope == "S3":
                bucket["scope_3"] = total
            bucket["total_co2e"] += total
        return list(grouped.values())

    def _build_energy_card(self, energy_qs):
        """Summarize total, renewable, and non-renewable energy plus the distinct unit codes present in the queryset."""
        units = list(energy_qs.values_list("unit__code", flat=True).distinct())
        return {
            "total_energy": float(self._sum(energy_qs, "total_energy")),
            "renewable_energy": float(self._sum(energy_qs, "renewable_energy")),
            "non_renewable_energy": float(self._sum(energy_qs, "non_renewable_energy")),
            "units": [unit for unit in units if unit],
        }

    def _build_geo(self, filters, facility_qs):
        """Convert facility and location records into map-friendly dictionaries and identify the currently focused location."""
        facilities = []
        for facility in facility_qs:
            location = getattr(facility, "location", None)
            facilities.append(
                {
                    "facility_id": facility.id,
                    "facility_name": facility.name,
                    "facility_code": facility.facility_code,
                    "is_active": facility.is_active,
                    "is_carbon_neutral": facility.is_carbon_neutral,
                    "street_address": getattr(location, "street_address", ""),
                    "postal_code": getattr(location, "postal_code", ""),
                    "city": getattr(getattr(location, "city", None), "name", None),
                    "state": getattr(getattr(location, "state", None), "name", None),
                    "country": getattr(getattr(location, "country", None), "name", None),
                    "latitude": self._to_float_or_none(getattr(location, "latitude", None)),
                    "longitude": self._to_float_or_none(getattr(location, "longitude", None)),
                }
            )

        current_location = facilities[0] if len(facilities) == 1 else None
        if filters["facility_id"] and facilities:
            current_location = facilities[0]

        return {
            "current_location": current_location,
            "facility_locations": facilities,
            "has_coordinates": any(
                item["latitude"] is not None and item["longitude"] is not None
                for item in facilities
            ),
        }

    def _build_highlights(
        self,
        gross_emissions,
        net_emissions,
        scope_totals,
        yearly_emissions,
        monthly_emissions,
        energy_qs,
        water_qs,
        waste_qs,
    ):
        """Derive highlight metrics like top scope, latest period, renewable share, and reduction percentages."""
        top_scope_code = max(scope_totals, key=lambda key: scope_totals[key]) if scope_totals else None
        top_scope_total = scope_totals[top_scope_code] if top_scope_code else ZERO
        latest_year = yearly_emissions[-1] if yearly_emissions else None
        previous_year = yearly_emissions[-2] if len(yearly_emissions) > 1 else None
        latest_month = monthly_emissions[-1] if monthly_emissions else None
        peak_month = max(monthly_emissions, key=lambda item: item["total_co2e"]) if monthly_emissions else None

        renewable_energy = self._sum(energy_qs, "renewable_energy")
        total_energy = self._sum(energy_qs, "total_energy")
        renewable_share = float((renewable_energy / total_energy * 100) if total_energy else ZERO)

        water_total = self._sum(water_qs, "amount")
        waste_total = self._sum(waste_qs, "total_waste")

        yoy_change = 0.0
        if latest_year and previous_year and previous_year["total_co2e"]:
            yoy_change = round(
                (
                    (latest_year["total_co2e"] - previous_year["total_co2e"])
                    / previous_year["total_co2e"]
                )
                * 100,
                2,
            )

        return {
            "top_emission_scope": {
                "code": top_scope_code,
                "label": SCOPE_LABELS.get(top_scope_code),
                "total_co2e": float(top_scope_total),
            },
            "latest_month": latest_month,
            "peak_month": peak_month,
            "latest_year": latest_year,
            "year_over_year_change_percentage": yoy_change,
            "renewable_energy_share_percentage": round(renewable_share, 2),
            "water_to_waste_ratio": float((water_total / waste_total) if waste_total else ZERO),
            "net_vs_gross_reduction_percentage": float(
                round(((gross_emissions - net_emissions) / gross_emissions * 100), 2)
                if gross_emissions
                else 0
            ),
            "yearly_emissions": yearly_emissions,
            "monthly_emissions": monthly_emissions,
        }

    def _build_water_card(self, water_qs):
        """Summarize total water usage and category-level totals, preserving any unit codes present in the data."""
        units = list(water_qs.values_list("unit__code", flat=True).distinct())
        categories = [
            {
                "category": row["category"],
                "amount": float(row["amount"]),
                "unit": row["unit__code"],
            }
            for row in water_qs.values("category", "unit__code")
            .annotate(amount=Coalesce(Sum("amount"), ZERO))
            .order_by("category")
        ]
        return {
            "total_water_usage": float(self._sum(water_qs, "amount")),
            "units": [unit for unit in units if unit],
            "categories": categories,
        }

    def _build_waste_card(self, waste_qs):
        """Summarize waste totals, hazardous split, recycling average, and unit codes for the dashboard waste card."""
        units = list(waste_qs.values_list("unit__code", flat=True).distinct())
        aggregates = waste_qs.aggregate(
            total_waste=Coalesce(Sum("total_waste"), ZERO),
            hazardous=Coalesce(Sum("hazardous"), ZERO),
            non_hazardous=Coalesce(Sum("non_hazardous"), ZERO),
            average_recycled_percentage=Coalesce(Avg("recycled_percentage"), ZERO),
        )
        return {
            "total_waste": float(aggregates["total_waste"]),
            "hazardous": float(aggregates["hazardous"]),
            "non_hazardous": float(aggregates["non_hazardous"]),
            "average_recycled_percentage": float(aggregates["average_recycled_percentage"]),
            "units": [unit for unit in units if unit],
        }

    def _sum(self, queryset, field):
        """Return a null-safe aggregate total for the requested field, defaulting to the shared zero constant."""
        return queryset.aggregate(total=Coalesce(Sum(field), ZERO))["total"] or ZERO

    def _parse_optional_int(self, raw_value, field_name):
        """Convert an optional query parameter to an integer and raise a clear error when parsing fails."""
        if raw_value in (None, ""):
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc

    def _to_float_or_none(self, value):
        """Convert decimal-like values to floats while preserving nulls for optional API response fields."""
        if value is None:
            return None
        return float(value)
    



