from django.db import models
from django.core.exceptions import ValidationError
from apps.shared.models import Resource, TimeStampedModel,Location

class OrganizationBoundary(models.TextChoices):
    OPERATIONAL_CONTROL = "operational_control", "Operational control"
    FINANCIAL_CONTROL = "financial_control", "Financial control"
    EQUITY_SHARE = "equity_share", "Equity share"


class IndustryType(models.TextChoices):
    TECHNOLOGY = "technology", "Technology"
    FINANCE = "finance", "Finance"
    HEALTHCARE = "healthcare", "Healthcare"
    EDUCATION = "education", "Education"
    MANUFACTURING = "manufacturing", "Manufacturing"
    RETAIL = "retail", "Retail"
    ENERGY = "energy", "Energy"
    LOGISTICS = "logistics", "Logistics"
    OTHER = "other", "Other"

class Organization(TimeStampedModel):
    name = models.CharField(max_length=200, unique=True)
    legal_name = models.CharField(max_length=255, blank=True)
    industry_type = models.CharField(max_length=50, choices=IndustryType.choices, default=IndustryType.OTHER)
    reporting_boundary = models.CharField(max_length=30, choices=OrganizationBoundary.choices, default=OrganizationBoundary.OPERATIONAL_CONTROL)
    base_currency = models.CharField(max_length=3, default="USD")
    base_year = models.PositiveIntegerField(null=True, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.SET_NULL, null=True, blank=True, related_name="organizations")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        """Return the organization name so related records render with the business label users expect."""
        return self.name
    
class Facility(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="facilities")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="facilities")
    facility_code = models.CharField(max_length=50, blank=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_carbon_neutral = models.BooleanField(default=False)

    class Meta:
        unique_together = ("organization", "name")
        ordering = ["organization__name", "name"]

    def __str__(self):
        """Return the facility and organization names together to keep facility choices unique in admin and APIs."""
        return f"{self.name} - {self.organization.name}"
    
class Department(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("facility", "name")
        ordering = ["facility__name", "name"]

    def __str__(self):
        """Return the department with its facility name so department labels stay unambiguous across sites."""
        return f"{self.name} - {self.facility.name}"
    
class ReportingPeriod(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="reporting_periods")
    name = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("organization", "year", "name")
        ordering = ["-year", "-start_date"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lt=models.F("end_date")),
                name="valid_reporting_period_dates"
            )
        ]

    def clean(self):
        """Validate reporting dates by rejecting reversed ranges and overlaps within the same organization."""
        if self.start_date >= self.end_date:
            raise ValidationError("start_date must be earlier than end_date")

        overlapping = ReportingPeriod.objects.filter(
            organization=self.organization,
            start_date__lte=self.end_date,
            end_date__gte=self.start_date
        ).exclude(pk=self.pk)

        if overlapping.exists():
            raise ValidationError("Overlapping reporting periods not allowed")
    
    def __str__(self):
        """Return the organization and reporting-period name to keep period references readable everywhere."""
        return f"{self.organization.name} - {self.name}"
