import os
import sys

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


def _should_skip_preload() -> bool:
    skip_commands = {"makemigrations", "migrate", "collectstatic", "shell", "dbshell", "createsuperuser", "test"}
    return any(arg in skip_commands for arg in sys.argv[1:])


def _should_preload_rag() -> bool:
    if _should_skip_preload():
        return False
    if os.getenv("RAG_PRELOAD_ON_STARTUP"):
        return os.getenv("RAG_PRELOAD_ON_STARTUP", "").strip().lower() in {"1", "true", "yes", "on"}
    return False


class RagConfig(AppConfig):
    """Django app configuration for the RAG module."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.rag'
    _ready_ran = False

    def ready(self):
        if RagConfig._ready_ran:
            return
        RagConfig._ready_ran = True

        from apps.company.models import Department, Facility, Organization, ReportingPeriod
        from apps.emission.models import AirEmission, EmissionActivity, EmissionBreakdown, EmissionCategory, EmissionFactor, Scope3Category
        from apps.rag.retrieval import initialize_default_retriever, mark_default_retriever_stale
        from apps.shared.models import City, Country, Location, State
        from apps.summary.models import CarbonCredit, EnergySummary, MonthlyEmissionSummary, NeutralityClaim, ReductionProject, WasteSummary, WaterUsage

        tracked_models = (
            AirEmission,
            CarbonCredit,
            City,
            Country,
            Department,
            EmissionActivity,
            EmissionBreakdown,
            EmissionCategory,
            EmissionFactor,
            EnergySummary,
            Facility,
            Location,
            MonthlyEmissionSummary,
            NeutralityClaim,
            Organization,
            ReductionProject,
            ReportingPeriod,
            Scope3Category,
            State,
            WasteSummary,
            WaterUsage,
        )

        def _mark_rag_stale(**kwargs):
            sender = kwargs.get("sender")
            mark_default_retriever_stale(f"{getattr(sender, '__name__', 'model')} change")

        for model in tracked_models:
            post_save.connect(_mark_rag_stale, sender=model, weak=False, dispatch_uid=f"rag_stale_save_{model._meta.label_lower}")
            post_delete.connect(_mark_rag_stale, sender=model, weak=False, dispatch_uid=f"rag_stale_delete_{model._meta.label_lower}")

        if _should_preload_rag():
            try:
                initialize_default_retriever(source="django_startup")
            except Exception:
                from apps.rag.core.common import logger

                logger.exception("RAG startup warmup failed")
