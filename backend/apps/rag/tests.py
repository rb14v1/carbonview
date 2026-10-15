import os
from datetime import date
from decimal import Decimal
from time import monotonic
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory

from apps.company.models import Facility, Organization, ReportingPeriod
from apps.emission.models import (
    EmissionActivity,
    EmissionCategory,
    EmissionFactor,
    EmissionFactorSource,
    GasType,
    RecordStatus,
    Scope2Method,
    UnitOfMeasure,
)
from apps.rag.answering import generate_local_answer
from apps.rag.core.answering import CarbonFormatter, rewrite_query_with_history
from apps.rag.core.common import expand_relative_time_query, extract_month_numbers
from apps.rag.core.orchestrator import _dashboard_home_value_topic
from apps.rag.core.types import RetrievedDocument
from apps.rag.agent import QueryRouter
from apps.rag.charting import generate_chart_payload
from apps.rag.common import make_document
from apps.rag.document_builders import build_documents
from apps.rag.retrieval import (
    HybridRetriever,
    document_fingerprint,
    document_id,
    initialize_default_retriever,
    mark_default_retriever_stale,
    search,
)
from apps.rag.sql_tool import SQLTool
from apps.rag.types import SearchScope
from apps.rag import views as rag_views
from apps.rag.views import ask_ai, chart_data
from apps.shared.models import City, Country, Location, State
from apps.summary.models import MonthlyEmissionSummary, ReductionProject


class _FakeCollection:
    def __init__(self, *, ids: list[str] | None = None, metadatas: list[dict[str, object]] | None = None):
        self.ids = list(ids or [])
        self.metadatas = list(metadatas or [])
        self.upsert_calls: list[dict[str, object]] = []
        self.delete_calls: list[list[str]] = []

    def get(self, include=None):
        return {
            "ids": list(self.ids),
            "metadatas": list(self.metadatas),
        }

    def upsert(self, ids, embeddings, documents, metadatas):
        self.upsert_calls.append(
            {
                "ids": list(ids),
                "embeddings": list(embeddings),
                "documents": list(documents),
                "metadatas": list(metadatas),
            }
        )

    def delete(self, ids):
        self.delete_calls.append(list(ids))


class RetrieverIndexSyncTests(SimpleTestCase):
    def _make_doc(self, *, source: str, content: str, metadata: dict[str, object]):
        return make_document(source=source, content=content, metadata=metadata, keywords={"test"})

    def test_get_documents_skips_request_time_sync_when_disabled(self):
        class _Builder:
            def build(self_inner):
                return [
                    self._make_doc(
                        source="Doc A",
                        content="Stable content",
                        metadata={"entity": "test", "organization_id": 1},
                    )
                ]

        retriever = HybridRetriever(builder=_Builder(), auto_index_on_request=False, document_cache_ttl_secs=900)

        with patch.object(retriever, "_sync_chroma_documents") as mock_sync:
            documents = retriever.get_documents()

        self.assertEqual(len(documents), 1)
        mock_sync.assert_not_called()

    def test_sync_only_upserts_new_docs_and_deletes_stale_docs(self):
        retriever = HybridRetriever(builder=None)  # type: ignore[arg-type]
        unchanged_doc = self._make_doc(
            source="Doc A",
            content="Stable content",
            metadata={"entity": "test", "organization_id": 1},
        )
        new_doc = self._make_doc(
            source="Doc B",
            content="Fresh content",
            metadata={"entity": "test", "organization_id": 1},
        )
        stale_doc = self._make_doc(
            source="Doc Old",
            content="Old content",
            metadata={"entity": "test", "organization_id": 1},
        )
        collection = _FakeCollection(
            ids=[document_id(unchanged_doc), document_id(stale_doc)],
            metadatas=[
                {"rag_fingerprint": document_fingerprint(unchanged_doc)},
                {"rag_fingerprint": document_fingerprint(stale_doc)},
            ],
        )

        with patch.object(retriever, "get_chroma_collection", return_value=collection), patch(
            "apps.rag.retrieval.embed_texts",
            return_value=[[0.1, 0.2]],
        ) as mock_embed:
            retriever._sync_chroma_documents([unchanged_doc, new_doc])

        self.assertEqual(mock_embed.call_count, 1)
        self.assertEqual(len(collection.upsert_calls), 1)
        self.assertEqual(collection.upsert_calls[0]["ids"], [document_id(new_doc)])
        self.assertEqual(collection.delete_calls, [[document_id(stale_doc)]])

    def test_sync_reindexes_when_fingerprint_changes_for_same_id(self):
        retriever = HybridRetriever(builder=None)  # type: ignore[arg-type]
        current_doc = self._make_doc(
            source="Doc A",
            content="Stable content",
            metadata={"entity": "test", "organization_id": 1, "city": "Bengaluru"},
        )
        previous_doc = self._make_doc(
            source="Doc A",
            content="Stable content",
            metadata={"entity": "test", "organization_id": 1, "city": "Mumbai"},
        )
        collection = _FakeCollection(
            ids=[document_id(current_doc)],
            metadatas=[{"rag_fingerprint": document_fingerprint(previous_doc)}],
        )

        with patch.object(retriever, "get_chroma_collection", return_value=collection), patch(
            "apps.rag.retrieval.embed_texts",
            return_value=[[0.1, 0.2]],
        ) as mock_embed:
            retriever._sync_chroma_documents([current_doc])

        self.assertEqual(mock_embed.call_count, 1)
        self.assertEqual(len(collection.upsert_calls), 1)
        self.assertEqual(collection.upsert_calls[0]["ids"], [document_id(current_doc)])
        self.assertEqual(collection.delete_calls, [])

    def test_hybrid_rank_drops_low_confidence_tail_documents(self):
        retriever = HybridRetriever(builder=None)  # type: ignore[arg-type]
        documents = [
            self._make_doc(
                source="High Match",
                content="Reduction project solar initiative for North Plant with expected reduction 42.00 tCO2e",
                metadata={"entity": "reduction_project", "facility": "North Plant", "facility_id": 1},
            ),
            self._make_doc(
                source="Weak Match",
                content="General glossary language with little overlap",
                metadata={"entity": "glossary"},
            ),
        ]

        with patch.object(retriever, "_semantic_scores", return_value={}):
            results = retriever._hybrid_rank("available reduction projects for North Plant", documents, 6, None)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "High Match")


