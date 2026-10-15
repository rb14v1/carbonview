from __future__ import annotations
 
import logging
import re
from functools import lru_cache
from typing import Any
 
from apps.company.models import Facility, Organization, ReportingPeriod
 
from .common import (
    build_source_example,
    extract_month_numbers,
    extract_month_year_pairs,
    extract_scope_filters,
    extract_years,
    get_registered_sql_handlers,
    load_domain_config,
)
from .types import GenericQueryFilters, SearchScope
 
logger = logging.getLogger(__name__)

_SCOPE_LIST_PATTERN = re.compile(r"\bscopes?\s*([123](?:\s*(?:,|and)?\s*[123]){1,2})\b")


@lru_cache(maxsize=1)
def _organization_name_pairs() -> tuple[tuple[int, str], ...]:
    return tuple(Organization.objects.values_list("id", "name"))


@lru_cache(maxsize=1)
def _facility_name_pairs() -> tuple[tuple[int, str], ...]:
    return tuple(Facility.objects.values_list("id", "name"))


@lru_cache(maxsize=1)
def _reporting_period_name_pairs() -> tuple[tuple[int, str], ...]:
    return tuple(ReportingPeriod.objects.values_list("id", "name"))


@lru_cache(maxsize=1024)
def _facility_organization_id(facility_id: int) -> int | None:
    return Facility.objects.filter(id=facility_id).values_list("organization_id", flat=True).first()

