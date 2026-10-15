import json
import os
import re
from copy import deepcopy
from hashlib import md5
from time import monotonic
from urllib import error, request
from .core.cache import TTLCache
from .common import dedupe_lines, format_number, is_definition_query, logger, tokenize
from .types import ChatTurn, RetrievedDocument


def _use_llm_answer_refinement() -> bool:
    value = (os.getenv("RAG_ANSWER_REFINEMENT", "false") or "false").strip().lower()
    return value in {"1", "true", "yes", "on"}

def _get_azure_deployment_name() -> str:
    """Production-grade deployment name resolution."""
    for key in ("AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT_NAME", "AZURE_OPENAI_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


_AZURE_OPENAI_CHAT_TIMEOUT_SECS = float(os.getenv("AZURE_OPENAI_CHAT_TIMEOUT_SECS", "30"))
_AZURE_OPENAI_CHAT_MAX_RETRIES = max(int(os.getenv("AZURE_OPENAI_CHAT_MAX_RETRIES", "1")), 1)
_FINAL_ANSWER_CACHE = TTLCache[str, str](
    maxsize=max(int(os.getenv("RAG_FINAL_ANSWER_CACHE_SIZE", "128")), 1),
    ttl_secs=float(os.getenv("RAG_FINAL_ANSWER_CACHE_TTL_SECS", "300")),
)

def _azure_chat_completion(system_prompt: str, user_prompt: str) -> str:
    """Fixed completion call with zero temperature for numeric accuracy."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    deployment = _get_azure_deployment_name()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
 
    missing = [
        name for name, value in [
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
            ("AZURE_OPENAI_CHAT_DEPLOYMENT or AZURE_OPENAI_MODEL", deployment),
        ] if not value
    ]
    if missing:
        raise ValueError(f"Missing Azure OpenAI settings: {', '.join(missing)}")
 
    req = request.Request(
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}",
        data=json.dumps({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0, # Ensures deterministic numeric output
            "seed": 42,
            "max_tokens": 800,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )

    cache_key = md5(f"{system_prompt}\n{user_prompt}".encode("utf-8")).hexdigest()
    cached = _FINAL_ANSWER_CACHE.get(cache_key)
    if cached is not None:
        logger.info("RAG LLM cache hit latency_ms=0.00")
        return cached

    last_error: Exception | None = None
    for _ in range(_AZURE_OPENAI_CHAT_MAX_RETRIES):
        try:
            started_at = monotonic()
            logger.info("RAG LLM call start timeout_secs=%s", _AZURE_OPENAI_CHAT_TIMEOUT_SECS)
            with request.urlopen(req, timeout=_AZURE_OPENAI_CHAT_TIMEOUT_SECS) as response:
                body = json.loads(response.read().decode("utf-8"))
            answer = body["choices"][0]["message"]["content"].strip()
            _FINAL_ANSWER_CACHE.set(cache_key, answer)
            logger.info("RAG LLM call end latency_ms=%.2f", (monotonic() - started_at) * 1000)
            return answer
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_error = RuntimeError(f"Azure OpenAI request failed: {exc.code} {detail}")
            if 400 <= exc.code < 500 and exc.code not in {408, 429}:
                break
        except (error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = RuntimeError(f"Azure OpenAI request failed: {exc}")
    raise last_error or RuntimeError("Azure OpenAI request failed")


def _is_definition_style_query(query: str) -> bool:
    normalized = (query or "").strip().lower()
    return is_definition_query(normalized) or any(
        phrase in normalized
        for phrase in {"tell me about", "explain", "meaning of", "about "}
    )


def _is_reduction_project_query(query: str) -> bool:
    if _is_definition_style_query(query):
        return False
    query_tokens = set(tokenize(query))
    project_terms = {"project", "initiative", "opportunity", "opportunitie"}
    intent_terms = {"reduction", "available", "availability", "list", "show", "tell"}
    if {"credit", "offset"}.intersection(query_tokens):
        return False
    return bool(project_terms.intersection(query_tokens)) and bool(intent_terms.intersection(query_tokens))


def _is_carbon_credit_query(query: str) -> bool:
    if _is_definition_style_query(query):
        return False
    query_tokens = set(tokenize(query))
    credit_terms = {"credit", "offset"}
    intent_terms = {"available", "availability", "list", "show", "tell", "project"}
    return bool(credit_terms.intersection(query_tokens)) and bool(intent_terms.intersection(query_tokens))


def _extract_project_metric(label: str, content: str) -> str | None:
    match = re.search(rf"{label}: ([0-9,]+(?:\.[0-9]+)?) tCO2e", content, re.IGNORECASE)
    return match.group(1) if match else None


def _query_mentions_named_value(query: str, value: str) -> bool:
    normalized_query = (query or "").strip().lower()
    normalized_value = (value or "").strip().lower()
    return bool(normalized_query and normalized_value and normalized_value in normalized_query)


def _extract_segment(content: str, label: str, next_label: str) -> str | None:
    if next_label:
        pattern = rf"{label}: (.*?)(?:\. {next_label}:|$)"
    else:
        pattern = rf"{label}: (.*?)(?:$)"
    match = re.search(pattern, content, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value else None


def _format_named_reduction_project_answer(doc: RetrievedDocument) -> tuple[str, list[RetrievedDocument]]:
    project_name = str(doc.metadata.get("project") or doc.source.replace("Reduction Project: ", "")).strip()
    facility_name = str(doc.metadata.get("facility") or "the selected facility").strip()
    organization = str(doc.metadata.get("organization") or "the selected organization").strip()
    expected_value = _extract_project_metric("Expected reduction", doc.content)
    actual_value = _extract_project_metric("Actual reduction", doc.content)
    description = _extract_segment(doc.content, "Description", "Expected reduction")
    start_date = _extract_segment(doc.content, "Start date", "End date")
    end_date = _extract_segment(doc.content, "End date", "")

    lines = [f"{project_name} is a reduction project for {facility_name} in {organization}."]
    if description and description.lower() != "not provided":
        lines.append(f"Description: {description}.")
    expected_amount = float(expected_value.replace(",", "")) if expected_value is not None else None
    actual_amount = float(actual_value.replace(",", "")) if actual_value is not None else None
    if expected_value is not None:
        lines.append(
            f"Expected reduction: {format_number(expected_amount or 0.0)} tCO2e."
        )
    if actual_value is not None:
        lines.append(
            f"Actual reduction: {format_number(actual_amount or 0.0)} tCO2e."
        )
    if expected_amount and actual_amount is not None:
        achievement = (actual_amount / expected_amount) * 100.0
        lines.append(f"Achievement so far: {achievement:.0f}% of the expected reduction target.")
    if start_date and start_date.lower() != "not set":
        lines.append(f"Start date: {start_date}.")
    if end_date and end_date.lower() != "not set":
        lines.append(f"End date: {end_date}.")
    return " ".join(lines), [doc]


def _format_named_facility_answer(doc: RetrievedDocument) -> tuple[str, list[RetrievedDocument]]:
    metadata = doc.metadata
    facility_name = str(metadata.get("facility") or "Unnamed facility").strip()
    organization = str(metadata.get("organization") or "the selected organization").strip()
    city = str(metadata.get("city") or "").strip()
    state = str(metadata.get("state") or "").strip()
    country = str(metadata.get("country") or "").strip()
    location_parts = [part for part in [city, state, country] if part]
    location = ", ".join(location_parts) if location_parts else str(metadata.get("location") or "location not set").strip()
    carbon_neutral = "yes" if metadata.get("is_carbon_neutral") else "no"
    active = "yes" if metadata.get("is_active") else "no"
    facility_code = _extract_segment(doc.content, "Facility code", "Description")
    description = _extract_segment(doc.content, "Description", "Active")

    lines = [f"{facility_name} is a CarbonView facility in {organization}."]
    lines.append(f"Location: {location}.")
    if facility_code and facility_code.lower() != "not set":
        lines.append(f"Facility code: {facility_code}.")
    if description and description.lower() != "not provided":
        lines.append(f"Description: {description}.")
    lines.append(f"Active: {active}. Carbon neutral: {carbon_neutral}.")
    return " ".join(lines), [doc]


def _format_named_carbon_credit_answer(doc: RetrievedDocument) -> tuple[str, list[RetrievedDocument]]:
    project_name = str(doc.metadata.get("project") or doc.source.replace("Carbon Credit: ", "")).strip()
    facility_name = str(doc.metadata.get("facility") or "the selected facility").strip()
    quantity = _extract_project_metric("Quantity retired or purchased", doc.content)
    status = str(doc.metadata.get("status") or "").strip()
    vintage_year = str(doc.metadata.get("year") or "").strip()

    lines = [f"{project_name} is a carbon credit record for {facility_name}."]
    if quantity is not None:
        lines.append(f"Quantity: {format_number(float(quantity.replace(',', '')))} tCO2e.")
    if status:
        lines.append(f"Status: {status}.")
    if vintage_year:
        lines.append(f"Vintage year: {vintage_year}.")
    return " ".join(lines), [doc]


def _format_named_entity_answer(query: str, documents: list[RetrievedDocument]) -> tuple[str, list[RetrievedDocument]] | None:
    if not documents:
        return None
    first_doc = documents[0]
    entity = str(first_doc.metadata.get("entity") or "")
    if entity == "reduction_project":
        project_name = str(first_doc.metadata.get("project") or "").strip()
        if _query_mentions_named_value(query, project_name):
            return _format_named_reduction_project_answer(first_doc)
    if entity == "facility_overview":
        facility_name = str(first_doc.metadata.get("facility") or "").strip()
        if _query_mentions_named_value(query, facility_name):
            return _format_named_facility_answer(first_doc)
    if entity == "carbon_credit":
        project_name = str(first_doc.metadata.get("project") or "").strip()
        if _query_mentions_named_value(query, project_name):
            return _format_named_carbon_credit_answer(first_doc)
    return None


def _format_reduction_project_answer(documents: list[RetrievedDocument]) -> tuple[str, list[RetrievedDocument]]:
    project_docs = [
        doc for doc in documents
        if str(doc.metadata.get("entity") or "") == "reduction_project"
    ]
    if not project_docs:
        return "I could not find any reduction projects matching that question.", []

    facility_names = sorted(
        {
            str(doc.metadata.get("facility") or "").strip()
            for doc in project_docs
            if str(doc.metadata.get("facility") or "").strip()
        }
    )
    header = (
        f"Reduction projects available for {facility_names[0]}:"
        if len(facility_names) == 1
        else "Reduction projects available in CarbonView:"
    )

    lines = [header]
    for doc in project_docs:
        project_name = str(doc.metadata.get("project") or doc.source.replace("Reduction Project: ", "")).strip()
        expected_value = _extract_project_metric("Expected reduction", doc.content)
        actual_value = _extract_project_metric("Actual reduction", doc.content)
        details: list[str] = []
        if expected_value is not None:
            details.append(f"expected reduction {format_number(float(expected_value.replace(',', '')))} tCO2e")
        if actual_value is not None:
            details.append(f"actual reduction {format_number(float(actual_value.replace(',', '')))} tCO2e")
        if details:
            lines.append(f"- {project_name}: {'; '.join(details)}.")
        else:
            lines.append(f"- {project_name}")
    return "\n".join(lines), project_docs


def _format_carbon_credit_answer(documents: list[RetrievedDocument]) -> tuple[str, list[RetrievedDocument]]:
    credit_docs = [
        doc for doc in documents
        if str(doc.metadata.get("entity") or "") == "carbon_credit"
    ]
    if not credit_docs:
        return "I could not find any carbon credits matching that question.", []

    facility_names = sorted(
        {
            str(doc.metadata.get("facility") or "").strip()
            for doc in credit_docs
            if str(doc.metadata.get("facility") or "").strip()
        }
    )
    header = (
        f"Carbon credits available for {facility_names[0]}:"
        if len(facility_names) == 1
        else "Carbon credits available in CarbonView:"
    )
    lines = [header]
    for doc in credit_docs:
        project_name = str(doc.metadata.get("project") or doc.source.replace("Carbon Credit: ", "")).strip()
        quantity = _extract_project_metric("Quantity retired or purchased", doc.content)
        status = str(doc.metadata.get("status") or "").strip()
        details: list[str] = []
        if quantity is not None:
            details.append(f"quantity {format_number(float(quantity.replace(',', '')))} tCO2e")
        if status:
            details.append(f"status {status}")
        if details:
            lines.append(f"- {project_name}: {'; '.join(details)}.")
        else:
            lines.append(f"- {project_name}")
    return "\n".join(lines), credit_docs


def _is_facility_location_query(query: str) -> bool:
    normalized = (query or "").strip().lower()
    return any(
        phrase in normalized
        for phrase in {
            "location",
            "locations",
            "located",
            "where are the facilities",
            "where are facilities",
            "facility footprint map",
            "carbon neutral",
            "carbon-neutral",
            "country",
            "countries",
            "city",
            "cities",
            "state",
            "states",
        }
    )


def _format_facility_location_answer(query: str, documents: list[RetrievedDocument]) -> tuple[str, list[RetrievedDocument]] | None:
    if not _is_facility_location_query(query):
        return None

    overview_docs = [
        doc for doc in documents
        if str(doc.metadata.get("entity") or "") == "facility_overview"
    ]
    if not overview_docs:
        return None

    deduped_docs: list[RetrievedDocument] = []
    seen_facilities: set[str] = set()
    for doc in overview_docs:
        facility_name = str(doc.metadata.get("facility") or "").strip()
        if not facility_name or facility_name in seen_facilities:
            continue
        seen_facilities.add(facility_name)
        deduped_docs.append(doc)

    if not deduped_docs:
        return None

    normalized = (query or "").lower()
    wants_neutral_focus = "carbon neutral" in normalized or "carbon-neutral" in normalized
    display_docs = deduped_docs
    if wants_neutral_focus:
        neutral_docs = [doc for doc in deduped_docs if doc.metadata.get("is_carbon_neutral")]
        lines = (
            ["Carbon-neutral facilities in CarbonView:"]
            if neutral_docs
            else ["No facilities are currently marked carbon neutral in CarbonView. Current facility statuses:"]
        )
        if neutral_docs:
            display_docs = neutral_docs
    else:
        lines = ["Facility locations in CarbonView:"]

    for doc in display_docs:
        metadata = doc.metadata
        facility_name = str(metadata.get("facility") or "Unnamed facility").strip()
        city = str(metadata.get("city") or "").strip()
        state = str(metadata.get("state") or "").strip()
        country = str(metadata.get("country") or "").strip()
        location_parts = [part for part in [city, state, country] if part]
        location = ", ".join(location_parts) if location_parts else str(metadata.get("location") or "location not set").strip()
        carbon_neutral = "yes" if metadata.get("is_carbon_neutral") else "no"
        active = "yes" if metadata.get("is_active") else "no"
        lines.append(
            f"- {facility_name} - {location}. Carbon neutral: {carbon_neutral}. Active: {active}."
        )

    return "\n".join(lines), deduped_docs


def _resolve_documents_from_tool_result(tool_result: dict) -> list[RetrievedDocument]:
    """Extract the active document list from either rag or sql_rag tool results."""
    raw_documents = list(tool_result.get("documents", []))
    if not raw_documents and str(tool_result.get("route") or "") == "sql_rag":
        raw_documents = list(((tool_result.get("rag_result") or {}).get("documents")) or [])

    documents: list[RetrievedDocument] = []
    for doc in raw_documents:
        try:
            documents.append(
                RetrievedDocument(
                    source=str(doc["source"]),
                    content=str(doc["content"]),
                    metadata=dict(doc["metadata"]),
                    score=float(doc.get("score", 0.0) or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return documents


def _sql_rag_context_suffix(query: str, tool_result: dict, documents: list[RetrievedDocument]) -> str:
    """Add compact contextual evidence for composite numeric-and-explanation answers."""
    normalized = (query or "").lower()
    if str(tool_result.get("route") or "") != "sql_rag":
        return ""
    if not any(term in normalized for term in {"why", "explain", "reason", "driver", "drivers", "because"}):
        return ""
    if not documents:
        return ""

    preferred_entities = {"emission_breakdown"}
    filtered_documents = [
        doc for doc in documents
        if str(doc.metadata.get("entity") or "") in preferred_entities
    ]
    if not filtered_documents:
        return ""

    context_lines: list[str] = []
    for doc in filtered_documents[:2]:
        snippet = " ".join(str(doc.content or "").split())
        if len(snippet) > 180:
            snippet = f"{snippet[:177].rstrip()}..."
        context_lines.append(f"- {snippet}")
    unique_lines = dedupe_lines(context_lines, limit=2)
    if not unique_lines:
        return ""
    return "Possible context from related CarbonView records:\n" + "\n".join(unique_lines)

# =========================
# ✅ FIXED LOCAL ANSWER
# =========================
 
def generate_local_answer(query: str, documents: list[RetrievedDocument], history: list[ChatTurn] | None = None):
    """Refined local aggregation with status validation and deduplication."""
    if not documents:
        normalized = (query or "").lower()
        if "scope 1" in normalized or "scope1" in normalized:
            return (
                "Scope 1 means direct emissions from sources the organization owns or controls, such as on-site fuel combustion and company vehicles.",
                [],
            )
        if "scope 2" in normalized or "scope2" in normalized:
            return (
                "Scope 2 means indirect emissions from purchased electricity, steam, heating, or cooling consumed by the organization.",
                [],
            )
        if "scope 3" in normalized or "scope3" in normalized:
            return (
                "Scope 3 means all other indirect emissions across the value chain, including suppliers, transport, waste, business travel, and product use.",
                [],
            )
        return "I could not find relevant CarbonView data for that question.", []

    first_doc = documents[0]
    if str(first_doc.metadata.get("entity") or "") in {"glossary", "dashboard_home_value"}:
        return first_doc.content, [first_doc]

    facility_location_answer = _format_facility_location_answer(query, documents)
    if facility_location_answer is not None:
        return facility_location_answer

    named_entity_answer = _format_named_entity_answer(query, documents)
    if named_entity_answer is not None:
        return named_entity_answer

    if _is_carbon_credit_query(query):
        return _format_carbon_credit_answer(documents)

    if _is_reduction_project_query(query):
        return _format_reduction_project_answer(documents)

    facility_map = {}
    used_docs = []
 
    for doc in documents:
        if doc.metadata.get("status") == "rejected":
            continue
 
        facility = doc.metadata.get("facility")
        if not facility:
            continue
 
        facility_lower = facility.lower()
        if any(x in facility_lower for x in ["all facilities", "total", "overall"]):
            continue
 
        match = re.search(r"([0-9,]+(?:\.[0-9]+)?)\s*tCO2e", doc.content)
        if not match:
            continue
 
        value = float(match.group(1).replace(",", ""))
 
        if facility not in facility_map:
            facility_map[facility] = value
            used_docs.append(doc)
 
    if len(facility_map) > 1:
        lines = []
        total = 0.0
        for facility, value in facility_map.items():
            lines.append(f"{facility}: {format_number(value)} tCO2e")
            total += value
        lines.append(f"Total: {format_number(total)} tCO2e")
        return "\n".join(lines), used_docs

    entity = str(first_doc.metadata.get("entity") or "")
    match = re.search(r"([0-9,]+(?:\.[0-9]+)?)\s*tCO2e", first_doc.content)
    if match and entity in {"monthly_summary", "emission_activity", "emission_breakdown"}:
        value = format_number(float(match.group(1).replace(",", "")))
        facility = str(first_doc.metadata.get("facility") or "the selected facility")
        reporting_period = str(first_doc.metadata.get("reporting_period") or "").strip()
        scope = str(first_doc.metadata.get("scope") or "").strip()
        subject = f"{scope.replace('S', 'Scope ')} emissions" if scope else "Emissions"
        period_text = f" in {reporting_period}" if reporting_period else ""
        return f"{subject} for {facility}{period_text} were {value} tCO2e.", [first_doc]

    return documents[0].content, [documents[0]]
 
 
def _structured_chart_answer(tool_result: dict) -> str | None:
    chart = tool_result.get("chart") if isinstance(tool_result.get("chart"), dict) else tool_result.get("data")
    if not isinstance(chart, dict):
        return None
 
    labels = chart.get("labels") or []
    series = chart.get("series") or []
    unit = chart.get("unit") or ""
    title = chart.get("title") or "Chart"
 
    if not labels or not series:
        fallback = str(tool_result.get("fallback_answer") or "").strip()
        return fallback or None
 
    lines = [f"{title}:"]
    for item in series:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "Series"
        values = item.get("data") or []
        lines.append(f"- {name}:")
        for label, value in zip(labels, values):
            lines.append(f"  - {label}: {format_number(float(value))}{f' {unit}' if unit else ''}")
 
    return "\n".join(lines)
 
 
def _structured_tool_answer(tool_result: dict) -> str | None:
    if tool_result.get("route") == "chart":
        return _structured_chart_answer(tool_result)
 
    fallback = str(tool_result.get("fallback_answer") or "").strip()
    return fallback or None
 
# =========================
# ✅ FINAL ANSWER GENERATION
# =========================
 
def generate_answer(query: str, tool_result: dict, history: list[ChatTurn] | None = None):
    """Orchestrates structured answer generation with a structural tag for the UI button."""
    result_payload = deepcopy(tool_result)
    if result_payload.get("tool") == "guardrail":
        result_payload["explanation"] = None
        return str(result_payload.get("fallback_answer") or "").strip(), "guardrail-local", result_payload
    documents = _resolve_documents_from_tool_result(result_payload)

    if str(result_payload.get("route") or "") == "sql_rag":
        draft_answer = str(result_payload.get("fallback_answer") or "I could not find relevant CarbonView data for that question.")
        used_docs = documents
    elif documents:
        draft_answer, used_docs = generate_local_answer(query, documents, history=history)
    else:
        draft_answer = str(result_payload.get("fallback_answer") or "I could not find relevant CarbonView data for that question.")
        used_docs = []

    context_suffix = _sql_rag_context_suffix(query, result_payload, used_docs or documents)
    if context_suffix:
        draft_answer = f"{draft_answer}\n\n{context_suffix}"

    # Identitiy and Formatting rules
    system_prompt = (
        "You are the CarbonView AI Sustainability Assistant. "
        "Your goal is to provide accurate, audit-ready carbon insights. "
        "Present the data clearly in bullet or line format. Do NOT use tables. "
        "Maintain all numbers exactly as provided in the PRE-COMPUTED answer."
    )
 
    # Technical metadata extraction for the explanation button
    sql_source = result_payload.get("source", {}).get("table")
    rag_entities = list(set(doc.metadata.get("entity") for doc in used_docs if doc.metadata.get("entity")))
    primary_tables = sql_source if sql_source else ", ".join(rag_entities) if rag_entities else "emission_breakdown"
    sql_meta = result_payload.get("metadata", {}).get("filters", {})

    # Construct a clear, unambiguous user prompt for the chat model.
    # The model should produce a human-readable answer and append a single structural tag
    # on its own line: [BUTTON:SHOW_EXPLANATION]
    # The backend stores structured explanation metadata separately (tool_result['explanation']).
    user_prompt = (
        f"Question: {query}\n\n"
        f"Answer Content (PRE-COMPUTED):\n{draft_answer}\n\n"
        f"Metadata: primary_tables={primary_tables}; filters={sql_meta}\n\n"
        "Instructions:\n"
        "- You are the CarbonView Assistant: provide concise, accurate, audit-ready answers.\n"
        "- Present lists as bullet points or numbered lines; do NOT use Markdown tables.\n"
        "- Preserve numeric values exactly as shown in the PRE-COMPUTED answer.\n"
        "- Keep the answer focused and avoid adding speculative text.\n"
        "- When finished, on a new line append ONLY the token: [BUTTON:SHOW_EXPLANATION]\n"
        "  (the frontend will use structured metadata sent separately to render the explanation panel)."
    )

    if _use_llm_answer_refinement():
        try:
            answer = _azure_chat_completion(system_prompt, user_prompt)
            provider = "azure-openai-refined"
        except Exception:
            logger.exception("Falling back to draft answer")
            answer = f"{draft_answer}\n\n[BUTTON:SHOW_EXPLANATION]"
            provider = "local"
    else:
        answer = f"{draft_answer}\n\n[BUTTON:SHOW_EXPLANATION]"
        provider = "local-fast"

    # Store for session tracking
    result_payload["explanation"] = {
        "route": result_payload.get("route"),
        "tool": result_payload.get("tool"),
        "summary": result_payload.get("fallback_answer") or draft_answer,
        "sql_source": result_payload.get("source"),
        "documents_used": [{"source": d.source, "metadata": d.metadata} for d in used_docs],
        "applied_filters": sql_meta
    }

    return answer, provider, result_payload
