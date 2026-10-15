import logging
import re
from dataclasses import dataclass, field
from time import monotonic

from .core.common import extract_month_year_pairs, extract_scope_filters, extract_years, is_definition_query, load_domain_json


logger = logging.getLogger(__name__)

NUMERIC_INTENT_KEYWORDS = {
    "compare", "comparison", "trend", "total", "totals", "sum", "latest", "current", "recent",
}

METRIC_ALIASES = {
    "carbon",
    "co2",
    "co2e",
    "ghg",
    "emit",
    "emits",
    "emitting",
    "emitted",
}

RANKING_KEYWORDS = {
    "highest",
    "lowest",
    "most",
    "least",
    "top",
    "max",
    "maximum",
    "minimum",
}

FACILITY_TARGET_KEYWORDS = {
    "facility",
    "facilities",
    "site",
    "sites",
    "plant",
    "plants",
    "campus",
    "hub",
    "centre",
    "center",
}

DOMAIN_CONTEXT_KEYWORDS = {
    "carbon",
    "co2",
    "co2e",
    "ghg",
    "emission",
    "emissions",
    "scope",
    "facility",
    "facilities",
    "location",
    "locations",
    "located",
    "organization",
    "company",
    "site",
    "plant",
    "reporting",
    "reporting period",
    "period",
    "fy",
    "energy",
    "water",
    "waste",
    "air emission",
    "pollutant",
    "sustainability",
    "reduction",
    "reduction project",
    "reduction projects",
    "project",
    "projects",
    "carbon credit",
    "carbon credits",
    "credit",
    "credits",
    "retired",
    "credits retired",
    "offset",
    "offsets",
    "neutrality",
    "neutral",
    "neutrality claim",
    "neutrality claims",
    "gross emissions",
    "net emissions",
    "carbon neutral",
    "snapshot",
    "resource",
    "transition",
    "resource and transition snapshot",
    "performance signals",
    "facility footprint map",
    "scope breakdown",
    "scope 2 split",
    "top emission scope",
    "latest reporting month",
    "peak period",
    "renewable",
    "renewable energy share",
    "renewable energy",
    "recycl",
    "recycling",
    "recycle",
    "waste handled",
    "water categories",
    "credits retired",
    "retired credits",
    "total retired",
    "projects tracked",
    "next month estimate",
    "forecast insights",
    "recent trend estimate",
    "latest month total",
    "month-over-month change",
    "latest recorded month",
    "year over year change",
    "year-over-year change",
    "mwh",
    "kwh",
    "m3",
    "tco2e",
    "footprint",
    "breakdown",
    "category",
    "categories",
    "factor",
    "factors",
    "department",
    "reports",
    "reports & analytics",
    "reports and analytics",
    "annual report",
    "quarterly report",
    "esg report",
}

IDENTITY_PATTERNS = (
    r"\bwhat(?:'s| is)? your name\b",
    r"\bwho are you\b",
    r"\bwhat are you\b",
    r"\bare you (?:a |an )?assistant\b",
    r"\byour name\b",
    r"\bwhat\s+is\s+carbon\s*view\b",
    r"\bwhat'?s\s+carbon\s*view\b",
    r"\babout\s+carbon\s*view\b",
    r"\btell\s+(me\s+)?about\s+carbon\s*view\b",
)

PRODUCT_PATTERNS = (
    r"\bwhat\s+is\s+carbon\s*view\b",
    r"\bwhat'?s\s+carbon\s*view\b",
    r"\babout\s+carbon\s*view\b",
    r"\btell\s+(me\s+)?about\s+carbon\s*view\b",
    r"\bwhat\s+is\s+(the\s+)?ai\s+sustainability\s+assistant\b",
    r"\bwhat\s+(can|do)\s+you\s+(do|help|assist)\b",
    r"\bwhat\s+are\s+you\s+capable\s+of\b",
    r"\bai\s+sustainability\s+assistant\b",
    r"\bsustainability\s+assistant\b",
    r"\bwhat\s+are\s+you\b",
)

STATEMENT_PATTERNS = (
    r"^[a-z0-9 ,]+(?:means?|refers? to|is defined as|stands? for)\b.{10,}",
    r"^(?:fyi|note(?: that)?|just so you know)[,:]?\s+.{10,}",
    r"^(?:i (?:know|see|understand|think|believe|feel))\b",
    r"^explain\s+(me\s+)?about\s+this\b",
    r"^what\s+is\s+this\b",
    r"^tell\s+me\s+about\s+this\b",
    r"^(?:what|explain|describe)\s+(?:does\s+)?this\s+(?:show|mean|represent|chart|graph|number|section|widget|card)\s*[.!?]*$",
    r"^what\s+(?:are\s+)?these\s+(?:numbers?|values?|stats?|metrics?)\s*[.!?]*$",
)

