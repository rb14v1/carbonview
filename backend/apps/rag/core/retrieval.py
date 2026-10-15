# Prefer the stdlib sqlite3, and only swap in pysqlite3-binary on hosts that
# ship an older SQLite than Chroma requires.
import sqlite3
import sys

if sqlite3.sqlite_version_info < (3, 35, 0):
    try:
        __import__("pysqlite3")
    except ImportError:
        pass
    else:
        sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

import json
import os
import threading
import time
from collections import defaultdict
from functools import lru_cache
from hashlib import md5
from urllib import error, request

import chromadb
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from .cache import TTLCache
from .common import (
    expanded_query_tokens,
    extract_scope_filters,
    extract_years,
    get_document_builder,
    is_definition_query,
    logger,
    tokenize,
)
from .types import RetrievedDocument, SearchScope


_DEFAULT_CHROMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "rag_db",
)


def _resolve_chroma_path() -> str:
    configured = os.getenv("RAG_CHROMA_PATH", "").strip()
    if not configured:
        return _DEFAULT_CHROMA_PATH
    if os.name == "nt" and configured.startswith("/home/site/"):
        logger.warning("Using local fallback Chroma path because Azure App Service path is not valid on Windows: %s", configured)
        return _DEFAULT_CHROMA_PATH
    return configured


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_app_service_mode() -> bool:
    return bool(os.getenv("WEBSITE_SITE_NAME") or os.getenv("WEBSITE_INSTANCE_ID"))


def _is_running_tests() -> bool:
    return any(arg.startswith("test") for arg in sys.argv[1:])


def _lazy_warmup_default() -> bool:
    # Keep first-request retrieval available in tests as well so semantic and
    # glossary flows behave like the real application instead of returning empty
    # results purely because startup warmup has not run yet.
    return True


_CHROMA_PATH = _resolve_chroma_path()
_CHROMA_COLLECTION_NAME = os.getenv("RAG_CHROMA_COLLECTION", "carbonview_rag")
_VECTOR_DIMENSIONS = 768
_SENTENCE_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
_EMBEDDING_PROVIDER = (os.getenv("RAG_EMBEDDING_PROVIDER", "local") or "local").strip().lower()
_VECTORIZER = HashingVectorizer(
    n_features=_VECTOR_DIMENSIONS,
    alternate_sign=False,
    norm="l2",
    ngram_range=(1, 2),
)
_SENTENCE_MODEL = None
_SENTENCE_MODEL_READY = False

_DEFAULT_AUTO_INDEX_ON_REQUEST = False
_DEFAULT_REFRESH_ON_EMPTY_SEARCH = False
_ALLOW_REQUEST_TIME_WARMUP = _env_flag("RAG_ALLOW_REQUEST_TIME_WARMUP", _lazy_warmup_default())
_ALLOW_REQUEST_TIME_REFRESH = _env_flag("RAG_ALLOW_REQUEST_TIME_REFRESH", _lazy_warmup_default())
_DOCUMENT_CACHE_TTL_SECS = float(os.getenv("RAG_DOCUMENT_CACHE_TTL_SECS", "900"))
_AUTO_INDEX_ON_REQUEST = _env_flag("RAG_AUTO_INDEX_ON_REQUEST", _DEFAULT_AUTO_INDEX_ON_REQUEST)
_REFRESH_ON_EMPTY_SEARCH = _env_flag("RAG_REFRESH_ON_EMPTY_SEARCH", _DEFAULT_REFRESH_ON_EMPTY_SEARCH)
_MAX_RETRIEVED_DOCS = max(int(os.getenv("RAG_MAX_RETRIEVED_DOCS", "8")), 1)
_MIN_RETRIEVAL_SCORE = float(os.getenv("RAG_MIN_RETRIEVAL_SCORE", "0.5"))
_RELATIVE_RETRIEVAL_SCORE_FLOOR = float(os.getenv("RAG_RELATIVE_RETRIEVAL_SCORE_FLOOR", "0.35"))
_SEARCH_CACHE_TTL_SECS = float(os.getenv("RAG_SEARCH_CACHE_TTL_SECS", "300"))
_SEARCH_CACHE_SIZE = max(int(os.getenv("RAG_SEARCH_CACHE_SIZE", "256")), 1)
_AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
_AZURE_OPENAI_TIMEOUT_SECS = float(os.getenv("AZURE_OPENAI_TIMEOUT_SECS", "30"))
_AZURE_OPENAI_EMBEDDING_BATCH_SIZE = max(int(os.getenv("AZURE_OPENAI_EMBEDDING_BATCH_SIZE", "16")), 1)