class SQLTool:
    """Production-grade SQL dispatcher with enhanced explainability and error handling."""
 
    def __init__(self):
        self.domain_config = load_domain_config()
        self.handlers = get_registered_sql_handlers(self)
        self._entity_sources = {
            Facility: _facility_name_pairs,
            Organization: _organization_name_pairs,
            ReportingPeriod: _reporting_period_name_pairs,
        }

    def execute(self, query: str, scope: SearchScope | None = None, *, query_type: str | None = None) -> dict[str, object]:
        """Executes the best-matching SQL handler or returns a structured fallback."""
        normalized = (query or "").strip().lower()
        metric = self._detect_metric(normalized)
        resolved_type = query_type or self._detect_query_type(normalized)
       
        try:
            filters = self._resolve_filters(query, scope, query_type=resolved_type)
        except Exception as e:
            logger.error(f"Filter resolution failed: {e}")
            return self._fallback_error_result("Could not resolve database filters for this query.")
 
        result = None
        for handler in self.handlers:
            if handler.can_handle(query, metric=metric, query_type=resolved_type):
                try:
                    result = handler.execute(filters, query_type=resolved_type)
                    break
                except Exception as e:
                    logger.error(f"SQL Handler execution error: {e}")
                    continue
 
        if result is None:
            # ✅ PRODUCTION FIX: Return structured data instead of crashing
            return self._fallback_error_result(f"No specific database records found for {metric} in this context.")
 
        self._log_execution(query=query, metric=metric, query_type=resolved_type, filters=filters, result=result)
        return result
 
    def _fallback_error_result(self, message: str) -> dict[str, object]:
        return {
            "tool": "sql",
            "route": "sql",
            "data": [],
            "metadata": {"error": message, "row_count": 0},
            "fallback_answer": message
        }
 
    def _detect_metric(self, normalized_query: str) -> str:
        """Categorizes the query into specific carbon/resource domains."""
        if any(k in normalized_query for k in ["energy", "renewable", "power", "electricity"]):
            return "energy"
        if "water" in normalized_query:
            return "water"
        if any(k in normalized_query for k in ["waste", "recycl", "landfill"]):
            return "waste"
        if any(k in normalized_query for k in ["credit", "credits", "retired", "offset", "offsets"]):
            return "credits"
        return "emissions"
 
    def _detect_query_type(self, normalized_query: str) -> str:
        """Determines the analytical intent of the query."""
        has_multi_scope_signal = len(self._extract_scope_filters(normalized_query)) > 1
        if any(term in normalized_query for term in {"highest", "lowest", "most", "least", "top", "maximum", "minimum"}):
            if any(term in normalized_query for term in {"facility", "facilities", "site", "sites", "plant", "plants", "campus", "hub", "centre", "center"}):
                return "ranking"
        if has_multi_scope_signal and any(
            term in normalized_query for term in {"value", "values", "total", "totals", "what is", "what are", "give me", "show me"}
        ):
            return "summary"
        if "summary" in normalized_query:
            return "summary"
        if any(term in normalized_query for term in {"breakdown", "split by", "category"}):
            return "breakdown"
        if any(term in normalized_query for term in {"compare", "comparison", "higher", "lower", "vs"}):
            return "comparison"
        if any(term in normalized_query for term in {"latest", "current", "recent"}):
            return "latest"
        if "trend" in normalized_query or "monthly" in normalized_query:
            return "trend"
        return "total"

    def _extract_scope_filters(self, query: str) -> tuple[str, ...]:
        normalized = (query or "").lower()
        scopes = set(extract_scope_filters(normalized))
        for match in _SCOPE_LIST_PATTERN.finditer(normalized):
            for scope_number in re.findall(r"[123]", match.group(1)):
                scopes.add(f"S{scope_number}")
        return tuple(sorted(scopes))

    def _model_has_field(self, model, field_name: str) -> bool:
        return any(field.name == field_name for field in model._meta.get_fields())

    def _apply_common_filters(self, queryset, filters: GenericQueryFilters, *, period_year_field: str) -> Any:
        """Apply shared entity and time filters across SQL-backed querysets."""
        model = queryset.model

        if filters.organization_id:
            if self._model_has_field(model, "organization"):
                queryset = queryset.filter(organization_id=filters.organization_id)
            elif self._model_has_field(model, "facility"):
                queryset = queryset.filter(facility__organization_id=filters.organization_id)

        if filters.facility_id and self._model_has_field(model, "facility"):
            queryset = queryset.filter(facility_id=filters.facility_id)

        if filters.reporting_period_id and self._model_has_field(model, "reporting_period"):
            queryset = queryset.filter(reporting_period_id=filters.reporting_period_id)

        if filters.years:
            queryset = queryset.filter(**{f"{period_year_field}__in": list(filters.years)})

        return queryset

    def _resolve_filters(self, query: str, scope: SearchScope | None, *, query_type: str) -> GenericQueryFilters:
        """Resolves natural language entities into database-level IDs."""
        entities = dict((scope or SearchScope()).to_domain_filters()["entities"])
        org_id = entities.get("organization")
        fac_id = entities.get("facility")
        rp_id = entities.get("reporting_period")
 
        # Prioritize query-based entities if not provided in request scope
        if fac_id is None:
            fac_id = self._match_entity_id(query, Facility)
        if org_id is None:
            org_id = self._match_entity_id(query, Organization)
        if rp_id is None:
            rp_id = self._match_entity_id(query, ReportingPeriod)

        years = tuple(sorted(int(year) for year in extract_years(query)))
        pairs = tuple(dict.fromkeys(extract_month_year_pairs(query)))
        months = tuple(sorted(extract_month_numbers(query)))
        scopes = self._extract_scope_filters(query)
        has_all_history_signal = self._has_all_history_signal(query)

        if has_all_history_signal:
            rp_id = None
 
        # Default to latest period if query is simple (e.g., "total emissions")
        if self._should_use_default_reporting_period(query_type, rp_id, years, pairs, has_all_history_signal):
            rp_id = self._latest_reporting_period_id(organization_id=org_id, facility_id=fac_id, years=years)
 
        return GenericQueryFilters(
            entities={"organization": org_id, "facility": fac_id, "reporting_period": rp_id},
            dimensions={"scopes": list(scopes)},
            time_range={"years": list(years), "month_year_pairs": [list(p) for p in pairs], "months": list(months)},
        )

    def _match_entity_id(self, query: str, source) -> int | None:
        """Match query text to entity names with length-priority and cached model loaders."""
        normalized = (query or "").lower()
        matches = []
        if hasattr(source, "_meta"):
            pair_loader = self._entity_sources.get(source)
            pairs = pair_loader() if pair_loader is not None else tuple(source.objects.values_list("id", "name"))
        else:
            pair_loader = self._entity_sources.get(source.model)
            pairs = pair_loader() if pair_loader is not None else tuple(source.values_list("id", "name"))
        for eid, name in pairs:
            label = str(name or "").strip().lower()
            if label and label in normalized:
                matches.append((eid, len(label)))
       
        # ✅ PRODUCTION FIX: Pick the longest match (e.g., "North Plant" over "Plant")
        if matches:
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[0][0]
        return None
 
    def _log_execution(self, *, query: str, metric: str, query_type: str, filters: GenericQueryFilters, result: dict[str, object]) -> None:
        """Logs detailed execution telemetry for the AICTE Explainability section."""
        logger.info(
            "SQLTool Execution Trace",
            extra={
                "input_query": query,
                "metric": metric,
                "intent": query_type,
                "filters": filters.to_metadata(),
                "records_retrieved": (result.get("metadata") or {}).get("row_count", 0),
            },
        )
 
    def _standard_result(self, *, metric: str, query_type: str, filters: GenericQueryFilters, data: list[dict[str, object]],
                        metadata: dict[str, object], fallback_answer: str, table_name: str, aggregation: str,
                        data_source_code: str) -> dict[str, object]:
        """Constructs the final production-ready payload with explainability metadata."""
        rows_sample = data[:5]
        source = {
            "table": table_name,
            "filters": filters.to_metadata(),
            "aggregation": aggregation,
            "line": f"Data extracted from {table_name} for {aggregation}",
            "example": build_source_example(rows_sample[0] if rows_sample else None)
        }
        return {
            "tool": "sql",
            "route": "sql",
            "data": data,
            "metadata": {
                "filters": filters.to_metadata(),
                "row_count": len(data),
                "data_source": data_source_code,
                **metadata,
            },
            "fallback_answer": fallback_answer,
            "metric": metric,
            "type": query_type,
            "source": source,
        }
 
    def _apply_common_filters(self, queryset, filters: GenericQueryFilters, *, period_year_field: str):
        """Apply shared entity and time filters used by domain SQL handlers."""
        if filters.organization_id is not None:
            model_fields = {field.name for field in queryset.model._meta.get_fields()}
            if "organization" in model_fields:
                queryset = queryset.filter(organization_id=filters.organization_id)
            elif "facility" in model_fields:
                queryset = queryset.filter(facility__organization_id=filters.organization_id)
 
        if filters.facility_id is not None:
            queryset = queryset.filter(facility_id=filters.facility_id)
 
        if filters.reporting_period_id is not None:
            queryset = queryset.filter(reporting_period_id=filters.reporting_period_id)
 
        if filters.years:
            queryset = queryset.filter(**{f"{period_year_field}__in": filters.years})
 
        return queryset
 
    def _latest_reporting_period_id(self, organization_id: int | None, facility_id: int | None, years: tuple[int, ...]) -> int | None:
        period_qs = ReportingPeriod.objects.all()
        if facility_id:
            organization_id = organization_id or _facility_organization_id(facility_id)
        if organization_id:
            period_qs = period_qs.filter(organization_id=organization_id)
        if len(years) == 1:
            period_qs = period_qs.filter(year=years[0])
        return period_qs.order_by("-year", "-start_date").values_list("id", flat=True).first()
 
    def _has_all_history_signal(self, query: str) -> bool:
        normalized = (query or "").strip().lower()
        return any(
            phrase in normalized
            for phrase in {
                "all years",
                "for all years",
                "across all years",
                "over all years",
                "all time",
                "entire history",
                "overall history",
                "full history",
            }
        )

    def _should_use_default_reporting_period(self, q_type, rp_id, years, pairs, has_all_history_signal=False) -> bool:
        return not any([rp_id, q_type in {"comparison", "trend"}, len(years) > 1, len(pairs) > 1, has_all_history_signal])
