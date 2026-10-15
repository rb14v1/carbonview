from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from apps.emission.models import EmissionActivity, EmissionBreakdown, RecordStatus
from apps.summary.models import EnergySummary, MonthlyEmissionSummary, WasteSummary, WaterUsage

from ...core.common import MONTH_NAMES


ZERO = Decimal("0")


if TYPE_CHECKING:
    from ...sql_tool import SQLTool
    from ...core.types import GenericQueryFilters


class BaseSQLHandler(ABC):
    metric: str = ""

    def __init__(self, tool: "SQLTool"):
        self.tool = tool

    @abstractmethod
    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        raise NotImplementedError


class EmissionsHandler(BaseSQLHandler):
    metric = "emissions"

    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        return metric == self.metric or query_type == "breakdown"

    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        if query_type == "breakdown":
            return self._breakdown_result(filters)
        return self._emissions_result(filters, query_type)

    def _emissions_queryset(self, filters: "GenericQueryFilters"):
        queryset = EmissionActivity.objects.filter(status=RecordStatus.APPROVED).select_related(
            "organization",
            "facility",
            "reporting_period",
            "category",
        )
        queryset = self.tool._apply_common_filters(queryset, filters, period_year_field="activity_date__year")
        if filters.scopes:
            queryset = queryset.filter(category__scope__in=filters.scopes)
        if filters.month_year_pairs:
            period_filter = Q()
            for year, month in filters.month_year_pairs:
                period_filter |= Q(activity_date__year=year, activity_date__month=month)
            queryset = queryset.filter(period_filter)
        elif filters.months:
            queryset = queryset.filter(activity_date__month__in=list(filters.months))
        return queryset

    def _activity_emissions_rows(self, filters: "GenericQueryFilters") -> list[dict[str, object]]:
        return list(
            self._emissions_queryset(filters)
            .values(
                "organization__name",
                "facility__name",
                "reporting_period__name",
                "activity_date__year",
                "activity_date__month",
                "category__scope",
            )
            .annotate(total_co2e=Coalesce(Sum("total_co2e"), ZERO))
            .order_by("activity_date__year", "activity_date__month", "category__scope")
        )

    def _monthly_summary_queryset(self, filters: "GenericQueryFilters"):
        queryset = MonthlyEmissionSummary.objects.select_related("organization", "facility", "reporting_period")
        queryset = self.tool._apply_common_filters(queryset, filters, period_year_field="year")
        if filters.scopes:
            queryset = queryset.filter(scope__in=filters.scopes)
        if filters.month_year_pairs:
            period_filter = Q()
            for year, month in filters.month_year_pairs:
                period_filter |= Q(year=year, month=month)
            queryset = queryset.filter(period_filter)
        elif filters.months:
            queryset = queryset.filter(month__in=list(filters.months))
        return queryset

    def _monthly_summary_rows(self, filters: "GenericQueryFilters") -> list[dict[str, object]]:
        return list(
            self._monthly_summary_queryset(filters)
            .values(
                "organization__name",
                "facility__name",
                "reporting_period__name",
                "year",
                "month",
                "scope",
            )
            .annotate(total_co2e=Coalesce(Sum("total_co2e"), ZERO))
            .order_by("year", "month", "scope")
        )

    def _distinct_period_count(self, rows: list[dict[str, object]]) -> int:
        return len(
            {
                (int(row["year"]), int(row["month"]))
                for row in rows
                if row.get("year") is not None and row.get("month") is not None
            }
        )

    def _emissions_result(self, filters: "GenericQueryFilters", query_type: str) -> dict[str, object]:
        activity_rows = [
            {
                "organization": row["organization__name"],
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": int(row["activity_date__year"]),
                "month": int(row["activity_date__month"]),
                "scope": row["category__scope"],
                "total_co2e": float(row["total_co2e"]),
            }
            for row in self._activity_emissions_rows(filters)
        ]
        summary_rows = [
            {
                "organization": row["organization__name"],
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": int(row["year"]),
                "month": int(row["month"]),
                "scope": row["scope"],
                "total_co2e": float(row["total_co2e"]),
            }
            for row in self._monthly_summary_rows(filters)
        ]

        if query_type in {"comparison", "trend"}:
            if self._distinct_period_count(summary_rows) >= 2:
                rows = summary_rows
                source_table = "MonthlyEmissionSummary"
                data_source_code = "monthly_summary"
            elif self._distinct_period_count(activity_rows) >= 2:
                rows = activity_rows
                source_table = "EmissionActivity"
                data_source_code = "emission_activity"
            elif summary_rows:
                rows = summary_rows
                source_table = "MonthlyEmissionSummary"
                data_source_code = "monthly_summary"
            else:
                rows = activity_rows
                source_table = "EmissionActivity"
                data_source_code = "emission_activity"
        elif query_type in {"ranking", "summary", "latest"} and summary_rows:
            rows = summary_rows
            source_table = "MonthlyEmissionSummary"
            data_source_code = "monthly_summary"
        elif activity_rows:
            rows = activity_rows
            source_table = "EmissionActivity"
            data_source_code = "emission_activity"
        else:
            rows = summary_rows
            source_table = "MonthlyEmissionSummary"
            data_source_code = "monthly_summary"

        if query_type == "comparison":
            data, metadata, fallback = self._comparison_payload(rows, filters)
        elif query_type == "trend":
            data, metadata, fallback = self._trend_payload(rows)
        elif query_type == "ranking":
            data, metadata, fallback = self._ranking_payload(rows, filters)
        elif query_type == "summary":
            data, metadata, fallback = self._summary_payload(rows, filters)
        elif query_type == "latest":
            data, metadata, fallback = self._latest_payload(rows)
        else:
            data, metadata, fallback = self._total_payload(rows)

        return self.tool._standard_result(
            metric="emissions",
            query_type=query_type,
            filters=filters,
            data=data,
            metadata=metadata,
            fallback_answer=fallback,
            table_name=source_table,
            aggregation=query_type,
            data_source_code=data_source_code,
        )

    def _latest_payload(self, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object], str]:
        if not rows:
            return [], {"summary": "No matched emission records were found."}, "I could not find matched emissions data for that request."
        latest_year = max(int(row["year"] or 0) for row in rows)
        latest_month = max(int(row["month"] or 0) for row in rows if int(row["year"] or 0) == latest_year)
        latest_rows = [
            row
            for row in rows
            if int(row["year"] or 0) == latest_year and int(row["month"] or 0) == latest_month
        ]
        total = sum(float(row["total_co2e"]) for row in latest_rows)
        fallback = " ".join(
            f"{str(row['scope']).replace('S', 'Scope ')} emissions for {row.get('facility') or 'the selected facility'} were {row['total_co2e']:.2f} tCO2e in {row.get('reporting_period') or 'the selected reporting period'} ({row['year']}-{row['month']:02d})."
            for row in latest_rows[:3]
        )
        return latest_rows, {
            "summary": f"Latest matched emissions total {total:.2f} tCO2e for {MONTH_NAMES.get(latest_month, latest_month)} {latest_year}.",
            "period": {"year": latest_year, "month": latest_month},
            "aggregate_total_co2e": round(total, 2),
        }, fallback

    def _ranking_payload(self, rows: list[dict[str, object]], filters: "GenericQueryFilters") -> tuple[list[dict[str, object]], dict[str, object], str]:
        if not rows:
            message = "I could not find matched emissions data for that facility ranking request."
            return [], {"summary": message}, message

        latest_year = max(int(row["year"] or 0) for row in rows)
        latest_month = max(int(row["month"] or 0) for row in rows if int(row["year"] or 0) == latest_year)
        latest_rows = [
            row
            for row in rows
            if int(row["year"] or 0) == latest_year and int(row["month"] or 0) == latest_month
        ]

        totals_by_facility: dict[str, float] = defaultdict(float)
        reporting_period_by_facility: dict[str, str] = {}
        for row in latest_rows:
            facility = str(row.get("facility") or row.get("organization") or "Unknown facility")
            totals_by_facility[facility] += float(row["total_co2e"])
            if row.get("reporting_period"):
                reporting_period_by_facility[facility] = str(row["reporting_period"])

        ranked = sorted(totals_by_facility.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            message = "I could not find facility totals for the latest matched period."
            return [], {"summary": message}, message

        data = [
            {
                "rank": index + 1,
                "facility": facility,
                "reporting_period": reporting_period_by_facility.get(facility, ""),
                "year": latest_year,
                "month": latest_month,
                "total_co2e": round(total, 2),
            }
            for index, (facility, total) in enumerate(ranked)
        ]

        top = data[0]
        scope_text = ""
        if len(filters.scopes) == 1:
            scope_text = f"{str(next(iter(filters.scopes))).replace('S', 'Scope ')} "
        period_label = f"{MONTH_NAMES.get(latest_month, latest_month)} {latest_year}"
        fallback = (
            f"The highest {scope_text}emitting facility in {period_label} was {top['facility']} "
            f"with {top['total_co2e']:.2f} tCO2e."
        )
        summary = f"Ranked {len(data)} facilities for the latest matched period ({period_label})."
        return data, {
            "summary": summary,
            "period": {"year": latest_year, "month": latest_month},
            "top_facility": top["facility"],
            "top_total_co2e": top["total_co2e"],
        }, fallback

    def _summary_payload(self, rows: list[dict[str, object]], filters: "GenericQueryFilters") -> tuple[list[dict[str, object]], dict[str, object], str]:
        if not rows:
            message = "I could not find matched emissions summary data for that request."
            return [], {"summary": message}, message

        totals_by_scope: dict[str, float] = defaultdict(float)
        facilities = sorted({str(row.get("facility") or "") for row in rows if row.get("facility")})
        organizations = sorted({str(row.get("organization") or "") for row in rows if row.get("organization")})
        periods = sorted({str(row.get("reporting_period") or "") for row in rows if row.get("reporting_period")})
        years = sorted({int(row.get("year") or 0) for row in rows if row.get("year") is not None})

        for row in rows:
            scope = str(row.get("scope") or "Unknown")
            totals_by_scope[scope] += float(row["total_co2e"])

        ordered_scopes = ["S1", "S2", "S3"]
        data = [
            {
                "scope": scope,
                "total_co2e": round(totals_by_scope[scope], 2),
            }
            for scope in ordered_scopes
            if scope in totals_by_scope
        ]
        for scope, total in sorted(totals_by_scope.items()):
            if scope not in ordered_scopes:
                data.append({"scope": scope, "total_co2e": round(total, 2)})

        grand_total = round(sum(item["total_co2e"] for item in data), 2)
        summary_lines = [f"{str(item['scope']).replace('S', 'Scope ')}: {item['total_co2e']:.2f} tCO2e" for item in data]
        summary_lines.append(f"Total: {grand_total:.2f} tCO2e")

        if len(facilities) == 1:
            entity = facilities[0]
        elif len(organizations) == 1:
            entity = organizations[0]
        else:
            entity = "the selected organization"

        if len(periods) == 1:
            period_text = periods[0]
        elif len(years) == 1 and years[0]:
            period_text = f"{years[0]}"
        else:
            period_text = "the matched period"

        fallback = f"Emissions summary for {entity} in {period_text}: " + " ".join(summary_lines)
        return data, {
            "summary": fallback,
            "aggregate_total_co2e": grand_total,
            "scopes": [item["scope"] for item in data],
        }, fallback

    def _total_payload(self, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object], str]:
        total = sum(float(item["total_co2e"]) for item in rows)
        fallback = self._friendly_total_answer(rows, total) if rows else "I could not find matched emissions data for that request."
        return rows, {
            "summary": fallback if rows else "No matched emission records were found.",
            "aggregate_total_co2e": round(total, 2),
        }, fallback

    def _friendly_total_answer(self, data: list[dict[str, object]], total: float) -> str:
        scopes = sorted({str(item.get("scope") or "") for item in data if item.get("scope")})
        periods = sorted({str(item.get("reporting_period") or "") for item in data if item.get("reporting_period")})
        organizations = sorted({str(item.get("organization") or "") for item in data if item.get("organization")})
        facilities = sorted({str(item.get("facility") or "") for item in data if item.get("facility")})
        years = sorted({int(item.get("year")) for item in data if item.get("year") is not None})
        months = sorted({int(item.get("month")) for item in data if item.get("month") is not None})

        if len(scopes) == 1:
            subject = f"{scopes[0].replace('S', 'Scope ')} emissions"
        else:
            subject = "total emissions"

        if len(facilities) == 1:
            entity = facilities[0]
        elif len(organizations) == 1:
            entity = organizations[0]
        else:
            entity = "the selected organization"

        if len(years) == 1 and len(months) == 1:
            period_text = f" in {MONTH_NAMES.get(months[0], months[0])} {years[0]}"
        else:
            period_text = f" in {periods[0]}" if len(periods) == 1 and periods[0] else ""
        return f"{subject.capitalize()} for {entity}{period_text} were {total:,.2f} tCO2e."

    def _comparison_payload(self, rows: list[dict[str, object]], filters: "GenericQueryFilters") -> tuple[list[dict[str, object]], dict[str, object], str]:
        if filters.years and len(filters.years) >= 2 and not filters.month_year_pairs:
            totals_by_year: dict[int, float] = defaultdict(float)
            for row in rows:
                totals_by_year[int(row["year"])] += float(row["total_co2e"])
            ordered_years = [(year, totals_by_year[year]) for year in sorted(totals_by_year) if year in set(filters.years)]
            if len(ordered_years) >= 2:
                (first_year, first_total), (second_year, second_total) = ordered_years[0], ordered_years[-1]
                delta = second_total - first_total
                data = [
                    {"year": first_year, "label": f"{first_year}", "total_co2e": round(first_total, 2)},
                    {"year": second_year, "label": f"{second_year}", "total_co2e": round(second_total, 2)},
                ]
                summary = (
                    f"Compared {first_year} ({first_total:.2f} tCO2e) "
                    f"with {second_year} ({second_total:.2f} tCO2e). "
                    f"Delta {delta:.2f} tCO2e."
                )
                return data, {"summary": summary, "delta_total_co2e": round(delta, 2)}, summary

        totals_by_period: dict[tuple[int, int], float] = defaultdict(float)
        for row in rows:
            totals_by_period[(int(row["year"]), int(row["month"]))] += float(row["total_co2e"])
        ordered = sorted(totals_by_period.items())
        if len(ordered) < 2:
            message = "Not enough matched periods were found for a comparison."
            return [], {"summary": message}, message
        (first_year, first_month), first_total = ordered[-2]
        (second_year, second_month), second_total = ordered[-1]
        delta = second_total - first_total
        data = [
            {"year": first_year, "month": first_month, "label": f"{MONTH_NAMES.get(first_month, first_month)} {first_year}", "total_co2e": round(first_total, 2)},
            {"year": second_year, "month": second_month, "label": f"{MONTH_NAMES.get(second_month, second_month)} {second_year}", "total_co2e": round(second_total, 2)},
        ]
        summary = (
            f"Compared {MONTH_NAMES.get(first_month, first_month)} {first_year} ({first_total:.2f} tCO2e) "
            f"with {MONTH_NAMES.get(second_month, second_month)} {second_year} ({second_total:.2f} tCO2e). "
            f"Delta {delta:.2f} tCO2e."
        )
        return data, {"summary": summary, "delta_total_co2e": round(delta, 2)}, summary

    def _trend_payload(self, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object], str]:
        totals_by_period: dict[tuple[int, int], float] = defaultdict(float)
        scopes_by_period: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for row in rows:
            key = (int(row["year"]), int(row["month"]))
            value = float(row["total_co2e"])
            totals_by_period[key] += value
            scopes_by_period[key][str(row["scope"])] += value
        data = [
            {
                "year": year,
                "month": month,
                "label": f"{year}-{month:02d}",
                "total_co2e": round(total, 2),
                "scopes": {scope: round(amount, 2) for scope, amount in dict(scopes_by_period[(year, month)]).items()},
            }
            for (year, month), total in sorted(totals_by_period.items())
        ]
        if not data:
            message = "I could not find matched emissions trend data for that request."
            return [], {"summary": message}, message
        facility_names = sorted({str(row.get("facility") or "") for row in rows if row.get("facility")})
        entity = facility_names[0] if len(facility_names) == 1 else "the selected scope"
        summary = f"Built a monthly emissions trend for {entity} across {len(data)} periods."
        return data, {"summary": summary}, summary

    def _breakdown_result(self, filters: "GenericQueryFilters") -> dict[str, object]:
        rows = list(
            self.tool._apply_common_filters(
                EmissionBreakdown.objects.select_related(
                    "category",
                    "subcategory",
                    "scope3_category",
                    "gas_type",
                    "facility",
                    "organization",
                    "reporting_period",
                ),
                filters,
                period_year_field="reporting_period__year",
            )
            .filter(scope__in=filters.scopes if filters.scopes else ["S1", "S2", "S3"])
            .values(
                "scope",
                "category__name",
                "subcategory__name",
                "scope3_category__name",
                "gas_type__gas_name",
                "organization__name",
                "facility__name",
                "reporting_period__name",
                "reporting_period__year",
            )
            .annotate(total_co2e=Coalesce(Sum("total_co2e"), ZERO))
            .order_by("scope", "category__name")
        )
        data = [
            {
                "scope": row["scope"],
                "category": row["category__name"],
                "subcategory": row["subcategory__name"],
                "scope3_category": row["scope3_category__name"],
                "gas_type": row["gas_type__gas_name"],
                "organization": row["organization__name"],
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": row["reporting_period__year"],
                "total_co2e": float(row["total_co2e"]),
            }
            for row in rows
        ]
        summary = f"Built an emissions breakdown from {len(data)} aggregated rows."
        return self.tool._standard_result(
            metric="emissions",
            query_type="breakdown",
            filters=filters,
            data=data,
            metadata={"summary": summary},
            fallback_answer=summary if data else "I could not find matched emissions breakdown data for that request.",
            table_name="EmissionBreakdown",
            aggregation="breakdown",
            data_source_code="emission_breakdown",
        )


