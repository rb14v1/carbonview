import json
import logging
import os
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib import import_module


logger = logging.getLogger(__name__)


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "that",
    "the",
    "this",
    "to",
    "what",
    "which",
    "with",
}

DEFINITION_HINTS = {"what is", "what's", "define", "definition", "meaning"}
SIMPLE_LANGUAGE_HINTS = {"simple", "simple words", "easy words", "easier"}
VALUE_QUERY_HINTS = {"latest", "current", "recent", "value", "values", "total", "emission", "emissions", "compare"}

QUERY_SYNONYMS = {
    "co2": {"co2e", "carbon", "emission", "emissions", "ghg"},
    "co2e": {"co2", "carbon", "emission", "emissions", "ghg"},
    "carbon": {"co2", "co2e", "emission", "emissions", "ghg"},
    "emission": {"emissions", "co2e", "carbon", "ghg"},
    "emissions": {"emission", "co2e", "carbon", "ghg"},
    "facility": {"site", "plant", "location"},
    "facilities": {"site", "plant", "location"},
    "organization": {"company", "business"},
    "project": {"initiative", "reduction"},
    "trend": {"compare", "change", "movement"},
    "highest": {"largest", "top", "max"},
    "lowest": {"smallest", "min"},
    "energy": {"electricity", "power", "renewable"},
    "water": {"consumption", "usage"},
    "waste": {"recycling", "hazardous"},
    "credit": {"offset", "retired", "purchased"},
}

MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

DEFAULT_EMPTY_RAG_FALLBACK = (
    "I could not find relevant CarbonView data for that question. "
    "Try mentioning the facility, period, or metric more explicitly."
)

_RAG_PACKAGE_DIR = os.path.dirname(os.path.dirname(__file__))


def get_active_domain() -> str:
    return os.getenv("RAG_ACTIVE_DOMAIN", "carbon").strip().lower() or "carbon"


def _domain_dir(domain: str | None = None) -> str:
    return os.path.join(_RAG_PACKAGE_DIR, "domain", domain or get_active_domain())


@lru_cache(maxsize=16)
def load_domain_json(filename: str, domain: str | None = None) -> dict[str, object]:
    path = os.path.join(_domain_dir(domain), filename)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_domain_config(domain: str | None = None) -> dict[str, object]:
    return load_domain_json("domain_config.json", domain)


def import_from_path(path: str):
    module_name, _, attribute_name = path.rpartition(".")
    if not module_name or not attribute_name:
        raise ImportError(f"Invalid import path: {path}")
    module = import_module(module_name)
    return getattr(module, attribute_name)


def get_document_builder():
    config = load_domain_config()
    builder_path = str(config.get("document_builder") or "").strip()
    if not builder_path:
        raise ValueError("Domain config must define 'document_builder'")
    builder_class = import_from_path(builder_path)
    return builder_class()


def get_registered_sql_handlers(tool) -> list[object]:
    config = load_domain_config()
    handlers = []
    for path in config.get("sql_handlers", []):
        handler_class = import_from_path(str(path))
        handlers.append(handler_class(tool))
    return handlers


def normalize_token(token: str) -> str:
    token = token.lower()
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    normalized = [normalize_token(token) for token in tokens]
    return [token for token in normalized if token and token not in STOP_WORDS]


def expanded_query_tokens(query: str) -> set[str]:
    tokens = set(tokenize(query))
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(normalize_token(value) for value in QUERY_SYNONYMS.get(token, set()))
    return expanded


def extract_years(query: str) -> set[str]:
    years = set(re.findall(r"\b(20\d{2}|19\d{2})\b", query))
    normalized = (query or "").lower()
    range_pattern = re.compile(
        r"\b(?:from|between)\s+(20\d{2}|19\d{2})\s+(?:to|and|-)\s+(20\d{2}|19\d{2})\b"
    )
    for start_text, end_text in range_pattern.findall(normalized):
        start_year = int(start_text)
        end_year = int(end_text)
        lower = min(start_year, end_year)
        upper = max(start_year, end_year)
        for year in range(lower, upper + 1):
            years.add(str(year))
    for year, _ in extract_month_year_pairs(query):
        years.add(str(year))
    return years