GREETING_PATTERNS = (
    r"^(hi|hello|hey|hiya|howdy|sup|yo)[\s!.,]*$",
    r"^(hi|hello|hey)\s+there[\s!.,]*$",
    r"^how\s+are\s+you[\s!.,?]*$",
    r"^good\s+(morning|afternoon|evening)[\s!.,]*$",
    r"^(greetings|welcome|howdy)[\s!.,]*$",
)

UI_CONTEXT_PATTERNS = (
    r"^explain\s+(me\s+)?about\s+this\b",
    r"^what\s+is\s+this\b",
    r"^tell\s+me\s+about\s+this\b",
    r"^(?:what|explain|describe)\s+(?:does\s+)?this\s+(?:show|mean|represent|chart|graph|number|section|widget|card)\s*[.!?]*$",
    r"^what\s+(?:are\s+)?these\s+(?:numbers?|values?|stats?|metrics?)\s*[.!?]*$",
)

DASHBOARD_CONCEPT_KEYWORDS = {
    "resource and transition snapshot",
    "performance signals",
    "facility footprint map",
    "global facility map",
    "scope breakdown",
    "scope-wise breakdown",
    "scope 2 split",
    "carbon credits",
    "reduction projects",
    "emissions forecast",
    "energy",
    "renewable energy",
    "water usage",
    "waste handled",
    "credits retired",
    "retired credits",
    "total retired",
    "projects tracked",
    "water categories",
    "next month estimate",
    "forecast insights",
    "recent trend estimate",
    "latest month total",
    "month-over-month change",
    "latest recorded month",
    "selected-year highlights",
    "total emissions",
    "emissions trend",
    "facility locations",
    "reports & analytics",
    "reports and analytics",
    "annual report",
    "quarterly report",
    "esg report",
}

_SCOPE_LIST_PATTERN = re.compile(r"\bscopes?\s*([123](?:\s*(?:,|and)?\s*[123]){1,2})\b")

ALLOWED_LLM_ROUTES = {"rag", "sql", "sql_rag", "chart", "out_of_domain"}
_LLM_ROUTING_RETRY_COOLDOWN_SECS = 300.0


def _extract_scope_mentions(normalized: str) -> set[str]:
    scopes = set(extract_scope_filters(normalized))
    for match in _SCOPE_LIST_PATTERN.finditer(normalized):
        for scope_number in re.findall(r"[123]", match.group(1)):
            scopes.add(f"S{scope_number}")
    return scopes

@dataclass(frozen=True)
class AgentDecision:
    route: str
    reason: str
    needs_sql: bool
    needs_rag: bool
    needs_chart: bool
    metadata: dict = field(default_factory=dict)