class EnergyHandler(BaseSQLHandler):
    metric = "energy"

    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        return metric == self.metric

    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        rows = list(
            self.tool._apply_common_filters(
                EnergySummary.objects.select_related("facility", "reporting_period", "unit"),
                filters,
                period_year_field="reporting_period__year",
            )
            .values("facility__name", "reporting_period__name", "reporting_period__year", "unit__code")
            .annotate(
                total_energy=Coalesce(Sum("total_energy"), ZERO),
                renewable_energy=Coalesce(Sum("renewable_energy"), ZERO),
                non_renewable_energy=Coalesce(Sum("non_renewable_energy"), ZERO),
            )
            .order_by("facility__name", "reporting_period__name")
        )
        data = [
            {
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": row["reporting_period__year"],
                "unit": row["unit__code"],
                "total_energy": float(row["total_energy"]),
                "renewable_energy": float(row["renewable_energy"]),
                "non_renewable_energy": float(row["non_renewable_energy"]),
            }
            for row in rows
        ]
        fallback = (
            f"Total energy for {data[0].get('facility') or 'the selected facility'} is {data[0]['total_energy']:.2f} {data[0].get('unit') or ''}, "
            f"including {data[0]['renewable_energy']:.2f} renewable and {data[0]['non_renewable_energy']:.2f} non-renewable."
            if data else "I could not find matched energy data for that request."
        )
        return self.tool._standard_result(
            metric="energy",
            query_type=query_type,
            filters=filters,
            data=data,
            metadata={"summary": f"Matched {len(data)} energy summary rows."},
            fallback_answer=fallback,
            table_name="EnergySummary",
            aggregation=query_type,
            data_source_code="energy_summary",
        )