class QueryRewriteTests(SimpleTestCase):
    def test_this_year_query_is_not_mistaken_for_history_follow_up(self):
        history = [
            type("Turn", (), {"role": "user", "content": "What is scope 1?"})(),
        ]
        rewritten = rewrite_query_with_history("what is the emission of scope 1 this year", history)
        self.assertEqual(rewritten, "what is the emission of scope 1 this year")

    def test_temporal_follow_up_reuses_previous_query_context(self):
        history = [
            type("Turn", (), {"role": "user", "content": "what is the emission of scope 1 this year"})(),
        ]
        rewritten = rewrite_query_with_history("i want for 2024", history)
        self.assertEqual(rewritten, "what is the emission of scope 1 for 2024")

    def test_relative_year_expansion_uses_current_year(self):
        expanded = expand_relative_time_query("what is the emission of scope 1 this year")
        self.assertIn("2026", expanded)

    def test_extract_month_numbers_supports_month_only_queries(self):
        self.assertEqual(extract_month_numbers("what is the scope 1 emission of jan 1"), (1,))

    def test_agent_decision_metadata_defaults_to_empty_dict(self):
        decision = QueryRouter().decide("what is scope 1")
        self.assertEqual(decision.metadata, {})

    def test_build_decision_without_metadata_uses_empty_dict(self):
        decision = QueryRouter()._build_decision("rag", "semantic_default")
        self.assertEqual(decision.metadata, {})

    def test_router_marks_greetings_as_out_of_domain_greeting(self):
        decision = QueryRouter().decide("hello")
        self.assertEqual(decision.route, "out_of_domain")
        self.assertEqual(decision.reason, "greeting")
        self.assertFalse(decision.needs_sql)
        self.assertFalse(decision.needs_rag)

    def test_router_routes_carbonview_identity_question_to_rag(self):
        decision = QueryRouter().decide("what is carbon view")
        self.assertEqual(decision.route, "rag")
        self.assertEqual(decision.reason, "definition_query")

    def test_router_keeps_compound_chart_and_explain_queries_on_sql_rag(self):
        decision = QueryRouter().decide("show a chart and explain emissions for 2023 vs 2024")
        self.assertEqual(decision.route, "sql_rag")
        self.assertTrue(decision.needs_sql)
        self.assertTrue(decision.needs_rag)

    def test_router_treats_compact_scope_year_query_with_for_as_numeric(self):
        decision = QueryRouter().decide("scope 2 emission for 2023")
        self.assertEqual(decision.route, "sql")
        self.assertEqual(decision.reason, "numeric_query")

    def test_router_treats_compact_scope_year_query_with_in_as_numeric(self):
        decision = QueryRouter().decide("scope 2 emission in 2023")
        self.assertEqual(decision.route, "sql")
        self.assertEqual(decision.reason, "numeric_query")

    def test_dashboard_home_value_topic_matches_partial_snapshot_phrase(self):
        self.assertEqual(
            _dashboard_home_value_topic("show the transition snapshot"),
            "resource_transition_snapshot_value",
        )

    def test_dashboard_home_value_topic_allows_latest_reporting_month_question(self):
        self.assertEqual(
            _dashboard_home_value_topic("what is the latest reporting month"),
            "latest_reporting_month_value",
        )

    def test_dashboard_home_value_topic_keeps_definition_style_scope_query_out_of_value_mode(self):
        self.assertIsNone(_dashboard_home_value_topic("what is scope 2"))

    def test_llm_routing_disable_flag_can_reset_after_cooldown(self):
        router = QueryRouter()
        router._llm_routing_disabled = True
        router._llm_routing_disabled_at = monotonic() - 1000

        with patch.dict(os.environ, {"RAG_LLM_INTENT_ROUTING": "true"}, clear=False):
            decision = router._llm_intent_decision("hi there", {})

        self.assertIsNone(decision)
        self.assertFalse(router._llm_routing_disabled)