def _get_azure_embedding_deployment_name() -> str:
    for key in ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "AZURE_OPENAI_EMBEDDING_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _azure_embed_texts(texts: list[str]) -> list[list[float]]:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    deployment = _get_azure_embedding_deployment_name()
    missing = [
        name
        for name, value in [
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
            ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT or AZURE_OPENAI_EMBEDDING_MODEL", deployment),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing Azure OpenAI embedding settings: {', '.join(missing)}")

    embeddings: list[list[float]] = []
    for start in range(0, len(texts), _AZURE_OPENAI_EMBEDDING_BATCH_SIZE):
        chunk = [text if str(text).strip() else " " for text in texts[start:start + _AZURE_OPENAI_EMBEDDING_BATCH_SIZE]]
        req = request.Request(
            (
                f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings"
                f"?api-version={_AZURE_OPENAI_API_VERSION}"
            ),
            data=json.dumps({"input": chunk}).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=_AZURE_OPENAI_TIMEOUT_SECS) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise RuntimeError(
                f"Azure OpenAI embeddings request failed: {exc.code} {exc.read().decode('utf-8', errors='ignore')}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Azure OpenAI embeddings connection failed: {exc.reason}") from exc

        data = body.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Azure OpenAI embeddings returned an unexpected response shape")
        sorted_rows = sorted(data, key=lambda item: int(item.get("index", 0)))
        embeddings.extend([list(row.get("embedding") or []) for row in sorted_rows])
    return embeddings


def document_id(item: dict[str, object]) -> str:
    metadata = item["metadata"]
    content_hash = md5(str(item.get("content", "")).encode("utf-8")).hexdigest()[:16]
    parts = [
        str(metadata.get("entity", "unknown")),
        str(metadata.get("organization_id", "")),
        str(metadata.get("facility_id", "")),
        str(metadata.get("reporting_period_id", "")),
        str(item.get("source", "")),
        content_hash,
    ]
    return "|".join(parts)


def _serializable_metadata(item: dict[str, object]) -> dict[str, object]:
    metadata = {
        key: value
        for key, value in item["metadata"].items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    metadata["source"] = item["source"]
    return metadata


def document_fingerprint(item: dict[str, object]) -> str:
    payload = json.dumps(
        {
            "source": str(item.get("source", "")),
            "content": str(item.get("content", "")),
            "searchable_text": str(item.get("searchable_text", "")),
            "metadata": _serializable_metadata(item),
        },
        sort_keys=True,
        default=str,
    )
    return md5(payload.encode("utf-8")).hexdigest()


def _collection_signature(documents: list[dict[str, object]]) -> str:
    ids = sorted(document_id(item) for item in documents)
    return md5("||".join(ids).encode("utf-8")).hexdigest()


def _get_sentence_model():
    global _SENTENCE_MODEL, _SENTENCE_MODEL_READY
    if _SENTENCE_MODEL_READY:
        return _SENTENCE_MODEL
    _SENTENCE_MODEL_READY = True
    if SentenceTransformer is None:
        return None
    try:
        _SENTENCE_MODEL = SentenceTransformer(_SENTENCE_MODEL_NAME, local_files_only=True)
    except Exception:
        logger.info("SentenceTransformer model '%s' is not available locally; using hashing fallback.", _SENTENCE_MODEL_NAME)
        return None
    logger.info("Using SentenceTransformer model '%s' for offline compatibility embeddings.", _SENTENCE_MODEL_NAME)
    return _SENTENCE_MODEL


@lru_cache(maxsize=2048)
def _embed_single_text(text: str) -> tuple[float, ...]:
    model = _get_sentence_model()
    if model is not None:
        return tuple(model.encode([text], normalize_embeddings=True)[0].tolist())
    return tuple(_VECTORIZER.transform([text]).toarray()[0].tolist())


def embed_texts(texts: list[str]) -> list[list[float]]:
    if _EMBEDDING_PROVIDER in {"azure", "azure_openai", "azure-openai"}:
        logger.info("Using Azure embeddings only for offline index compatibility helpers; request-time retrieval stays local.")
        return _azure_embed_texts(texts)
    return [list(_embed_single_text(text)) for text in texts]


def _compat_embed_texts(texts: list[str]) -> list[list[float]]:
    facade_module = sys.modules.get("apps.rag.retrieval")
    facade_embed = getattr(facade_module, "embed_texts", None) if facade_module is not None else None
    if callable(facade_embed) and facade_embed is not embed_texts:
        return facade_embed(texts)
    return embed_texts(texts)


def _top_k_indices(scores: np.ndarray, limit: int, *, min_score: float = 0.0) -> np.ndarray:
    if scores.size == 0 or limit <= 0:
        return np.array([], dtype=np.int32)
    candidate_count = min(limit, scores.size)
    indices = np.argpartition(scores, -candidate_count)[-candidate_count:]
    indices = indices[np.argsort(scores[indices])[::-1]]
    if min_score > 0:
        indices = indices[scores[indices] > min_score]
    return indices.astype(np.int32, copy=False)


class HybridRetriever:
    def __init__(
        self,
        *,
        builder,
        chroma_path: str = _CHROMA_PATH,
        collection_name: str = _CHROMA_COLLECTION_NAME,
        document_cache_ttl_secs: float = _DOCUMENT_CACHE_TTL_SECS,
        auto_index_on_request: bool = _AUTO_INDEX_ON_REQUEST,
        refresh_on_empty_search: bool = _REFRESH_ON_EMPTY_SEARCH,
    ):
        self.builder = builder
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.document_cache_ttl_secs = document_cache_ttl_secs
        self.auto_index_on_request = auto_index_on_request
        self.refresh_on_empty_search = refresh_on_empty_search

        self._document_cache: list[dict[str, object]] = []
        self._document_cache_at = 0.0
        self._document_signature = ""
        self._document_ids: list[str] = []
        self._document_id_to_index: dict[str, int] = {}
        self._documents_by_id: dict[str, dict[str, object]] = {}
        self._doc_matrix = None
        self._token_index: dict[str, tuple[int, ...]] = {}
        self._organization_ids = np.array([], dtype=np.int64)
        self._facility_ids = np.array([], dtype=np.int64)
        self._period_ids = np.array([], dtype=np.int64)
        self._organization_candidates: dict[int, set[str]] = {}
        self._facility_candidates: dict[int, set[str]] = {}
        self._period_candidates: dict[int, set[str]] = {}
        self._chroma_disabled = False
        self._ready = False
        self._stale = False
        self._version = 0
        self._initializing = threading.Lock()
        self._search_cache: TTLCache[tuple[object, ...], tuple[RetrievedDocument, ...]] = TTLCache(
            maxsize=_SEARCH_CACHE_SIZE,
            ttl_secs=_SEARCH_CACHE_TTL_SECS,
        )

    @property
    def version(self) -> int:
        return self._version

    @property
    def is_ready(self) -> bool:
        return self._ready

    def mark_stale(self, reason: str = "model_change") -> None:
        self._stale = True
        logger.info("Marked RAG corpus as stale: %s", reason)

    def get_chroma_collection(self):
        if self._chroma_disabled:
            return None
        try:
            client = chromadb.PersistentClient(path=self.chroma_path)
            return client.get_or_create_collection(name=self.collection_name, metadata={"hnsw:space": "cosine"})
        except Exception as exc:
            self._chroma_disabled = True
            logger.warning("Disabling Chroma compatibility helpers after initialization failure: %s", exc)
            return None

    def _collection_state(self, collection) -> tuple[set[str], dict[str, str]]:
        result = collection.get(include=["metadatas"])
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        existing_ids: set[str] = set()
        fingerprints: dict[str, str] = {}

        for index, doc_id in enumerate(ids):
            if not doc_id:
                continue
            existing_ids.add(str(doc_id))
            metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
            fingerprint = str(metadata.get("rag_fingerprint") or "").strip()
            if fingerprint:
                fingerprints[str(doc_id)] = fingerprint

        return existing_ids, fingerprints

    def _prepare_upsert_payload(
        self,
        documents_by_id: dict[str, dict[str, object]],
    ) -> tuple[list[str], list[list[float]], list[str], list[dict[str, object]]]:
        ids = list(documents_by_id.keys())
        embeddings = _compat_embed_texts([str(documents_by_id[doc_id]["searchable_text"]) for doc_id in ids])
        contents = [str(documents_by_id[doc_id]["content"]) for doc_id in ids]
        metadatas = []
        for doc_id in ids:
            metadata = dict(_serializable_metadata(documents_by_id[doc_id]))
            metadata["rag_fingerprint"] = document_fingerprint(documents_by_id[doc_id])
            metadatas.append(metadata)
        return ids, embeddings, contents, metadatas

    def _rebuild_collection(self, documents: list[dict[str, object]]) -> None:
        documents_by_id = {document_id(item): item for item in documents}
        ids, embeddings, contents, metadatas = self._prepare_upsert_payload(documents_by_id)
        client = chromadb.PersistentClient(path=self.chroma_path)
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            logger.exception("Failed deleting stale Chroma collection before rebuild")
        collection = client.get_or_create_collection(name=self.collection_name, metadata={"hnsw:space": "cosine"})
        if ids:
            collection.upsert(ids=ids, embeddings=embeddings, documents=contents, metadatas=metadatas)

    def _sync_chroma_documents(self, documents: list[dict[str, object]]) -> None:
        signature = _collection_signature(documents)
        if signature == self._document_signature:
            return

        collection = self.get_chroma_collection()
        if collection is None:
            return
        documents_by_id = {document_id(item): item for item in documents}
        current_ids = set(documents_by_id.keys())

        try:
            existing_ids, existing_fingerprints = self._collection_state(collection)
            stale_ids = sorted(existing_ids.difference(current_ids))
            changed_or_new_ids = [
                doc_id
                for doc_id, item in documents_by_id.items()
                if existing_fingerprints.get(doc_id) != document_fingerprint(item)
            ]

            if changed_or_new_ids:
                changed_documents = {doc_id: documents_by_id[doc_id] for doc_id in changed_or_new_ids}
                ids, embeddings, contents, metadatas = self._prepare_upsert_payload(changed_documents)
                collection.upsert(ids=ids, embeddings=embeddings, documents=contents, metadatas=metadatas)

            if stale_ids:
                collection.delete(ids=stale_ids)
        except chromadb.errors.InvalidArgumentError as exc:
            if "dimension" not in str(exc).lower():
                raise
            logger.info("Rebuilding Chroma collection '%s' to match embedding dimension.", self.collection_name)
            self._rebuild_collection(documents)

    def _build_name_candidates(self, documents: list[dict[str, object]]) -> tuple[dict[int, set[str]], dict[int, set[str]], dict[int, set[str]]]:
        organizations: dict[int, set[str]] = defaultdict(set)
        facilities: dict[int, set[str]] = defaultdict(set)
        periods: dict[int, set[str]] = defaultdict(set)

        for item in documents:
            metadata = item["metadata"]
            organization_id = metadata.get("organization_id")
            facility_id = metadata.get("facility_id")
            reporting_period_id = metadata.get("reporting_period_id")
            organization_name = str(metadata.get("organization") or "").strip()
            facility_name = str(metadata.get("facility") or "").strip()
            reporting_period_name = str(metadata.get("reporting_period") or "").strip()
            city_name = str(metadata.get("city") or "").strip()
            state_name = str(metadata.get("state") or "").strip()
            country_name = str(metadata.get("country") or "").strip()

            if organization_id and organization_name:
                organizations[int(organization_id)].add(organization_name)
            if facility_id and facility_name and facility_name != "All facilities":
                facilities[int(facility_id)].add(facility_name)
                if city_name:
                    facilities[int(facility_id)].add(city_name)
                if state_name:
                    facilities[int(facility_id)].add(state_name)
                if country_name:
                    facilities[int(facility_id)].add(country_name)
            if reporting_period_id and reporting_period_name:
                periods[int(reporting_period_id)].add(reporting_period_name)

        return dict(organizations), dict(facilities), dict(periods)

    def _replace_snapshot(self, documents: list[dict[str, object]]) -> None:
        self._document_cache = documents
        self._document_cache_at = time.monotonic()
        self._document_signature = ""
        self._document_ids = [document_id(item) for item in documents]
        self._document_id_to_index = {doc_id: index for index, doc_id in enumerate(self._document_ids)}
        self._documents_by_id = {doc_id: item for doc_id, item in zip(self._document_ids, documents)}

        texts = [str(item.get("searchable_text") or "") for item in documents]
        self._doc_matrix = _VECTORIZER.transform(texts) if texts else None

        token_index: dict[str, list[int]] = defaultdict(list)
        organization_ids: list[int] = []
        facility_ids: list[int] = []
        period_ids: list[int] = []

        for index, item in enumerate(documents):
            for token in item.get("tokens", {}):
                if token:
                    token_index[token].append(index)
            metadata = item["metadata"]
            organization_ids.append(int(metadata.get("organization_id")) if metadata.get("organization_id") is not None else -1)
            facility_ids.append(int(metadata.get("facility_id")) if metadata.get("facility_id") is not None else -1)
            period_ids.append(int(metadata.get("reporting_period_id")) if metadata.get("reporting_period_id") is not None else -1)

        self._token_index = {token: tuple(indices) for token, indices in token_index.items()}
        self._organization_ids = np.array(organization_ids, dtype=np.int64)
        self._facility_ids = np.array(facility_ids, dtype=np.int64)
        self._period_ids = np.array(period_ids, dtype=np.int64)
        (
            self._organization_candidates,
            self._facility_candidates,
            self._period_candidates,
        ) = self._build_name_candidates(documents)
        self._version += 1
        self._ready = True
        self._stale = False
        self._search_cache.clear()

    def initialize(self, *, force_refresh: bool = False, source: str = "startup") -> list[dict[str, object]]:
        if self.builder is None:
            self._ready = True
            return self._document_cache
        if self._ready and not force_refresh and not self._stale:
            return self._document_cache

        with self._initializing:
            if self._ready and not force_refresh and not self._stale:
                return self._document_cache
            started_at = time.monotonic()
            logger.info("RAG startup warmup begin source=%s force_refresh=%s", source, force_refresh)
            documents = self.builder.build()
            self._replace_snapshot(documents)
            if self.auto_index_on_request:
                try:
                    self._sync_chroma_documents(documents)
                except Exception:
                    logger.exception("RAG Chroma sync failed during initialization")
            self._document_signature = _collection_signature(documents)
            logger.info(
                "RAG startup warmup complete source=%s documents=%s latency_ms=%.2f",
                source,
                len(documents),
                (time.monotonic() - started_at) * 1000,
            )
            return self._document_cache

    def get_documents(self, force_refresh: bool = False) -> list[dict[str, object]]:
        if force_refresh or not self._ready or self._stale:
            return self.initialize(force_refresh=force_refresh or self._stale, source="get_documents")
        return self._document_cache

    def sync_documents(self, documents: list[dict[str, object]] | None = None, *, force_refresh: bool = False) -> list[dict[str, object]]:
        if documents is None:
            documents = self.get_documents(force_refresh=force_refresh)
        self._sync_chroma_documents(documents)
        return documents

    def rebuild_index(self) -> list[dict[str, object]]:
        return self.initialize(force_refresh=True, source="rebuild_index")

    def _scope_mask(self, scope: SearchScope | None, *, size: int | None = None) -> np.ndarray:
        length = size if size is not None else len(self._document_cache)
        mask = np.ones(length, dtype=bool)
        if scope is None:
            return mask
        if scope.organization_id:
            mask &= np.logical_or(self._organization_ids[:length] == -1, self._organization_ids[:length] == scope.organization_id)
        if scope.facility_id:
            mask &= np.logical_or(self._facility_ids[:length] == -1, self._facility_ids[:length] == scope.facility_id)
        if scope.reporting_period_id:
            mask &= np.logical_or(self._period_ids[:length] == -1, self._period_ids[:length] == scope.reporting_period_id)
        return mask

    def _semantic_scores(
        self,
        query: str,
        documents: list[dict[str, object]],
        scope: SearchScope | None,
        *,
        limit: int,
    ) -> dict[str, float]:
        if not documents:
            return {}

        if documents is self._document_cache and self._doc_matrix is not None:
            doc_matrix = self._doc_matrix
            doc_ids = self._document_ids
            scope_mask = self._scope_mask(scope)
        else:
            texts = [str(item.get("searchable_text") or "") for item in documents]
            if not texts:
                return {}
            doc_matrix = _VECTORIZER.transform(texts)
            doc_ids = [document_id(item) for item in documents]
            scope_mask = np.array([matches_scope(item["metadata"], scope) for item in documents], dtype=bool)

        query_vector = _VECTORIZER.transform([query])
        similarities = (doc_matrix @ query_vector.T).toarray().ravel()
        similarities[~scope_mask] = 0.0
        top_indices = _top_k_indices(similarities, max(limit, 8), min_score=0.01)
        return {doc_ids[index]: float(similarities[index]) for index in top_indices}

    def _resolve_query_scope(self, query: str) -> SearchScope:
        normalized_query = query.lower()
        query_tokens = set(tokenize(query))

        def pick_id(candidates: dict[int, set[str]]) -> int | None:
            matches: list[int] = []
            for entity_id, names in candidates.items():
                for name in names:
                    normalized_name = name.lower()
                    if normalized_name and normalized_name in normalized_query:
                        matches.append(entity_id)
                        break
                    name_tokens = set(tokenize(name))
                    if len(name_tokens) == 1 and name_tokens.intersection(query_tokens):
                        matches.append(entity_id)
                        break
            unique_matches = list(dict.fromkeys(matches))
            return unique_matches[0] if len(unique_matches) == 1 else None

        return SearchScope(
            organization_id=pick_id(self._organization_candidates),
            facility_id=pick_id(self._facility_candidates),
            reporting_period_id=pick_id(self._period_candidates),
        )

    def _candidate_indices(self, query: str, scope: SearchScope | None, *, limit: int) -> tuple[np.ndarray, dict[str, float]]:
        query_tokens = expanded_query_tokens(query)
        lexical_candidates: set[int] = set()
        for token in query_tokens:
            lexical_candidates.update(self._token_index.get(token, ()))

        semantic_scores = self._semantic_scores(query, self._document_cache, scope, limit=max(limit * 8, 32))
        semantic_candidates = {
            self._document_id_to_index[doc_id]
            for doc_id in semantic_scores
            if doc_id in self._document_id_to_index
        }

        combined = lexical_candidates | semantic_candidates
        if not combined:
            return np.array([], dtype=np.int32), semantic_scores

        indices = np.array(sorted(combined), dtype=np.int32)
        if scope is not None:
            mask = self._scope_mask(scope)
            indices = indices[mask[indices]]
        return indices, semantic_scores

    def _hybrid_rank(
        self,
        query: str,
        documents: list[dict[str, object]],
        limit: int,
        scope: SearchScope | None,
    ) -> list[RetrievedDocument]:
        effective_limit = max(1, min(limit, _MAX_RETRIEVED_DOCS))
        fetch_limit = effective_limit + 3
        query_tokens = expanded_query_tokens(query)
        semantic_scores = self._semantic_scores(query, documents, scope, limit=fetch_limit)
        scored_documents: list[RetrievedDocument] = []

        if documents is self._document_cache:
            candidate_indices, semantic_scores = self._candidate_indices(query, scope, limit=effective_limit)
            iterable = (documents[index] for index in candidate_indices.tolist())
        else:
            iterable = (item for item in documents if matches_scope(item["metadata"], scope))

        for item in iterable:
            if documents is not self._document_cache and not matches_scope(item["metadata"], scope):
                continue
            doc_key = document_id(item)
            lexical_score = _lexical_score(query, item)
            semantic_score = semantic_scores.get(doc_key, 0.0)

            if lexical_score <= 0 and semantic_score <= 0:
                continue

            combined_score = (lexical_score * 0.7) + (semantic_score * 0.3)
            if {"location", "city", "country"}.intersection(query_tokens):
                if item["metadata"].get("city") or item["metadata"].get("country") or item["metadata"].get("location"):
                    combined_score += 1.0
            scored_documents.append(
                RetrievedDocument(
                    str(item["source"]),
                    str(item["content"]),
                    dict(item["metadata"]),
                    combined_score,
                )
            )

        scored_documents.sort(key=lambda doc: (doc.score, doc.source), reverse=True)
        if {"location", "city", "country"}.intersection(query_tokens):
            location_docs = [
                doc for doc in scored_documents
                if doc.metadata.get("city") or doc.metadata.get("country") or doc.metadata.get("location")
            ]
            if location_docs:
                remainder = [doc for doc in scored_documents if doc not in location_docs]
                scored_documents = location_docs + remainder
        preferred_entity = _preferred_inventory_entity(query_tokens)
        if preferred_entity is not None:
            preferred_docs = [
                doc for doc in scored_documents
                if str(doc.metadata.get("entity") or "") == preferred_entity
            ]
            if preferred_docs:
                scored_documents = preferred_docs
        if not scored_documents:
            return []

        top_score = max(float(doc.score or 0.0) for doc in scored_documents)
        score_floor = max(_MIN_RETRIEVAL_SCORE, top_score * _RELATIVE_RETRIEVAL_SCORE_FLOOR)
        filtered_documents = [doc for doc in scored_documents if float(doc.score or 0.0) >= score_floor]
        return filtered_documents[:effective_limit]

    def _search_once(
        self,
        query: str,
        limit: int,
        scope: SearchScope | None,
    ) -> list[RetrievedDocument]:
        if not self._ready:
            return []
        inferred_scope = self._resolve_query_scope(query)
        effective_scope = _combined_scope(scope, inferred_scope)
        return self._hybrid_rank(query, self._document_cache, limit, effective_scope)

    def _maybe_initialize_for_request(self) -> None:
        if self._ready and not self._stale:
            return
        if not self._ready and _ALLOW_REQUEST_TIME_WARMUP:
            self.initialize(source="lazy_request_warmup")
            return
        if self._stale and _ALLOW_REQUEST_TIME_REFRESH:
            self.initialize(force_refresh=True, source="lazy_request_refresh")
            return
        if not self._ready:
            logger.warning("RAG retriever is not initialized; request-time warmup is disabled.")
        elif self._stale:
            logger.info("Serving from the last warm RAG snapshot because request-time refresh is disabled.")

    def search(self, query: str, limit: int = 6, scope: SearchScope | None = None) -> list[RetrievedDocument]:
        started_at = time.monotonic()
        self._maybe_initialize_for_request()
        if not self._ready:
            return []

        cache_key = (
            self._version,
            str(query).strip().lower(),
            int(limit),
            scope.organization_id if scope else None,
            scope.facility_id if scope else None,
            scope.reporting_period_id if scope else None,
        )
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "RAG retrieval cache hit query=%r limit=%s docs=%s latency_ms=%.2f",
                query,
                limit,
                len(cached),
                (time.monotonic() - started_at) * 1000,
            )
            return list(cached)

        logger.info("RAG retrieval start query=%r limit=%s", query, limit)
        results = self._search_once(query, limit, scope)
        if not results and self.refresh_on_empty_search and _ALLOW_REQUEST_TIME_REFRESH:
            self.initialize(force_refresh=True, source="empty_result_refresh")
            results = self._search_once(query, limit, scope)
        self._search_cache.set(cache_key, tuple(results))
        logger.info(
            "RAG retrieval end query=%r docs=%s latency_ms=%.2f",
            query,
            len(results),
            (time.monotonic() - started_at) * 1000,
        )
        return results


def matches_scope(metadata: dict[str, object], scope: SearchScope | None) -> bool:
    if scope is None:
        return True
    if scope.organization_id and metadata.get("organization_id") not in {None, scope.organization_id}:
        return False
    if scope.facility_id and metadata.get("facility_id") not in {None, scope.facility_id}:
        return False
    if scope.reporting_period_id and metadata.get("reporting_period_id") not in {None, scope.reporting_period_id}:
        return False
    return True


def _metadata_match_bonus(metadata: dict[str, object], query_tokens: set[str]) -> float:
    bonus = 0.0
    if "location" in query_tokens or "city" in query_tokens or "country" in query_tokens:
        if metadata.get("city") or metadata.get("country") or metadata.get("location"):
            bonus += 0.4
    for field in (
        "organization",
        "facility",
        "reporting_period",
        "department",
        "project",
        "category",
        "subcategory",
        "scope3_category",
        "factor_code",
        "factor_name",
        "pollutant_type",
        "city",
        "country",
    ):
        value = str(metadata.get(field) or "").strip()
        if not value:
            continue
        value_tokens = set(tokenize(value))
        if value_tokens and value_tokens.issubset(query_tokens):
            bonus += 0.2
        elif value.lower() in " ".join(sorted(query_tokens)):
            bonus += 0.15
    if metadata.get("scope") and str(metadata["scope"]).lower() in query_tokens:
        bonus += 0.15
    return bonus


def _lexical_score(query: str, item: dict[str, object]) -> float:
    query_tokens = expanded_query_tokens(query)
    if not query_tokens:
        return 0.0
    doc_tokens = item.get("tokens")
    if not doc_tokens:
        return 0.0

    overlap = 0.0
    for token in query_tokens:
        overlap += float(doc_tokens.get(token, 0))

    searchable_text = str(item.get("searchable_text") or "").lower()
    exact_phrase_bonus = 0.0
    normalized_query = query.lower().strip()
    if normalized_query and normalized_query in searchable_text:
        exact_phrase_bonus += 1.5

    coverage = overlap / max(len(query_tokens), 1)
    density = overlap / max(sum(doc_tokens.values()), 1)
    metadata_bonus = _metadata_match_bonus(item["metadata"], query_tokens)
    location_bonus = 0.0
    entity_bonus = 0.0
    if {"location", "city", "country"}.intersection(query_tokens):
        entity = str(item["metadata"].get("entity") or "")
        if entity in {"facility_overview", "monthly_summary"}:
            location_bonus += 0.6
    entity = str(item["metadata"].get("entity") or "")
    if _is_facility_location_query(query, query_tokens):
        if entity == "facility_overview":
            entity_bonus += 2.6
        elif entity == "organization_overview":
            entity_bonus += 0.6
        elif entity in {"monthly_summary", "emission_breakdown", "emission_activity"}:
            entity_bonus -= 0.8
        elif entity == "emission_factor":
            entity_bonus -= 1.6
    if {"latest", "current", "recent"}.intersection(query_tokens):
        if entity == "monthly_summary" and item["metadata"].get("year") and item["metadata"].get("month"):
            entity_bonus += 0.8
        elif entity == "emission_breakdown":
            entity_bonus -= 0.25
    if is_definition_query(query) or {"what", "define", "definition", "explain", "meaning"}.intersection(query_tokens):
        if entity == "glossary":
            entity_bonus += 1.2
    topic = str(item["metadata"].get("topic") or "")
    if entity == "glossary":
        if "scope 1" in query.lower() and topic == "scope_1":
            entity_bonus += 1.5
        if "scope 2" in query.lower() and topic == "scope_2":
            entity_bonus += 1.5
        if "scope 3" in query.lower() and topic == "scope_3":
            entity_bonus += 1.5
    if "emission" in query_tokens or "emissions" in query_tokens:
        if entity == "monthly_summary":
            entity_bonus += 0.4
    preferred_entity = _preferred_inventory_entity(query_tokens)
    if preferred_entity is not None:
        if entity == preferred_entity:
            entity_bonus += 2.4
        elif entity in {"emission_activity", "monthly_summary", "emission_breakdown"}:
            entity_bonus -= 1.0
    return coverage + (density * 4.0) + exact_phrase_bonus + metadata_bonus + location_bonus + entity_bonus


def _is_reduction_project_query(query_tokens: set[str]) -> bool:
    project_terms = {"project", "initiative", "opportunity", "opportunitie"}
    intent_terms = {"reduction", "available", "availability", "list", "show", "tell"}
    if {"credit", "offset"}.intersection(query_tokens):
        return False
    return bool(project_terms.intersection(query_tokens)) and bool(intent_terms.intersection(query_tokens))


def _is_carbon_credit_query(query_tokens: set[str]) -> bool:
    credit_terms = {"credit", "offset"}
    intent_terms = {"available", "availability", "list", "show", "tell", "project"}
    return bool(credit_terms.intersection(query_tokens)) and bool(intent_terms.intersection(query_tokens))


def _is_facility_location_query(query: str, query_tokens: set[str]) -> bool:
    normalized = (query or "").lower()
    has_location_signal = bool(
        {"location", "facility", "facilities", "site", "sites", "city", "country", "state", "map", "where"}.intersection(query_tokens)
    ) or any(
        phrase in normalized
        for phrase in {"locations", "located", "carbon neutral", "carbon-neutral", "footprint map"}
    )
    if not has_location_signal:
        return False
    return not (
        "factor" in query_tokens
        or "emission factor" in normalized
        or "location based" in normalized
        or "market based" in normalized
    )


def _preferred_inventory_entity(query_tokens: set[str]) -> str | None:
    if _is_carbon_credit_query(query_tokens):
        return "carbon_credit"
    if _is_reduction_project_query(query_tokens):
        return "reduction_project"
    return None


def _resolve_query_scope(query: str, documents: list[dict[str, object]]) -> SearchScope:
    normalized_query = query.lower()
    query_tokens = set(tokenize(query))
    organizations: dict[int, set[str]] = defaultdict(set)
    facilities: dict[int, set[str]] = defaultdict(set)
    periods: dict[int, set[str]] = defaultdict(set)

    for item in documents:
        metadata = item["metadata"]
        organization_id = metadata.get("organization_id")
        facility_id = metadata.get("facility_id")
        reporting_period_id = metadata.get("reporting_period_id")
        organization_name = str(metadata.get("organization") or "").strip()
        facility_name = str(metadata.get("facility") or "").strip()
        reporting_period_name = str(metadata.get("reporting_period") or "").strip()
        city_name = str(metadata.get("city") or "").strip()
        state_name = str(metadata.get("state") or "").strip()
        country_name = str(metadata.get("country") or "").strip()

        if organization_id and organization_name:
            organizations[int(organization_id)].add(organization_name)
        if facility_id and facility_name and facility_name != "All facilities":
            facilities[int(facility_id)].add(facility_name)
            if city_name:
                facilities[int(facility_id)].add(city_name)
            if state_name:
                facilities[int(facility_id)].add(state_name)
            if country_name:
                facilities[int(facility_id)].add(country_name)
        if reporting_period_id and reporting_period_name:
            periods[int(reporting_period_id)].add(reporting_period_name)

    def pick_id(candidates: dict[int, set[str]]) -> int | None:
        matches: list[int] = []
        for entity_id, names in candidates.items():
            for name in names:
                normalized_name = name.lower()
                if normalized_name and normalized_name in normalized_query:
                    matches.append(entity_id)
                    break
                name_tokens = set(tokenize(name))
                if len(name_tokens) == 1 and name_tokens.intersection(query_tokens):
                    matches.append(entity_id)
                    break
        unique_matches = list(dict.fromkeys(matches))
        return unique_matches[0] if len(unique_matches) == 1 else None

    return SearchScope(
        organization_id=pick_id(organizations),
        facility_id=pick_id(facilities),
        reporting_period_id=pick_id(periods),
    )


def _single_or_and(clauses: list[dict[str, object]]) -> dict[str, object] | None:
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _base_scope_clauses(scope: SearchScope | None) -> list[dict[str, object]]:
    clauses: list[dict[str, object]] = []
    if scope and scope.organization_id:
        clauses.append({"organization_id": scope.organization_id})
    if scope and scope.facility_id:
        clauses.append({"facility_id": scope.facility_id})
    if scope and scope.reporting_period_id:
        clauses.append({"reporting_period_id": scope.reporting_period_id})
    return clauses


def _combined_scope(explicit_scope: SearchScope | None, inferred_scope: SearchScope | None) -> SearchScope | None:
    if explicit_scope is None and inferred_scope is None:
        return None
    return SearchScope(
        organization_id=(explicit_scope.organization_id if explicit_scope and explicit_scope.organization_id else None)
        or (inferred_scope.organization_id if inferred_scope else None),
        facility_id=(explicit_scope.facility_id if explicit_scope and explicit_scope.facility_id else None)
        or (inferred_scope.facility_id if inferred_scope else None),
        reporting_period_id=(explicit_scope.reporting_period_id if explicit_scope and explicit_scope.reporting_period_id else None)
        or (inferred_scope.reporting_period_id if inferred_scope else None),
    )


def _query_where(query: str, scope: SearchScope | None) -> dict[str, object] | None:
    clauses = _base_scope_clauses(scope)

    scope_filters = extract_scope_filters(query)
    if scope_filters:
        scope_clauses = [{"scope": scope_value} for scope_value in sorted(scope_filters)]
        clauses.append(scope_clauses[0] if len(scope_clauses) == 1 else {"$or": scope_clauses})

    years = extract_years(query)
    if len(years) == 1:
        clauses.append({"year": int(next(iter(years)))})

    return _single_or_and(clauses)


_DEFAULT_RETRIEVER = HybridRetriever(builder=get_document_builder())


def get_default_retriever() -> HybridRetriever:
    return _DEFAULT_RETRIEVER


def initialize_default_retriever(*, force_refresh: bool = False, source: str = "startup") -> list[dict[str, object]]:
    return _DEFAULT_RETRIEVER.initialize(force_refresh=force_refresh, source=source)


def mark_default_retriever_stale(reason: str = "model_change") -> None:
    _DEFAULT_RETRIEVER.mark_stale(reason)


def get_documents(force_refresh: bool = False) -> list[dict[str, object]]:
    return _DEFAULT_RETRIEVER.get_documents(force_refresh=force_refresh)


def get_chroma_collection():
    return _DEFAULT_RETRIEVER.get_chroma_collection()


def search(query: str, limit: int = 6, scope: SearchScope | None = None) -> list[RetrievedDocument]:
    return _DEFAULT_RETRIEVER.search(query, limit=limit, scope=scope)