class WaterHandler(BaseSQLHandler):
    metric = "water"

    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        return metric == self.metric

    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        rows = list(
            self.tool._apply_common_filters(
                WaterUsage.objects.select_related("facility", "reporting_period", "unit"),
                filters,
                period_year_field="reporting_period__year",
            )
            .values("facility__name", "reporting_period__name", "reporting_period__year", "category", "unit__code")
            .annotate(amount=Coalesce(Sum("amount"), ZERO))
            .order_by("facility__name", "category")
        )
        data = [
            {
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": row["reporting_period__year"],
                "category": row["category"],
                "unit": row["unit__code"],
                "amount": float(row["amount"]),
            }
            for row in rows
        ]
        total = sum(item["amount"] for item in data)
        fallback = (
            f"Total water usage for {data[0].get('facility') or 'the selected facility'} across the matched records is {total:.2f} {data[0].get('unit') or ''}."
            if data else "I could not find matched water data for that request."
        )
        return self.tool._standard_result(
            metric="water",
            query_type=query_type,
            filters=filters,
            data=data,
            metadata={"summary": f"Matched {len(data)} water usage rows.", "aggregate_amount": round(total, 2)},
            fallback_answer=fallback,
            table_name="WaterUsage",
            aggregation=query_type,
            data_source_code="water_usage",
        )


