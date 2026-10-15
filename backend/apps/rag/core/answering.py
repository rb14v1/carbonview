from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from urllib import error, request

from .common import DEFAULT_EMPTY_RAG_FALLBACK, is_definition_query, is_simple_language_query, is_value_query
from .types import ChatTurn, RetrievedDocument


class Formatter(ABC):
    @abstractmethod
    def format(
        self,
        query: str,
        tool_result: dict[str, object],
        history: list[ChatTurn] | None = None,
    ) -> tuple[str, str]:
        raise NotImplementedError


def _get_azure_deployment_name() -> str:
    for key in ("AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT_NAME", "AZURE_OPENAI_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _azure_chat_completion(system_prompt: str, user_prompt: str) -> str:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    deployment = _get_azure_deployment_name()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
    missing = [
        name
        for name, value in [
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
            ("AZURE_OPENAI_CHAT_DEPLOYMENT or AZURE_OPENAI_MODEL", deployment),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing Azure OpenAI settings: {', '.join(missing)}")
    req = request.Request(
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}",
        data=json.dumps(
            {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 450,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"Azure OpenAI request failed: {exc.code} {exc.read().decode('utf-8', errors='ignore')}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Azure OpenAI connection failed: {exc.reason}") from exc
    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Azure OpenAI returned an unexpected response shape") from exc


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _looks_contextual(query: str) -> bool:
    normalized = query.lower().strip()
    if not normalized:
        return False
    return bool(
        re.search(r"\b(it|that|those|these|they|them|there|here|above|previous|same|its|their)\b", normalized)
        or re.match(r"^(and|what about|how about|why|which one|which|compare|break that down|tell me more|more detail|more details|yes|go on|continue|i want\b|for\b|in\b)", normalized)
        or bool(re.fullmatch(r"(?:i want\s+)?(?:for\s+)?(?:fy)?20\d{2}", normalized))
    )


def _strip_relative_time_context(text: str) -> str:
    stripped = re.sub(
        r"\b(this year|current year|last year|previous year|this month|current month|right now|now|currently|latest|recent)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", stripped).strip(" ,")


def rewrite_query_with_history(query: str, history: list[ChatTurn] | None = None) -> str:
    normalized_query = _normalize_question(query)
    if not history or not _looks_contextual(normalized_query):
        return normalized_query

    prior_user_messages = [turn.content.strip() for turn in history if turn.role == "user" and turn.content.strip()]
    if not prior_user_messages:
        return normalized_query

    latest_user_context = prior_user_messages[-1]
    if latest_user_context.lower() == normalized_query.lower():
        return normalized_query

    if is_simple_language_query(normalized_query):
        return latest_user_context

    if re.fullmatch(r"(?:i want\s+)?(?:for\s+)?(?:fy)?20\d{2}", normalized_query.lower()):
        requested_period = re.sub(r"^i want\s+", "", normalized_query, flags=re.IGNORECASE).strip()
        if re.fullmatch(r"(?:fy)?20\d{2}", requested_period.lower()):
            requested_period = f"for {requested_period}"
        base_context = _strip_relative_time_context(latest_user_context)
        return f"{base_context} {requested_period}".strip()

    if re.match(r"^(what about|how about)\b", normalized_query.lower()):
        tail = re.sub(r"^(what about|how about)\s*", "", normalized_query, flags=re.IGNORECASE).strip()
        return f"{latest_user_context} {tail}".strip()

    if re.match(r"^(i want|for|in)\b", normalized_query.lower()):
        tail = re.sub(r"^i want\s*", "", normalized_query, flags=re.IGNORECASE).strip()
        base_context = _strip_relative_time_context(latest_user_context)
        return f"{base_context} {tail}".strip()

    if re.match(r"^(yes|go on|continue|tell me more|more detail|more details)\b", normalized_query.lower()):
        return f"{latest_user_context} give more detail".strip()

    return f"Context: previous user question was '{latest_user_context}'. Follow-up question: {normalized_query}"


class SingleCallFormatter(Formatter):
    """Build context from one tool result and make at most one LLM call."""

    def format(
        self,
        query: str,
        tool_result: dict[str, object],
        history: list[ChatTurn] | None = None,
    ) -> tuple[str, str]:
        if tool_result.get("tool") == "guardrail":
            fallback = str(tool_result.get("fallback_answer") or "")
            return fallback, "guardrail-local"
        context = self._build_context(tool_result)
        system_prompt = (
            "You are CarbonView's sustainability assistant. "
            "Answer the user's question directly using the provided structured tool output. "
            "Do not invent values. If no matching data was found, say so plainly and suggest a narrower query. "
            "Keep the answer concise and practical. "
            "If structured source evidence is provided, include a short non-sensitive evidence note without exposing chain-of-thought. "
            "Always clearly state which organization, facility, and reporting period the data covers. "
            "If the answer is scoped to a single facility, say so explicitly. "
            "Never present partial data as if it were the total without qualification."
        )
        history_lines = []
        for turn in (history or [])[-6:]:
            role = "User" if turn.role == "user" else "Assistant"
            history_lines.append(f"{role}: {turn.content}")
        user_prompt = (
            f"Current question: {query}\n\n"
            f"Chat history:\n{chr(10).join(history_lines) or 'No previous history.'}\n\n"
            f"Tool route: {tool_result.get('route')}\n"
            f"Tool output:\n{context}\n\n"
            "Write a short answer. If there are important numbers, include them. "
            "If the tool output contains chart metadata, describe what the chart shows."
        )
        try:
            answer = _azure_chat_completion(system_prompt, user_prompt)
            return self._append_explanation(answer, tool_result), "azure-openai-single-call"
        except Exception:
            fallback_answer = str(tool_result.get("fallback_answer") or "I could not generate an answer right now.")
            return self._append_explanation(fallback_answer, tool_result), f"{tool_result.get('tool', 'local')}-local-fallback"

    def _build_context(self, tool_result: dict[str, object]) -> str:
        tool_name = str(tool_result.get("tool") or "unknown")
        if tool_name == "rag":
            documents = tool_result.get("documents") or tool_result.get("data") or []
            if not documents:
                return "No retrieved documents."
            return "\n\n".join(
                f"Source: {doc['source']}\nSnippet: {doc.get('snippet') or doc['content']}\nScore: {doc.get('score')}"
                for doc in documents[:6]
            )
        if tool_name == "sql_rag":
            sql_result = tool_result.get("sql_result") or {}
            rag_result = tool_result.get("rag_result") or {}
            chart_result = tool_result.get("chart") or {}
            sql_context = json.dumps(sql_result, indent=2, default=str)
            rag_documents = rag_result.get("documents") or []
            rag_context = "\n\n".join(
                f"Source: {doc['source']}\nSnippet: {doc.get('snippet') or doc['content']}\nScore: {doc.get('score')}"
                for doc in rag_documents[:6]
            ) or "No retrieved documents."
            chart_context = json.dumps(chart_result, indent=2, default=str) if chart_result else "No chart."
            return f"SQL Result:\n{sql_context}\n\nRAG Context:\n{rag_context}\n\nChart:\n{chart_context}"
        return json.dumps(tool_result, indent=2, default=str)

    def _append_explanation(self, answer: str, tool_result: dict[str, object]) -> str:
        if not answer:
            return answer
        explanation = _source_explanation(tool_result)
        if not explanation:
            return answer
        if explanation in answer:
            return answer
        return f"{answer}\n\n{explanation}"


class CarbonFormatter(SingleCallFormatter):
    """Compatibility wrapper for older callers that still pass retrieved documents."""

    def format(
        self,
        query: str,
        tool_result: dict[str, object] | list[RetrievedDocument],
        history: list[ChatTurn] | None = None,
    ) -> tuple[str, str]:
        if isinstance(tool_result, list):
            documents = [
                {
                    "source": doc.source,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "score": doc.score,
                }
                for doc in tool_result
            ]
            tool_result = {
                "tool": "rag",
                "route": "rag",
                "data": documents,
                "metadata": {"document_count": len(documents)},
                "documents": documents,
                "fallback_answer": tool_result[0].content if tool_result else DEFAULT_EMPTY_RAG_FALLBACK,
            }
        return super().format(query, tool_result, history=history)

    def format_local(
        self,
        query: str,
        documents: list[RetrievedDocument],
        history: list[ChatTurn] | None = None,
    ) -> str:
        if not documents:
            try:
                from .retrieval import search

                documents = search(query, limit=3)
            except Exception:
                documents = []
        normalized_query = (query or "").lower()
        wants_definition = is_definition_query(normalized_query) or is_simple_language_query(normalized_query) or "explain" in normalized_query
        wants_numeric_value = is_value_query(normalized_query)
        glossary_doc = next((doc for doc in documents if doc.metadata.get("entity") == "glossary"), None)
        monthly_doc = next((doc for doc in documents if doc.metadata.get("entity") == "monthly_summary"), None)
        if wants_numeric_value and monthly_doc is not None:
            documents = [monthly_doc]
        if wants_definition and glossary_doc is not None:
            documents = [glossary_doc]
        tool_result = {
            "tool": "rag",
            "route": "rag",
            "data": [
                {
                    "source": doc.source,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "score": doc.score,
                }
                for doc in documents
            ],
            "metadata": {"document_count": len(documents)},
            "documents": [
                {
                    "source": doc.source,
                    "content": doc.content,
                    "metadata": doc.metadata,
                    "score": doc.score,
                }
                for doc in documents
            ],
            "fallback_answer": documents[0].content if documents else DEFAULT_EMPTY_RAG_FALLBACK,
        }
        return str(tool_result["fallback_answer"])


_DEFAULT_FORMATTER = CarbonFormatter()


def generate_local_answer(query: str, documents: list[RetrievedDocument], history: list[ChatTurn] | None = None) -> str:
    return _DEFAULT_FORMATTER.format_local(query, documents, history=history)


def generate_answer(query: str, tool_result: dict[str, object], history: list[ChatTurn] | None = None) -> tuple[str, str]:
    return _DEFAULT_FORMATTER.format(query, tool_result, history=history)


def _source_explanation(tool_result: dict[str, object]) -> str:
    route = str(tool_result.get("route") or "")
    if route not in {"sql", "sql_rag", "chart"}:
        return ""

    if route == "sql_rag":
        sql_result = dict(tool_result.get("sql_result") or {})
        source = dict(sql_result.get("source") or {})
    else:
        source = dict(tool_result.get("source") or {})

    table = source.get("table")
    line = source.get("line")
    if table:
        return f"This result is based on data from the {table} table filtered by the selected scope and time range."
    if line:
        return f"This result is based on {line.lower()}."
    return ""
