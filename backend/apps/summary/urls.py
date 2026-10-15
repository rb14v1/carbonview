from django.urls import include, path
from rest_framework.routers import DefaultRouter
from apps.summary.dashboard_views import DashboardViewSet
from .views import (
    AuditLogViewSet,
    CarbonCreditViewSet,
    CertificateViewSet,
    EnergySummaryViewSet,
    MonthlyEmissionSummaryViewSet,
    NeutralityClaimViewSet,
    ReductionProjectViewSet,
    WasteSummaryViewSet,
    WaterUsageViewSet,
    ESGReportExcelView,
)


router = DefaultRouter()
router.register(r"audit-logs", AuditLogViewSet)
router.register(r"certificates", CertificateViewSet)
router.register(r"carbon-credits", CarbonCreditViewSet)
router.register(r"reduction-projects", ReductionProjectViewSet)
router.register(r"neutrality-claims", NeutralityClaimViewSet)
router.register(r"monthly-emission-summaries", MonthlyEmissionSummaryViewSet)
router.register(r"energy-summaries", EnergySummaryViewSet)
router.register(r"water-usages", WaterUsageViewSet)
router.register(r"waste-summaries", WasteSummaryViewSet)
router.register(r"dashboard-summaries",  DashboardViewSet,basename="dashboard-summaries")


app_name = "summary"

urlpatterns = [
    path("", include(router.urls)),
    path("esg-report/", ESGReportExcelView.as_view())
    
]