class RagRebuildTests(TestCase):
    """Regression tests covering document building and retrieval behavior."""
    @classmethod
    def setUpTestData(cls):
        """Create a compact dataset used across all RAG regression tests."""
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(username="rag-user", password="secret")

        country = Country.objects.create(code="IN", name="India")
        state = State.objects.create(country=country, code="KA", name="Karnataka")
        city = City.objects.create(state=state, name="Bengaluru")
        location = Location.objects.create(
            country=country,
            state=state,
            city=city,
            street_address="1 MG Road",
            postal_code="560001",
        )

        cls.organization = Organization.objects.create(name="CarbonView Labs")
        cls.facility_a = Facility.objects.create(
            organization=cls.organization,
            location=location,
            name="North Plant",
            facility_code="NP-1",
        )
        cls.facility_b = Facility.objects.create(
            organization=cls.organization,
            location=location,
            name="South Plant",
            facility_code="SP-1",
        )
        cls.period = ReportingPeriod.objects.create(
            organization=cls.organization,
            name="FY 2025",
            year=2025,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            is_closed=False,
        )
        cls.latest_period = ReportingPeriod.objects.create(
            organization=cls.organization,
            name="FY 2026",
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_closed=False,
        )

        cls.unit = UnitOfMeasure.objects.create(code="kWh", name="Kilowatt hour")
        cls.gas_type = GasType.objects.create(code="CO2", gas_name="Carbon dioxide", gwp_value=Decimal("1"))
        cls.scope_parent = EmissionCategory.objects.create(
            code="S1-PARENT",
            name="Scope 1",
            scope="S1",
            category_type="scope",
        )
        cls.category = EmissionCategory.objects.create(
            code="STATIONARY",
            name="Stationary Combustion",
            scope="S1",
            parent=cls.scope_parent,
            category_type="category",
        )
        cls.scope2_parent = EmissionCategory.objects.create(
            code="S2-PARENT",
            name="Scope 2",
            scope="S2",
            category_type="scope",
        )
        cls.scope2_category = EmissionCategory.objects.create(
            code="PURCHASED-ELECTRICITY",
            name="Purchased Electricity",
            scope="S2",
            parent=cls.scope2_parent,
            category_type="category",
        )
        cls.factor_source = EmissionFactorSource.objects.create(
            name="DEFRA",
            version="2025",
        )
        cls.factor = EmissionFactor.objects.create(
            source=cls.factor_source,
            category=cls.category,
            gas_type=cls.gas_type,
            factor_code="FUEL-2025",
            factor_name="Fuel Combustion Factor",
            factor_value=Decimal("0.25000000"),
            activity_unit=cls.unit,
            factor_unit="kg gas/kWh",
            valid_from=date(2025, 1, 1),
            is_active=True,
        )

        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.period,
            year=2023,
            month=12,
            scope="S1",
            total_co2e=Decimal("25.900000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.period,
            year=2024,
            month=12,
            scope="S1",
            total_co2e=Decimal("31.400000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.period,
            year=2025,
            month=1,
            scope="S1",
            total_co2e=Decimal("12.340000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.period,
            year=2025,
            month=2,
            scope="S2",
            total_co2e=Decimal("18.900000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_b,
            reporting_period=cls.period,
            year=2025,
            month=1,
            scope="S1",
            total_co2e=Decimal("56.780000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.latest_period,
            year=2026,
            month=1,
            scope="S1",
            total_co2e=Decimal("9.100000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=cls.organization,
            facility=cls.facility_a,
            reporting_period=cls.latest_period,
            year=2026,
            month=1,
            scope="S2",
            total_co2e=Decimal("99.900000"),
        )

        activities = []
        for index in range(260):
            activities.append(
                EmissionActivity(
                    organization=cls.organization,
                    facility=cls.facility_a,
                    reporting_period=cls.period,
                    category=cls.category,
                    activity_name=f"Boiler Run {index}",
                    activity_date=date(2025, 1, 1),
                    quantity=Decimal("10.000000"),
                    unit=cls.unit,
                    factor_code="FUEL-2025",
                    scope2_method="not_applicable",
                    data_quality="actual",
                    supplier_name="Acme Energy",
                    total_co2e=Decimal("2.500000"),
                    status=RecordStatus.APPROVED,
                    entered_by=cls.user,
                )
            )
        EmissionActivity.objects.bulk_create(activities, batch_size=100)
        EmissionActivity.objects.bulk_create(
            [
                EmissionActivity(
                    organization=cls.organization,
                    facility=cls.facility_a,
                    reporting_period=cls.latest_period,
                    category=cls.category,
                    activity_name="Boiler Run Latest 1",
                    activity_date=date(2026, 1, 10),
                    quantity=Decimal("10.000000"),
                    unit=cls.unit,
                    factor_code="FUEL-2025",
                    scope2_method=Scope2Method.NOT_APPLICABLE,
                    data_quality="actual",
                    supplier_name="Acme Energy",
                    total_co2e=Decimal("3.000000"),
                    status=RecordStatus.APPROVED,
                    entered_by=cls.user,
                ),
                EmissionActivity(
                    organization=cls.organization,
                    facility=cls.facility_a,
                    reporting_period=cls.latest_period,
                    category=cls.category,
                    activity_name="Boiler Run Latest 2",
                    activity_date=date(2026, 1, 11),
                    quantity=Decimal("10.000000"),
                    unit=cls.unit,
                    factor_code="FUEL-2025",
                    scope2_method=Scope2Method.NOT_APPLICABLE,
                    data_quality="actual",
                    supplier_name="Acme Energy",
                    total_co2e=Decimal("4.000000"),
                    status=RecordStatus.APPROVED,
                    entered_by=cls.user,
                ),
                EmissionActivity(
                    organization=cls.organization,
                    facility=cls.facility_a,
                    reporting_period=cls.latest_period,
                    category=cls.scope2_category,
                    activity_name="Grid Power Latest",
                    activity_date=date(2026, 1, 12),
                    quantity=Decimal("10.000000"),
                    unit=cls.unit,
                    factor_code="FUEL-2025",
                    scope2_method=Scope2Method.LOCATION_BASED,
                    data_quality="actual",
                    supplier_name="Grid Utility",
                    total_co2e=Decimal("50.000000"),
                    status=RecordStatus.APPROVED,
                    entered_by=cls.user,
                ),
            ],
            batch_size=100,
        )

    def test_build_documents_indexes_all_approved_activities(self):
        """Ensure approved emission activities are fully represented in RAG docs."""
        documents = build_documents()
        activity_docs = [doc for doc in documents if doc["metadata"].get("entity") == "emission_activity"]
        self.assertEqual(len(activity_docs), 263)

    def test_document_ids_are_unique_for_same_month_different_facilities(self):
        """Ensure document ids stay unique across similar monthly summary rows."""
        documents = build_documents()
        monthly_docs = [doc for doc in documents if doc["metadata"].get("entity") == "monthly_summary"]
        self.assertEqual(len(monthly_docs), 7)
        self.assertEqual(len({document_id(doc) for doc in monthly_docs}), 7)

    def test_search_can_find_emission_factor_by_exact_code(self):
        """Ensure exact emission factor codes remain easy to retrieve."""
        results = search("Show me the FUEL-2025 emission factor", limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0].metadata.get("entity"), "emission_factor")
        self.assertEqual(results[0].metadata.get("factor_code"), "FUEL-2025")

    def test_location_queries_return_city_and_country_from_retrieved_metadata(self):
        """Ensure location queries answer from retrieved city and country metadata."""
        results = search("List the locations", limit=5)
        self.assertTrue(results)
        answer = CarbonFormatter().format_local("List the locations", results)
        self.assertIn("Bengaluru", answer)
        self.assertIn("India", answer)

    def test_scope_query_prefers_retrieved_data_over_generic_definition(self):
        """Ensure scope data questions answer with retrieved values, not glossary text."""
        results = search("What are the latest scope 1 emissions for North Plant?", limit=8)
        self.assertTrue(results)
        answer = CarbonFormatter().format_local("What are the latest scope 1 emissions for North Plant?", results)
        self.assertIn("tCO2e", answer)
        self.assertNotIn("Scope 1 covers direct emissions", answer)

    def test_chart_payload_can_build_monthly_trend(self):
        """Ensure graph payloads can be built from matched monthly summaries."""
        results = search("Show monthly emissions for North Plant", limit=8)
        chart = generate_chart_payload("Show monthly emissions for North Plant", results)
        self.assertIsNotNone(chart)
        assert chart is not None
        self.assertEqual(chart["chart_type"], "line")
        self.assertTrue(chart["labels"])
        self.assertTrue(chart["series"])

    def test_chart_endpoint_returns_graph_ready_json(self):
        """Ensure the chart endpoint returns graph-ready payloads."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/chart/", {"query": "Show monthly emissions for North Plant"}, format="json")
        response = chart_data(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider"], "rag-chart-local")
        self.assertIn("chart", response.data)

    def test_general_scope_definition_answer_is_simple(self):
        """Ensure general scope definition questions get plain-language answers."""
        answer, used_docs = generate_local_answer("What is scope 1?", documents=[])
        self.assertIn("direct emissions", answer.lower())
        self.assertNotIn("Scope 2 covers", answer)
        self.assertEqual(used_docs, [])

    def test_definition_query_endpoint_prefers_glossary_over_monthly_totals(self):
        """Ensure endpoint definition questions do not answer with latest numeric totals."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what is scope 1 emissions"}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertEqual(response.data["route_reason"], "definition_query")
        self.assertIn("direct emissions", response.data["answer"].lower())
        self.assertNotIn("2,078.99", response.data["answer"])
        self.assertNotIn("tco2e", response.data["answer"].lower())

    def test_definition_query_without_space_in_scope_number_uses_matching_glossary(self):
        """Ensure `scope2` still resolves to the Scope 2 glossary definition."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what is scope2"}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertIn("purchased electricity", response.data["answer"].lower())
        self.assertNotIn("value chain", response.data["answer"].lower())

    def test_unsupported_scope_definition_does_not_guess_wrong_glossary(self):
        """Ensure unsupported scope numbers return a clear unsupported response."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what is scope 4?"}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertIn("supports Scope 1, Scope 2, and Scope 3", response.data["answer"])
        self.assertIn("Scope 4", response.data["answer"])
        self.assertNotIn("purchased electricity", response.data["answer"].lower())

    def test_simple_words_follow_up_uses_history_context(self):
        """Ensure simple-language follow-ups reuse prior general-question context."""
        history = [
            {"role": "user", "content": "What is scope 1?"},
            {"role": "assistant", "content": "Scope 1 means direct emissions from owned or controlled sources."},
        ]
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "Explain that in simple words", "history": history}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("direct emissions", response.data["answer"].lower())

    def test_history_follow_up_keeps_facility_context(self):
        """Ensure follow-up scope questions keep the prior facility context."""
        history = [
            {"role": "user", "content": "What are the latest scope 1 emissions for North Plant?"},
        ]
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "And what about scope 2?", "history": history}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("North Plant", response.data["answer"])
        self.assertIn("Scope 2", response.data["answer"])

    def test_contextual_company_value_query_uses_scope_without_company_name(self):
        """Ensure 'this company' follow-ups can use request scope instead of explicit names."""
        history = [
            {"role": "user", "content": "What is scope 1?"},
            {"role": "assistant", "content": "Scope 1 means direct emissions from sources your company owns or controls."},
        ]
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "so whats the scope 1 emission of this company",
                "history": history,
                "organization_id": self.organization.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("tCO2e", response.data["answer"])
        self.assertNotIn("Scope 2 is purchased energy", response.data["answer"])
        self.assertIn("latest monthly emissions", response.data["resolved_query"].lower())

    def test_scope_query_with_explicit_time_returns_data_not_definition(self):
        """Ensure time-bound scope emission questions are treated as data lookups."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is the scope 1 emission in december 2023",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertIn("tco2e", response.data["answer"].lower())
        self.assertNotIn("direct emissions", response.data["answer"].lower())

    def test_scope_query_with_month_only_phrase_uses_month_filter(self):
        """Ensure month-only prompts like 'jan 1' resolve to January scope-1 data, not the full reporting period."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is the scope 1 emission of jan 1",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertIn("January", response.data["answer"])
        self.assertNotIn("FY2026", response.data["answer"])

    def test_compact_scope_year_query_with_for_uses_sql(self):
        MonthlyEmissionSummary.objects.create(
            organization=self.organization,
            facility=self.facility_a,
            reporting_period=self.period,
            year=2023,
            month=12,
            scope="S2",
            total_co2e=Decimal("44.150000"),
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "scope 2 emission for 2023",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertIn("Scope 2", response.data["answer"])
        self.assertIn("2023", response.data["answer"])
        self.assertNotIn("indirect emissions from purchased electricity", response.data["answer"].lower())

    def test_compact_scope_year_query_with_in_uses_sql(self):
        MonthlyEmissionSummary.objects.create(
            organization=self.organization,
            facility=self.facility_a,
            reporting_period=self.period,
            year=2023,
            month=12,
            scope="S2",
            total_co2e=Decimal("44.150000"),
        )
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "scope 2 emission in 2023",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertIn("Scope 2", response.data["answer"])
        self.assertIn("2023", response.data["answer"])
        self.assertNotIn("indirect emissions from purchased electricity", response.data["answer"].lower())

    def test_numeric_sql_empty_query_does_not_fall_back_to_scope_definition(self):
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "scope 2 emission for 2035",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        glossary_doc = RetrievedDocument(
            source="Glossary: Scope 2",
            content="Scope 2 means indirect emissions from purchased electricity, steam, heating, or cooling consumed by the organization.",
            metadata={"entity": "glossary", "topic": "scope_2"},
            score=0.99,
        )
        with patch("apps.rag.views.search", return_value=[glossary_doc]):
            response = ask_ai(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertNotIn("indirect emissions from purchased electricity", response.data["answer"].lower())
        self.assertIn("could not find matched emissions data", response.data["answer"].lower())

    def test_this_year_scope_query_uses_current_year_not_history(self):
        """Ensure `this year` resolves against the current year instead of prior chat context."""
        history = [
            {"role": "user", "content": "what is the scope 1 emission in 2023 march"},
            {"role": "assistant", "content": "No matched data."},
        ]
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is the emission of scope 1 this year",
                "history": history,
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertIn("2026", response.data["resolved_query"])
        self.assertIn("tco2e", response.data["answer"].lower())

    def test_year_follow_up_keeps_previous_numeric_topic(self):
        """Ensure short year follow-ups preserve the prior emission topic."""
        history = [
            {"role": "user", "content": "what is the emission of scope 1 this year"},
            {"role": "assistant", "content": "Scope 1 emissions for North Plant in FY2026 were 7.00 tCO2e."},
        ]
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "i want for 2024",
                "history": history,
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["route"], "out_of_domain")
        self.assertIn("2024", response.data["resolved_query"])

    def test_chatbot_can_compare_short_month_year_references(self):
        """Ensure chatbot queries like 'Dec 23 and Dec 24' resolve to matched monthly data."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "give me the graph comparison for dec 23 and dec 24",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("December 2023", response.data["answer"])
        self.assertIn("December 2024", response.data["answer"])
        self.assertIn("tCO2e", response.data["answer"])
        self.assertIn("2023", response.data["resolved_query"])
        self.assertIn("2024", response.data["resolved_query"])

    def test_router_detects_composite_numeric_explanation_queries(self):
        """Ensure combined numeric-plus-explanation queries route to both SQL and RAG."""
        decision = QueryRouter().decide("Compare emissions for 2023 vs 2024 and explain why it increased")
        self.assertEqual(decision.route, "sql_rag")
        self.assertTrue(decision.needs_sql)
        self.assertTrue(decision.needs_rag)
        self.assertFalse(decision.needs_chart)

    def test_router_selects_expected_tools_for_query_types(self):
        """Ensure deterministic routing across numeric, semantic, chart, and mixed queries."""
        router = QueryRouter()

        numeric = router.decide("compare emissions 2023 vs 2024")
        self.assertEqual(numeric.route, "sql")
        self.assertTrue(numeric.needs_sql)
        self.assertFalse(numeric.needs_rag)
        self.assertTrue(numeric.needs_chart)

        explanation = router.decide("explain scope 2 emissions")
        self.assertEqual(explanation.route, "rag")
        self.assertFalse(explanation.needs_sql)
        self.assertTrue(explanation.needs_rag)
        self.assertFalse(explanation.needs_chart)

        chart = router.decide("show graph of emissions")
        self.assertEqual(chart.route, "chart")
        self.assertFalse(chart.needs_sql)
        self.assertFalse(chart.needs_rag)
        self.assertTrue(chart.needs_chart)

        mixed = router.decide("show trend and explain the reason")
        self.assertEqual(mixed.route, "sql_rag")
        self.assertTrue(mixed.needs_sql)
        self.assertTrue(mixed.needs_rag)

    def test_warm_rag_request_stays_under_20_seconds(self):
        """Ensure warmed semantic requests stay well below worker timeout territory."""
        initialize_default_retriever(source="test_perf_warm_rag")
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "What is scope 1 emissions"}, format="json")

        started_at = monotonic()
        response = ask_ai(request)
        elapsed = monotonic() - started_at

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertLess(elapsed, 20.0, f"Warm RAG request took {elapsed:.2f}s")

    def test_warm_sql_rag_request_stays_under_20_seconds(self):
        """Ensure mixed numeric-plus-explanation requests stay below the latency ceiling."""
        initialize_default_retriever(source="test_perf_warm_sql_rag")
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "Compare emissions for Dec 23 and Dec 24 and explain why it increased",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
                "reporting_period_id": self.period.id,
            },
            format="json",
        )

        started_at = monotonic()
        response = ask_ai(request)
        elapsed = monotonic() - started_at

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql_rag")
        self.assertLess(elapsed, 20.0, f"Warm SQL+RAG request took {elapsed:.2f}s")

    def test_stale_rag_refresh_request_stays_under_20_seconds(self):
        """Ensure a stale-index refresh path still returns before Gunicorn timeout risk."""
        mark_default_retriever_stale("test_perf_refresh")
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "What reduction projects are available for South Plant?",
                "organization_id": self.organization.id,
            },
            format="json",
        )

        started_at = monotonic()
        response = ask_ai(request)
        elapsed = monotonic() - started_at

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertLess(elapsed, 20.0, f"Stale refresh request took {elapsed:.2f}s")

    def test_sql_tool_returns_standardized_output_shape(self):
        """Ensure SQL results keep a stable formatter-friendly structure."""
        result = SQLTool().execute(
            "Compare emissions for December 2023 and December 2024",
            SearchScope(
                organization_id=self.organization.id,
                facility_id=self.facility_a.id,
                reporting_period_id=self.period.id,
            ),
        )
        self.assertEqual(result["tool"], "sql")
        self.assertEqual(result["route"], "sql")
        self.assertEqual(result["type"], "comparison")
        self.assertIsInstance(result["data"], list)
        self.assertIn("metadata", result)
        self.assertIn("filters", result["metadata"])
        self.assertIn("row_count", result["metadata"])

    def test_sql_tool_defaults_to_latest_reporting_period_for_total_queries(self):
        """Ensure non-historical totals use the latest reporting period instead of all history."""
        result = SQLTool().execute(
            "total emissions",
            SearchScope(
                organization_id=self.organization.id,
                facility_id=self.facility_a.id,
            ),
        )
        self.assertEqual(result["type"], "total")
        self.assertEqual(result["metadata"]["filters"]["reporting_period_id"], self.latest_period.id)
        self.assertEqual(result["metadata"]["aggregate_total_co2e"], 57.0)
        self.assertEqual(result["metadata"]["data_source"], "emission_activity")

    def test_sql_tool_enforces_scope_filter_with_latest_period_default(self):
        """Ensure scope-specific totals do not bleed across other scopes or older periods."""
        result = SQLTool().execute(
            "total scope 1 emissions",
            SearchScope(
                organization_id=self.organization.id,
                facility_id=self.facility_a.id,
            ),
        )
        self.assertEqual(result["metadata"]["filters"]["reporting_period_id"], self.latest_period.id)
        self.assertEqual(result["metadata"]["aggregate_total_co2e"], 7.0)
        self.assertTrue(all(row["scope"] == "S1" for row in result["data"]))
        self.assertNotIn("rows", result["fallback_answer"].lower())
        self.assertIn("Scope 1 emissions", result["fallback_answer"])

    def test_sql_tool_preserves_multi_period_trends(self):
        """Ensure trend queries still span history instead of being forced into one period."""
        result = SQLTool().execute(
            "show emissions trend over time",
            SearchScope(
                organization_id=self.organization.id,
                facility_id=self.facility_a.id,
            ),
        )
        self.assertEqual(result["type"], "trend")
        self.assertIsNone(result["metadata"]["filters"]["reporting_period_id"])
        self.assertGreaterEqual(len(result["data"]), 4)

    def test_sql_tool_expands_year_ranges_for_total_queries(self):
        """Ensure year-range phrasing includes every year in the requested span."""
        result = SQLTool().execute(
            "give me total emissions from 2023 to 2025",
            SearchScope(
                organization_id=self.organization.id,
                facility_id=self.facility_a.id,
            ),
        )
        self.assertEqual(result["type"], "total")
        self.assertIsNone(result["metadata"]["filters"]["reporting_period_id"])
        self.assertEqual(result["metadata"]["filters"]["years"], [2023, 2024, 2025])

    def test_company_scope_total_query_returns_friendly_dashboard_aligned_answer(self):
        """Ensure company scope totals align with approved activity data and avoid row-count wording."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is the total scope 1 emissions value of the company",
                "organization_id": self.organization.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertEqual(response.data["tool_output"]["metadata"]["data_source"], "emission_activity")
        self.assertEqual(response.data["tool_output"]["metadata"]["aggregate_total_co2e"], 7.0)
        self.assertNotIn("rows", response.data["tool_output"]["fallback_answer"].lower())
        self.assertNotIn("rows", response.data["answer"].lower())

    def test_total_with_graph_returns_numeric_answer_and_chart(self):
        """Ensure mixed total-plus-graph prompts keep the total answer and also include chart data."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is total emission of scope 1 in 2025 and give it in graph",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertEqual(response.data["tool_output"]["type"], "total")
        self.assertIn("Scope 1 emissions", response.data["answer"])
        self.assertIn("tCO2e", response.data["answer"])
        self.assertIsNotNone(response.data["chart"])
        self.assertEqual(response.data["chart"]["title"], "Monthly Emissions Trend")
        self.assertTrue(response.data["chart"]["labels"])
        self.assertTrue(response.data["chart"]["series"])

    def test_facility_ranking_query_returns_top_facility_for_latest_period(self):
        """Ensure superlative facility questions use SQL ranking instead of semantic RAG snippets."""
        MonthlyEmissionSummary.objects.create(
            organization=self.organization,
            facility=self.facility_b,
            reporting_period=self.latest_period,
            year=2026,
            month=1,
            scope="S1",
            total_co2e=Decimal("150.000000"),
        )
        MonthlyEmissionSummary.objects.create(
            organization=self.organization,
            facility=self.facility_b,
            reporting_period=self.latest_period,
            year=2026,
            month=1,
            scope="S2",
            total_co2e=Decimal("50.000000"),
        )

        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "which facility is most carbon emitting now",
                "organization_id": self.organization.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertEqual(response.data["tool_output"]["type"], "ranking")
        self.assertIn("highest emitting facility", response.data["answer"].lower())
        self.assertIn("South Plant", response.data["answer"])

    def test_year_summary_query_returns_scope_breakdown_and_total(self):
        """Ensure year summary questions return scope totals instead of a single-scope answer."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "give me summary of 2025 year",
                "organization_id": self.organization.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertEqual(response.data["tool_output"]["type"], "summary")
        self.assertIn("Scope 1", response.data["answer"])
        self.assertIn("Scope 2", response.data["answer"])
        self.assertIn("Total:", response.data["answer"])

    def test_reduction_project_query_returns_project_docs_not_emissions(self):
        """Ensure facility project questions surface reduction projects instead of emission snippets."""
        ReductionProject.objects.create(
            facility=self.facility_b,
            name="Solar Chiller Upgrade",
            description="Cut cold-chain energy demand",
            expected_reduction_tco2e=Decimal("42.5000"),
            actual_reduction_tco2e=Decimal("18.7500"),
        )

        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "What reduction projects are available for South Plant?",
                "organization_id": self.organization.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertEqual(response.data["tool_output"]["tool"], "rag")
        self.assertIn("Reduction projects available for South Plant", response.data["answer"])
        self.assertIn("Solar Chiller Upgrade", response.data["answer"])
        self.assertNotIn("Scope 1 emissions", response.data["answer"])
        self.assertEqual(
            response.data["tool_output"]["documents"][0]["metadata"]["entity"],
            "reduction_project",
        )

    def test_resource_and_transition_snapshot_query_does_not_crash(self):
        """Ensure dashboard snapshot glossary prompts return a response instead of failing inside the snapshot builder."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "Resource and transition snapshot",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertIn("resource and transition snapshot", response.data["answer"].lower())

    def test_latest_reporting_month_question_uses_dashboard_value_answer(self):
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "what is the latest reporting month",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertIn("latest reporting month", response.data["answer"].lower())
        self.assertNotIn("dashboard section", response.data["answer"].lower())

    def test_composite_query_returns_combined_tool_context(self):
        """Ensure explanation-heavy numeric queries return both SQL and RAG context."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "Compare emissions for Dec 23 and Dec 24 and explain why it increased",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
                "reporting_period_id": self.period.id,
            },
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql_rag")
        self.assertIn("sql_result", response.data["tool_output"])
        self.assertIn("rag_result", response.data["tool_output"])

    def test_sql_empty_result_falls_back_to_rag(self):
        """Ensure SQL queries fall back to RAG when SQL returns no rows."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {"query": "compare emissions 2035 vs 2036", "organization_id": self.organization.id},
            format="json",
        )
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertEqual(response.data["tool_output"]["tool"], "rag")

    def test_rag_with_no_documents_returns_out_of_domain_guardrail(self):
        """Ensure vague semantic queries do not drift into random RAG answers."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "tell me something"}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "out_of_domain")
        self.assertIn("CarbonView-related questions", response.data["answer"])

    def test_router_marks_unrelated_chitchat_as_out_of_domain(self):
        """Ensure unrelated conversation is blocked before it reaches SQL or RAG search."""
        decision = QueryRouter().decide("had your lunch")
        self.assertEqual(decision.route, "out_of_domain")
        self.assertFalse(decision.needs_sql)
        self.assertFalse(decision.needs_rag)

    def test_greeting_returns_friendly_guardrail_without_explanation_button(self):
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "hello"}, format="json")
        with patch("apps.rag.views.search") as mock_search, patch("apps.rag.views.sql_tool.execute") as mock_sql, patch(
            "apps.rag.views.generate_answer"
        ) as mock_generate_answer:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "out_of_domain")
        self.assertEqual(response.data["route_reason"], "greeting")
        self.assertIn("What would you like to know?", response.data["answer"])
        self.assertNotIn("[BUTTON:SHOW_EXPLANATION]", response.data["answer"])
        self.assertIsNone(response.data["explanation"])
        self.assertTrue(response.data["tool_output"]["metadata"].get("greeting"))
        mock_search.assert_not_called()
        mock_sql.assert_not_called()
        mock_generate_answer.assert_not_called()

    def test_router_can_use_llm_for_ambiguous_intent_when_enabled(self):
        """Ensure the optional LLM router can override uncertain fallback classification."""
        with patch.dict(os.environ, {"RAG_LLM_INTENT_ROUTING": "true"}):
            with patch.object(
                QueryRouter,
                "_llm_intent_decision",
                return_value=QueryRouter()._build_decision("out_of_domain", "llm_small_talk"),
            ):
                decision = QueryRouter().decide("did u have ur bf?")

        self.assertEqual(decision.route, "out_of_domain")
        self.assertEqual(decision.reason, "llm_small_talk")

    def test_out_of_domain_question_returns_domain_guardrail_answer(self):
        """Ensure unrelated chit-chat does not return random carbon records."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what lunch did you have"}, format="json")
        with patch("apps.rag.views.search") as mock_search, patch("apps.rag.views.sql_tool.execute") as mock_sql:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "out_of_domain")
        self.assertEqual(response.data["route_reason"], "out_of_domain_query")
        self.assertIn("CarbonView-related questions", response.data["answer"])
        mock_search.assert_not_called()
        mock_sql.assert_not_called()

    def test_identity_question_returns_carbonview_assistant_without_search(self):
        """Ensure assistant identity prompts stay out-of-domain and never touch retrieval or SQL."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what is your name"}, format="json")
        with patch("apps.rag.views.search") as mock_search, patch("apps.rag.views.sql_tool.execute") as mock_sql:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "out_of_domain")
        self.assertEqual(response.data["route_reason"], "out_of_domain_query")
        self.assertIn("CarbonView Assistant", response.data["answer"])
        self.assertTrue(response.data["tool_output"]["metadata"].get("identity_question"))
        mock_search.assert_not_called()
        mock_sql.assert_not_called()

    def test_carbonview_definition_query_returns_platform_glossary_answer(self):
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "what is carbon view?"}, format="json")
        response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertEqual(response.data["route_reason"], "definition_query")
        self.assertIn("sustainability intelligence platform", response.data["answer"].lower())
        self.assertEqual(response.data["tool_output"]["documents"][0]["metadata"].get("topic"), "carbonview")
        self.assertNotIn("direct emissions from sources the organization owns or controls", response.data["answer"].lower())

    def test_generate_answer_does_not_mutate_original_tool_result(self):
        from apps.rag.answering import generate_answer

        tool_result = {
            "tool": "rag",
            "route": "rag",
            "documents": [
                {
                    "source": "Glossary: Scope 1",
                    "content": "Scope 1 means direct emissions.",
                    "metadata": {"entity": "glossary", "topic": "scope_1"},
                    "score": 1.2,
                }
            ],
            "metadata": {},
            "fallback_answer": "Scope 1 means direct emissions.",
        }

        answer, provider, enriched = generate_answer("what is scope 1", tool_result)
        self.assertIn("direct emissions", answer.lower())
        self.assertTrue(provider)
        self.assertNotIn("explanation", tool_result)
        self.assertIn("explanation", enriched)

    def test_composite_query_uses_sql_when_rag_search_fails(self):
        """Ensure composite requests degrade gracefully to SQL-only when RAG retrieval fails."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "compare emissions for 2023 vs 2024 and explain why",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        with patch("apps.rag.views.search", side_effect=RuntimeError("search down")):
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "sql")
        self.assertEqual(response.data["tool_output"]["tool"], "sql")

    def test_composite_query_uses_rag_when_sql_fails(self):
        """Ensure composite requests degrade gracefully to RAG-only when SQL fails."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {
                "query": "compare emissions for 2023 vs 2024 and explain why",
                "organization_id": self.organization.id,
                "facility_id": self.facility_a.id,
            },
            format="json",
        )
        with patch("apps.rag.views.sql_tool.execute", side_effect=RuntimeError("sql down")):
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "rag")
        self.assertEqual(response.data["tool_output"]["tool"], "rag")

    def test_both_sql_and_rag_fail_returns_graceful_error(self):
        """Ensure requests return a clean error when both data tools fail."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {"query": "compare emissions for 2023 vs 2024", "organization_id": self.organization.id},
            format="json",
        )
        with patch("apps.rag.views.sql_tool.execute", side_effect=RuntimeError("sql down")), patch(
            "apps.rag.views.search", side_effect=RuntimeError("search down")
        ):
            response = ask_ai(request)
        self.assertEqual(response.status_code, 502)
        self.assertIn("error", response.data)

    def test_chart_endpoint_handles_invalid_input_gracefully(self):
        """Ensure unsupported chart requests return a clear not-found style response."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/chart/", {"query": "show graph of unicorns"}, format="json")
        response = chart_data(request)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_chart_generation_failure_is_graceful(self):
        """Ensure chart endpoint does not crash if chart generation raises unexpectedly."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/chart/", {"query": "show graph of emissions"}, format="json")
        with patch("apps.rag.views.generate_chart_payload", side_effect=RuntimeError("chart down")):
            response = chart_data(request)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_only_one_formatter_call_for_sql_request(self):
        """Ensure each request performs only one final formatting call."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {"query": "compare emissions 2023 vs 2024", "organization_id": self.organization.id, "facility_id": self.facility_a.id},
            format="json",
        )
        with patch("apps.rag.views.generate_answer", return_value=("ok", "test")) as mock_generate_answer:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_generate_answer.call_count, 1)

    def test_sql_request_does_not_trigger_unnecessary_rag_search(self):
        """Ensure direct SQL requests do not call retrieval when SQL already answers them."""
        factory = APIRequestFactory()
        request = factory.post(
            "/api/rag/ask/",
            {"query": "compare emissions 2023 vs 2024", "organization_id": self.organization.id, "facility_id": self.facility_a.id},
            format="json",
        )
        with patch("apps.rag.views.search") as mock_search:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        mock_search.assert_not_called()

    def test_chart_request_avoids_duplicate_sql_calls(self):
        """Ensure chart requests inside ask_ai only execute SQL once."""
        factory = APIRequestFactory()
        request = factory.post("/api/rag/ask/", {"query": "show graph of emissions"}, format="json")
        with patch("apps.rag.views.sql_tool.execute", wraps=rag_views.sql_tool.execute) as mock_sql_execute:
            response = ask_ai(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"], "chart")
        self.assertEqual(mock_sql_execute.call_count, 1)