def extract_month_year_pairs(query: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    pattern = re.compile(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?"
        r")\s*['â€™]?\s*(\d{2}|\d{4})\b",
        re.IGNORECASE,
    )
    for month_text, year_text in pattern.findall(query):
        month = MONTH_ALIASES.get(month_text.lower())
        if not month:
            continue
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000 if year < 70 else 1900
        pairs.append((year, month))
    return pairs


def extract_month_numbers(query: str) -> tuple[int, ...]:
    normalized = (query or "").lower()
    month_numbers: list[int] = []
    paired_months = {month for _, month in extract_month_year_pairs(normalized)}

    for month_text, month_number in MONTH_ALIASES.items():
        if month_number in paired_months:
            continue
        if re.search(rf"\b{re.escape(month_text)}\b", normalized):
            month_numbers.append(month_number)

    return tuple(dict.fromkeys(month_numbers))


def expand_temporal_query(query: str) -> str:
    pairs = extract_month_year_pairs(query)
    if not pairs:
        return query
    additions: list[str] = []
    for year, month in pairs:
        month_name = MONTH_NAMES.get(month)
        if not month_name:
            continue
        additions.append(f"{month_name} {year}")
        additions.append(f"year {year}")
        additions.append(f"month {month}")
    return f"{query} {' '.join(additions)}".strip()


def expand_relative_time_query(query: str) -> str:
    normalized = (query or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return normalized

    today = date.today()
    additions: list[str] = []

    if any(term in lowered for term in {"this year", "current year"}):
        additions.extend([str(today.year), f"FY{today.year}"])
    elif any(term in lowered for term in {"last year", "previous year"}):
        additions.extend([str(today.year - 1), f"FY{today.year - 1}"])

    if any(term in lowered for term in {"this month", "current month"}):
        additions.extend([f"{MONTH_NAMES.get(today.month, today.month)} {today.year}", f"month {today.month}", f"year {today.year}"])

    additions = [item for item in dict.fromkeys(additions) if item.lower() not in lowered]
    return f"{normalized} {' '.join(additions)}".strip() if additions else normalized


def extract_scope_filters(query: str) -> set[str]:
    scopes: set[str] = set()
    normalized = query.lower()
    if re.search(r"\b(?:scope|scop|cope)\s*1\b|\bs\s*1\b|\bs1\b", normalized):
        scopes.add("S1")
    if re.search(r"\b(?:scope|scop|cope)\s*2\b|\bs\s*2\b|\bs2\b", normalized):
        scopes.add("S2")
    if re.search(r"\b(?:scope|scop|cope)\s*3\b|\bs\s*3\b|\bs3\b", normalized):
        scopes.add("S3")
    return scopes


def extract_scope_number(query: str) -> int | None:
    normalized = (query or "").lower()
    match = re.search(r"\b(?:scope|scop|cope)\s*(\d)\b|\bs\s*(\d)\b|\bs(\d)\b", normalized)
    if not match:
        return None
    for group in match.groups():
        if group is not None:
            return int(group)
    return None


def is_definition_query(query: str) -> bool:
    normalized = (query or "").strip().lower()
    return any(term in normalized for term in DEFINITION_HINTS)


def is_simple_language_query(query: str) -> bool:
    normalized = (query or "").strip().lower()
    return any(term in normalized for term in SIMPLE_LANGUAGE_HINTS)


def is_value_query(query: str) -> bool:
    normalized = (query or "").strip().lower()
    return any(term in normalized for term in VALUE_QUERY_HINTS)


def decimal_to_float(value: Decimal | None) -> float:
    return float(value or Decimal("0"))


def format_number(value: float) -> str:
    return f"{value:,.2f}"


def dedupe_lines(lines: list[str], limit: int) -> list[str]:
    unique_lines = list(dict.fromkeys(line.strip() for line in lines if line.strip()))
    return unique_lines[:limit]


def make_document(
    *,
    source: str,
    content: str,
    metadata: dict[str, object],
    keywords: set[str] | None = None,
) -> dict[str, object]:
    keyword_values = sorted(keywords or set())
    searchable_parts = [source, content]
    if keyword_values:
        searchable_parts.append(" ".join(keyword_values))
    searchable_text = " ".join(part for part in searchable_parts if part)
    return {
        "source": source,
        "content": content,
        "metadata": metadata,
        "keywords": keyword_values,
        "searchable_text": searchable_text,
        "tokens": Counter(tokenize(searchable_text)),
    }


def build_source_example(row: dict[str, object] | None) -> str | None:
    if not row:
        return None
    if row.get("label") and "total_co2e" in row:
        return f"{row['label']} -> {format_number(float(row['total_co2e']))} tCO2e"
    year = row.get("year")
    month = row.get("month")
    if year is not None and month is not None:
        if "total_co2e" in row:
            return f"{int(year)}-{int(month):02d} -> {format_number(float(row['total_co2e']))} tCO2e"
        if "amount" in row:
            return f"{int(year)}-{int(month):02d} -> {format_number(float(row['amount']))}"
    if row.get("facility") and "total_energy" in row:
        return f"{row['facility']} -> {format_number(float(row['total_energy']))} {row.get('unit') or ''}".strip()
    if row.get("facility") and "total_waste" in row:
        return f"{row['facility']} -> {format_number(float(row['total_waste']))} {row.get('unit') or ''}".strip()
    if row.get("category") and "amount" in row:
        return f"{row['category']} -> {format_number(float(row['amount']))} {row.get('unit') or ''}".strip()
    value_field = next(
        (
            field
            for field in (
                "total_co2e",
                "total_energy",
                "renewable_energy",
                "non_renewable_energy",
                "total_waste",
                "hazardous",
                "non_hazardous",
                "amount",
            )
            if field in row and row.get(field) is not None
        ),
        None,
    )
    context_field = next(
        (
            field
            for field in (
                "category",
                "scope",
                "facility",
                "organization",
                "reporting_period",
                "label",
                "subcategory",
                "scope3_category",
                "gas_type",
            )
            if row.get(field)
        ),
        None,
    )
    if value_field:
        unit = "tCO2e" if "co2e" in value_field else str(row.get("unit") or "").strip()
        context = str(row.get(context_field) or "matched record").strip() if context_field else "matched record"
        value = format_number(float(row[value_field]))
        return f"{context} -> {value}{f' {unit}' if unit else ''}"
    if context_field:
        return f"{row[context_field]} -> matched record"
    return "Matched record -> evidence available"
