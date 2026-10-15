from django.db import models
from django.conf import settings
from decimal import Decimal
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from apps.shared.models import TimeStampedModel
from apps.company.models import Organization, Facility
from apps.emission.models import ReportingPeriod, EmissionActivity, RecordStatus, EmissionScope, UnitOfMeasure



# Create your models here.
class AuditLog(TimeStampedModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    action = models.CharField(max_length=50)
    message = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="carbon_audit_logs")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Return the action and target identifiers so audit rows are easy to read in admin and logs."""
        return f"{self.action} - {self.content_type} - {self.object_id}"


class CarbonCredit(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="carbon_credits")
    project_name = models.CharField(max_length=200)
    source = models.CharField(max_length=100)
    registry_name = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=200, unique=True)
    vintage_year = models.PositiveIntegerField()
    quantity_tco2e = models.DecimalField(max_digits=18, decimal_places=4)
    purchase_date = models.DateField(null=True, blank=True)
    retirement_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ("purchased", "Purchased"),
        ("retired", "Retired"),
        ("cancelled", "Cancelled"),
    ], default="purchased")

    class Meta:
        ordering = ["-vintage_year", "project_name"]

    def __str__(self):
        """Return the project name with its serial number so each carbon credit is uniquely identifiable."""
        return f"{self.project_name} - {self.serial_number}"


class ReductionProject(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="reduction_projects")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    expected_reduction_tco2e = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    actual_reduction_tco2e = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))

    def __str__(self):
        """Return the reduction-project name for concise labels in admin and related-object fields."""
        return self.name


class NeutralityClaim(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="neutrality_claims")
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="neutrality_claims", null=True, blank=True)
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="neutrality_claims")
    name = models.CharField(max_length=200)
    gross_emissions = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    reductions = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    offsets_retired = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    net_emissions = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.DRAFT)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("organization", "facility", "reporting_period", "name")

    def refresh_totals(self):
        """Recalculate gross, reduction, offset, and net figures by aggregating approved data for the claim scope."""
        activity_qs = EmissionActivity.objects.filter(
            organization=self.organization,
            reporting_period=self.reporting_period,
            status=RecordStatus.APPROVED,
        )
        if self.facility_id:
            activity_qs = activity_qs.filter(facility=self.facility)
            credit_qs = CarbonCredit.objects.filter(facility=self.facility, status="retired")
            reduction_qs = ReductionProject.objects.filter(facility=self.facility)
        else:
            credit_qs = CarbonCredit.objects.filter(facility__organization=self.organization, status="retired")
            reduction_qs = ReductionProject.objects.filter(facility__organization=self.organization)

        gross = activity_qs.aggregate(total=Sum("total_co2e"))["total"] or Decimal("0")
        offsets = credit_qs.aggregate(total=Sum("quantity_tco2e"))["total"] or Decimal("0")
        reductions = reduction_qs.aggregate(total=Sum("actual_reduction_tco2e"))["total"] or Decimal("0")

        self.gross_emissions = gross
        self.reductions = reductions
        self.offsets_retired = offsets
        self.net_emissions = gross - reductions - offsets
        return self.net_emissions

    def save(self, *args, **kwargs):
        """Refresh derived neutrality totals before saving so the stored ledger always matches current source data."""
        self.refresh_totals()
        super().save(*args, **kwargs)

    def __str__(self):
        """Return the claim name so neutrality records display with a simple human-readable label."""
        return self.name


class MonthlyEmissionSummary(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="monthly_summaries")
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="monthly_summaries", null=True, blank=True)
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="monthly_summaries")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    scope = models.CharField(max_length=2, choices=EmissionScope.choices)
    total_co2e = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal("0"))

    class Meta:
        unique_together = ("organization", "facility", "reporting_period", "year", "month", "scope")
        ordering = ["year", "month", "scope"]

    def __str__(self):
        """Return a year-month-scope label so monthly summaries are easy to identify at a glance."""
        return f"{self.organization.name} {self.year}-{self.month:02d} {self.scope}"


class EnergySummary(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="energy_summaries")
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="energy_summaries")
    total_energy = models.DecimalField(max_digits=18, decimal_places=4)
    renewable_energy = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    non_renewable_energy = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="energy_summaries")

    def __str__(self):
        """Return the facility and reporting period to identify each energy summary in admin and exports."""
        return f"Energy summary - {self.facility.name} - {self.reporting_period.name}"


class WaterUsage(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="water_usages")
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="water_usages")
    category = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="water_usages")

    def __str__(self):
        """Return the water category with its facility so water-usage rows stay easy to distinguish."""
        return f"{self.category} - {self.facility.name}"


class WasteSummary(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="waste_summaries")
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="waste_summaries")
    total_waste = models.DecimalField(max_digits=18, decimal_places=4)
    hazardous = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    non_hazardous = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    recycled_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="waste_summaries")

    def __str__(self):
        """Return the facility and reporting period to identify each waste summary record clearly."""
        return f"Waste summary - {self.facility.name} - {self.reporting_period.name}"


class Certificate(TimeStampedModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="certificates/")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Return the certificate name so uploaded files appear with a friendly label in admin and APIs."""
        return self.name


