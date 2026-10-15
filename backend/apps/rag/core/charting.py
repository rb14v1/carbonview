from __future__ import annotations

from collections import defaultdict
import re

from ..sql_tool import SQLTool
from .types import SearchScope


SUPPORTED_CHART_METRIC_KEYWORDS = {
    "emission",
    "emissions",
    "scope",
    "energy",
    "renewable",
    "non-renewable",
    "power",
    "water",
    "waste",
}

_SCOPE_LIST_PATTERN = re.compile(r"\bscopes?\s*([123](?:\s*(?:,|and)?\s*[123]){1,2})\b")


def _has_multi_scope_signal(normalized: str) -> bool:
    direct_mentions = [scope for scope in ["scope 1", "scope 2", "scope 3", "s1", "s2", "s3"] if scope in normalized]
    if len(direct_mentions) > 1:
        return True
    for match in _SCOPE_LIST_PATTERN.finditer(normalized):
        if len(re.findall(r"[123]", match.group(1))) > 1:
            return True
    return False


class ChartTool:
    """Chart generator backed by structured SQL results instead of retrieved prose."""

    def __init__(self, sql_tool: SQLTool | None = None):
        self.sql_tool = sql_tool or SQLTool()

    def generate(self, query: str, scope: SearchScope | None = None) -> dict[str, object] | None:
        normalized = (query or "").lower()
        if not any(term in normalized for term in SUPPORTED_CHART_METRIC_KEYWORDS):
            return None

        try:
            if any(term in normalized for term in {"energy", "renewable", "non-renewable", "power"}):
                result = self.sql_tool.execute(query, scope, query_type="latest")
                return self.build_from_sql_result(result)

            has_multi_scope = _has_multi_scope_signal(normalized)
            if any(term in normalized for term in {"breakdown", "split by", "scope breakdown"}) or has_multi_scope:
                result = self.sql_tool.execute(query, scope, query_type="breakdown")
                return self.build_from_sql_result(result)

            result = self.sql_tool.execute(query, scope, query_type="trend")
            return self.build_from_sql_result(result)
        except Exception:
            return None

    def build_from_sql_result(self, result: dict[str, object] | None) -> dict[str, object] | None:
        if not result:
            return None
        query_type = str(result.get("type") or "")
        metric = str(result.get("metric") or "")
        if metric == "energy":
            return self._energy_chart(result)
        if query_type == "breakdown":
            return self._breakdown_chart(result)
        return self._trend_chart(result)

    def _energy_chart(self, result: dict[str, object]) -> dict[str, object] | None:
        records = result.get("data", [])
        if not records:
            return None
        record = records[0]
        source = dict(result.get("source") or {})
        return {
            "chart_type": "pie",
            "title": f"Energy Mix for {record.get('facility') or 'Selected facility'}",
            "labels": ["Renewable", "Non-renewable"],
            "series": [
                {
                    "name": "Energy",
                    "data": [
                        round(float(record.get("renewable_energy") or 0.0), 2),
                        round(float(record.get("non_renewable_energy") or 0.0), 2),
                    ],
                }
            ],
            "unit": record.get("unit") or "",
            "summary": result.get("metadata", {}).get("summary", ""),
            "source_line": source.get("line") or "",
            "example": source.get("example"),
            "data_points_count": 2,
        }

    def _breakdown_chart(self, result: dict[str, object]) -> dict[str, object] | None:
        records = result.get("data", [])
        if not records:
            return None

        totals_by_scope: dict[str, float] = defaultdict(float)
        for record in records:
            totals_by_scope[str(record.get("scope") or "")] += float(record.get("total_co2e") or 0.0)

        labels = sorted(scope for scope in totals_by_scope if scope)
        if not labels:
            return None
        source = dict(result.get("source") or {})
        return {
            "chart_type": "bar",
            "title": "Scope Breakdown",
            "labels": labels,
            "series": [
                {
                    "name": "Emissions",
                    "data": [round(totals_by_scope[label], 2) for label in labels],
                }
            ],
            "unit": "tCO2e",
            "summary": result.get("metadata", {}).get("summary", ""),
            "source_line": source.get("line") or "",
            "example": source.get("example"),
            "data_points_count": len(labels),
        }

    def _trend_chart(self, result: dict[str, object]) -> dict[str, object] | None:
        records = result.get("data", [])
        if not records:
            return None

        labels = [str(record.get("label")) for record in records]
        scope_names = sorted(
            {
                scope_name
                for record in records
                for scope_name in dict(record.get("scopes") or {}).keys()
            }
        )
        if scope_names:
            series = [
                {
                    "name": scope_name,
                    "data": [
                        round(float(dict(record.get("scopes") or {}).get(scope_name, 0.0)), 2)
                        for record in records
                    ],
                }
                for scope_name in scope_names
            ]
        else:
            series = [
                {
                    "name": "Emissions",
                    "data": [round(float(record.get("total_co2e") or 0.0), 2) for record in records],
                }
            ]
        source = dict(result.get("source") or {})
        return {
            "chart_type": "line",
            "title": "Monthly Emissions Trend",
            "labels": labels,
            "series": series,
            "unit": "tCO2e",
            "summary": result.get("metadata", {}).get("summary", ""),
            "source_line": source.get("line") or "",
            "example": source.get("example"),
            "data_points_count": len(records),
        }


_DEFAULT_CHART_TOOL = ChartTool()


def generate_chart_payload(query: str, documents_or_scope, scope: SearchScope | None = None) -> dict[str, object] | None:
    """
    Backward-compatible chart entrypoint.

    Existing callers passed retrieved documents as the second argument.
    The new implementation ignores document lists and reads directly from PostgreSQL.
    """
    effective_scope = scope if scope is not None else (documents_or_scope if isinstance(documents_or_scope, SearchScope) else None)
    return _DEFAULT_CHART_TOOL.generate(query, scope=effective_scope)


def build_chart_payload_from_sql_result(result: dict[str, object] | None) -> dict[str, object] | None:
    return _DEFAULT_CHART_TOOL.build_from_sql_result(result)