class WasteHandler(BaseSQLHandler):
    metric = "waste"

    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        return metric == self.metric

    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        rows = list(
            self.tool._apply_common_filters(
                WasteSummary.objects.select_related("facility", "reporting_period", "unit"),
                filters,
                period_year_field="reporting_period__year",
            )
            .values("facility__name", "reporting_period__name", "reporting_period__year", "unit__code")
            .annotate(
                total_waste=Coalesce(Sum("total_waste"), ZERO),
                hazardous=Coalesce(Sum("hazardous"), ZERO),
                non_hazardous=Coalesce(Sum("non_hazardous"), ZERO),
            )
            .order_by("facility__name", "reporting_period__name")
        )
        data = [
            {
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "year": row["reporting_period__year"],
                "unit": row["unit__code"],
                "total_waste": float(row["total_waste"]),
                "hazardous": float(row["hazardous"]),
                "non_hazardous": float(row["non_hazardous"]),
            }
            for row in rows
        ]
        total = sum(item["total_waste"] for item in data)
        fallback = (
            f"Total waste for {data[0].get('facility') or 'the selected facility'} across the matched records is {total:.2f} {data[0].get('unit') or ''}."
            if data else "I could not find matched waste data for that request."
        )
        return self.tool._standard_result(
            metric="waste",
            query_type=query_type,
            filters=filters,
            data=data,
            metadata={"summary": f"Matched {len(data)} waste summary rows.", "aggregate_total_waste": round(total, 2)},
            fallback_answer=fallback,
            table_name="WasteSummary",
            aggregation=query_type,
            data_source_code="waste_summary",
        )