class QueryRouter:
    """Deterministic router driven by per-domain keyword configuration."""

    def __init__(self):
        config = load_domain_json("agent_config.json")
        self.chart_keywords = {str(item).lower() for item in config.get("chart_keywords", [])}
        self.rag_keywords = {str(item).lower() for item in config.get("rag_keywords", [])}
        self.sql_keywords = {str(item).lower() for item in config.get("sql_keywords", [])}
        self.metric_keywords = {str(item).lower() for item in config.get("metric_keywords", [])}
        self._llm_routing_disabled = False
        self._llm_routing_disabled_at = 0.0
        self.domain_keywords = (
            self.chart_keywords
            | self.rag_keywords
            | self.sql_keywords
            | self.metric_keywords
            | DOMAIN_CONTEXT_KEYWORDS
        )

    def _has_domain_signal(self, normalized: str) -> bool:
        if not normalized:
            return False

        return any(keyword in normalized for keyword in self.domain_keywords)

    def _is_identity_question(self, normalized: str) -> bool:
        if not normalized:
            return False
        if self._is_product_question(normalized):
            return False
        return any(re.search(pattern, normalized) for pattern in IDENTITY_PATTERNS)

    def _has_named_dashboard_concept(self, normalized: str) -> bool:
        return any(keyword in normalized for keyword in DASHBOARD_CONCEPT_KEYWORDS)

    def _is_declarative_statement(self, normalized: str) -> bool:
        """Catches user statements that aren't questions or commands."""
        if normalized.endswith("?"):
            return False
        if self._has_named_dashboard_concept(normalized):
            return False
        return any(re.search(pat, normalized) for pat in STATEMENT_PATTERNS)

    def _is_ui_context_question(self, normalized: str) -> bool:
        if self._has_named_dashboard_concept(normalized):
            return False
        return any(re.search(pat, normalized) for pat in UI_CONTEXT_PATTERNS)

    def _is_greeting(self, normalized: str) -> bool:
        return any(re.search(pat, normalized) for pat in GREETING_PATTERNS)

    def _is_product_question(self, normalized: str) -> bool:
        return any(re.search(pattern, normalized) for pattern in PRODUCT_PATTERNS)

    def _looks_like_named_domain_entity(self, normalized: str) -> bool:
        if not normalized or self._has_domain_signal(normalized):
            return False
        has_name_term = any(
            term in normalized
            for term in {
                "program",
                "campus",
                "centre",
                "center",
                "hub",
                "facility",
                "site",
                "plant",
            }
        )
        has_code_or_year = bool(re.search(r"\b[a-z]{3}-[a-z]{3}\b", normalized) or re.search(r"\b20\d{2}\b", normalized))
        return has_name_term and has_code_or_year

    def _is_neutrality_location_query(self, normalized: str) -> bool:
        has_neutrality_signal = any(
            term in normalized
            for term in {"neutral", "neutrality", "carbon neutral", "net zero", "neutral area", "neutral location", "neutral facility"}
        )
        has_location_signal = any(
            term in normalized
            for term in {
                "area",
                "areas",
                "location",
                "locations",
                "region",
                "regions",
                "where",
                "facility",
                "facilities",
                "site",
                "sites",
                "which facilities",
                "which sites",
            }
        )
        return has_neutrality_signal and has_location_signal

    def _is_dashboard_concept_definition_question(self, normalized: str) -> bool:
        if not self._has_named_dashboard_concept(normalized):
            return False
        if not (
            is_definition_query(normalized)
            or "tell me about" in normalized
            or "tell about" in normalized
            or "explain" in normalized
        ):
            return False
        if extract_month_year_pairs(normalized) or extract_years(normalized):
            return False
        if "fy" in normalized or "reporting period" in normalized:
            return False
        return not any(
            phrase in normalized
            for phrase in {
                "show me",
                "give me",
                "how much",
                "compare",
                "comparison",
                "this year",
                "last year",
                "previous year",
            }
        )

    def _build_decision(self, route: str, reason: str, metadata: dict | None = None) -> AgentDecision:
        return AgentDecision(
            route=route,
            reason=reason,
            needs_sql=route in {"sql", "sql_rag"},
            needs_rag=route in {"rag", "sql_rag"},
            needs_chart=route in {"chart"},
            metadata=metadata if metadata is not None else {},
        )

    def _llm_intent_decision(self, normalized: str, routing_metadata: dict) -> AgentDecision | None:
        if self._llm_routing_disabled:
            if (monotonic() - self._llm_routing_disabled_at) >= _LLM_ROUTING_RETRY_COOLDOWN_SECS:
                self._llm_routing_disabled = False
                self._llm_routing_disabled_at = 0.0
            else:
                return None
        # Request-time LLM routing is intentionally disabled in production.
        logger.debug("Skipping LLM intent routing for query=%r; rule-based routing only.", normalized)
        return None

    def decide(self, query: str) -> AgentDecision:
        normalized = (query or "").strip().lower()
        if not normalized:
            return AgentDecision("rag", "empty_query", False, True, False)

        if self._is_identity_question(normalized):
            return self._build_decision("out_of_domain", "out_of_domain_query")

        if self._is_ui_context_question(normalized):
            return self._build_decision("out_of_domain", "ui_context_question")

        if self._is_declarative_statement(normalized):
            return self._build_decision("out_of_domain", "declarative_statement")

        if self._is_greeting(normalized):
            return self._build_decision("out_of_domain", "greeting")

        if self._is_product_question(normalized):
            if is_definition_query(normalized) or "about carbon" in normalized or "tell" in normalized:
                return self._build_decision("rag", "definition_query")
            return self._build_decision("rag", "product_question")

        if self._is_dashboard_concept_definition_question(normalized):
            return self._build_decision("rag", "definition_query")

        if self._is_neutrality_location_query(normalized):
            return self._build_decision("rag", "neutrality_location_query")

        month_year_pairs = extract_month_year_pairs(normalized)
        years = extract_years(normalized)
        scope_mentions = _extract_scope_mentions(normalized)

        # Signal Detection
        has_chart_signal = any(k in normalized for k in self.chart_keywords)
        has_explanation_signal = any(k in normalized for k in self.rag_keywords)
        has_metric_signal = any(k in normalized for k in self.metric_keywords) or any(alias in normalized for alias in METRIC_ALIASES)
        has_numeric_signal = any(k in normalized for k in self.sql_keywords) and has_metric_signal
        has_numeric_intent_signal = any(k in normalized for k in NUMERIC_INTENT_KEYWORDS)
        has_summary_signal = "summary" in normalized
        has_ranking_signal = any(k in normalized for k in RANKING_KEYWORDS)
        has_facility_target_signal = any(k in normalized for k in FACILITY_TARGET_KEYWORDS)
        has_scope_filter_signal = bool(scope_mentions)
        has_multi_scope_signal = len(scope_mentions) > 1
        has_period_reference_signal = bool(
            month_year_pairs
            or years
            or "fy" in normalized
            or "reporting period" in normalized
            or "monthly" in normalized
            or any(term in normalized for term in {"now", "today", "currently", "right now"})
        )
        has_value_metric_signal = any(term in normalized for term in {"emission", "emissions", "summary", "total", "value", "values", "amount"})
        has_value_question_signal = any(
            phrase in normalized for phrase in {"what were", "what was", "what are", "what is the", "how much", "give me", "show me"}
        )
        has_compact_filtered_value_signal = (
            has_metric_signal
            and has_value_metric_signal
            and has_scope_filter_signal
            and has_period_reference_signal
        )
        has_definition_signal = is_definition_query(normalized) and not (
            has_value_metric_signal and (has_period_reference_signal or has_value_question_signal)
        ) and not has_multi_scope_signal
        
        has_explanatory_rag_signal = any(
            k in normalized for k in {"explain", "why", "reason", "caused", "because", "drivers", "driver"}
        )

        wants_visual_signal = has_chart_signal or any(
            k in normalized for k in {"trend", "graph", "plot", "visual", "visualize"}
        )
        has_comparison_signal = any(k in normalized for k in {"compare", "comparison", "vs", "versus"})

        has_multi_time_signal = len(month_year_pairs) >= 2 or len(years) >= 2

        # Routing Logic with Explainability Metadata
        routing_metadata = {
            "signals": {
                "numeric": has_numeric_signal or (has_numeric_intent_signal and has_metric_signal),
                "visual": wants_visual_signal,
                "explanatory": has_explanatory_rag_signal
            }
        }

        has_numeric_query_signal = (
            has_numeric_signal
            or (has_numeric_intent_signal and (has_metric_signal or has_multi_time_signal or wants_visual_signal))
            or (has_multi_time_signal and has_metric_signal)
            or (
                has_metric_signal
                and not has_definition_signal
                and has_value_question_signal
                and (has_scope_filter_signal or has_period_reference_signal)
            )
            or (
                has_compact_filtered_value_signal
                and not has_definition_signal
            )
            or (
                has_metric_signal
                and has_ranking_signal
                and (has_facility_target_signal or has_period_reference_signal)
            )
            or (
                has_summary_signal
                and (has_metric_signal or has_period_reference_signal)
            )
            or (
                has_multi_scope_signal
                and (has_value_metric_signal or has_value_question_signal or has_numeric_intent_signal)
            )
            or (
                has_metric_signal
                and "monthly" in normalized
                and (has_facility_target_signal or has_period_reference_signal or "show" in normalized or "give me" in normalized)
            )
        )

        if has_numeric_query_signal:
            if has_explanatory_rag_signal:
                reason = "chart_numeric_explanation_query" if wants_visual_signal else "composite_numeric_explanation_query"
                return AgentDecision("sql_rag", reason, True, True, wants_visual_signal, routing_metadata)

            numeric_needs_chart = wants_visual_signal or has_comparison_signal
            if (has_summary_signal or has_multi_scope_signal) and not has_ranking_signal:
                reason = "summary_query"
            elif has_ranking_signal and has_facility_target_signal:
                reason = "ranking_query"
            else:
                reason = "chart_numeric_query" if numeric_needs_chart else "numeric_query"
            return AgentDecision("sql", reason, True, False, numeric_needs_chart, routing_metadata)

        if has_chart_signal and not (has_explanation_signal or has_numeric_query_signal):
            return AgentDecision("chart", "chart_query", False, False, True, routing_metadata)

        if has_definition_signal:
            return self._build_decision("rag", "definition_query")

        llm_decision = self._llm_intent_decision(normalized, routing_metadata)
        if llm_decision is not None:
            return llm_decision

        if self._looks_like_named_domain_entity(normalized):
            return self._build_decision("rag", "named_entity_query")

        if not self._has_domain_signal(normalized):
            return self._build_decision("out_of_domain", "out_of_domain_query")

        return AgentDecision("rag", "semantic_default", False, True, False, routing_metadata)