class CreditsHandler(BaseSQLHandler):
    metric = "credits"

    def can_handle(self, query: str, *, metric: str, query_type: str) -> bool:
        return metric == self.metric

    def execute(self, filters: "GenericQueryFilters", *, query_type: str) -> dict[str, object]:
        from apps.summary.models import CarbonCredit
        rows = list(
            self.tool._apply_common_filters(
                CarbonCredit.objects.select_related("facility", "reporting_period"),
                filters,
                period_year_field="reporting_period__year",
            )
            .filter(status="retired")
            .values("facility__name", "reporting_period__name", "project_name", "quantity_tco2e", "status", "vintage_year")
            .order_by("-vintage_year")
        )
        data = [
            {
                "facility": row["facility__name"],
                "reporting_period": row["reporting_period__name"],
                "project_name": row["project_name"],
                "quantity_tco2e": float(row["quantity_tco2e"]),
                "status": row["status"],
                "vintage_year": row["vintage_year"],
            }
            for row in rows
        ]
        total = sum(item["quantity_tco2e"] for item in data)
        fallback = (
            f"Total retired carbon credits: {total:.2f} tCO2e across {len(data)} record(s)."
            if data else "No retired carbon credits found for that selection."
        )
        return self.tool._standard_result(
            metric="credits",
            query_type=query_type,
            filters=filters,
            data=data,
            metadata={"summary": fallback, "aggregate_quantity_tco2e": round(total, 2)},
            fallback_answer=fallback,
            table_name="CarbonCredit",
            aggregation=query_type,
            data_source_code="carbon_credit",
        )
