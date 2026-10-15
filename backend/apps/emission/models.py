from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from apps.shared.models import TimeStampedModel, Country
from apps.company.models import Organization, Facility, Department, ReportingPeriod

# Create your models here.
class EmissionScope(models.TextChoices):
    SCOPE_1 = "S1", "Scope 1"
    SCOPE_2 = "S2", "Scope 2"
    SCOPE_3 = "S3", "Scope 3"


class Scope2Method(models.TextChoices):
    LOCATION_BASED = "location_based", "Location based"
    MARKET_BASED = "market_based", "Market based"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class ActivityDataQuality(models.TextChoices):
    ACTUAL = "actual", "Actual"
    ESTIMATED = "estimated", "Estimated"
    SPEND_BASED = "spend_based", "Spend based"
    SUPPLIER_SPECIFIC = "supplier_specific", "Supplier specific"


class RecordStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


# class EmissionCategory(TimeStampedModel):
#     code = models.CharField(max_length=30, unique=True)
#     name = models.CharField(max_length=100)
#     scope = models.CharField(max_length=2, choices=EmissionScope.choices)
#     description = models.TextField(blank=True)

#     class Meta:
#         ordering = ["scope", "name"]

#     def __str__(self):
#         return f"{self.name} ({self.get_scope_display()})"

class EmissionCategory(TimeStampedModel):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=2, choices=EmissionScope.choices)

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcategories"
    )

    CATEGORY_TYPE_CHOICES = [
        ("scope", "Scope Level"),
        ("category", "Category Level"),
        ("subcategory", "Subcategory Level"),
    ]
    category_type = models.CharField(
        max_length=20,
        choices=CATEGORY_TYPE_CHOICES,
        default="category"
    )

    scope3_category_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    description = models.TextField(blank=True)

    class Meta:
        ordering = ["scope", "code"]

    def __str__(self):
        """Return the category name with its scope code so category records stay readable across admin and APIs."""
        return f"{self.name} ({self.scope})"
    
    def clean(self):
        """Enforce the category hierarchy by checking allowed parent types and matching scope inheritance."""
        # Scope level should not have parent
        if self.category_type == "scope" and self.parent:
            raise ValidationError("Scope level cannot have a parent")

        # Category must have scope parent
        if self.category_type == "category":
            if not self.parent or self.parent.category_type != "scope":
                raise ValidationError("Category must have a scope as parent")

        # Subcategory must have category parent
        if self.category_type == "subcategory":
            if not self.parent or self.parent.category_type != "category":
                raise ValidationError("Subcategory must have a category as parent")

        # Scope consistency
        if self.parent and self.scope != self.parent.scope:
            raise ValidationError("Child must have same scope as parent")


class Scope3Category(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        """Return the Scope 3 code and name so value-chain categories display with both identifiers."""
        return f"{self.code} - {self.name}"


class UnitOfMeasure(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code
    
class GasType(TimeStampedModel):
    code = models.CharField(max_length=10, unique=True)
    gas_name = models.CharField(max_length=50)
    gwp_value = models.DecimalField(max_digits=12, decimal_places=6)
    gwp_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        """Return the gas code so factors and calculations render with a short recognizable identifier."""
        return self.code

class FuelType(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True)  # e.g., DIESEL, PETROL
    description = models.TextField(blank=True)

    default_unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="fuel_types"
    )
    
    def __str__(self):
        """Return the unit code for concise labels in selectors, related objects, and admin tables."""
        return self.code


class EmissionFactorSource(TimeStampedModel):
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=100)
    publisher = models.CharField(max_length=200, blank=True)
    published_on = models.DateField(null=True, blank=True)
    reference_url = models.URLField(blank=True, null=True)

    class Meta:
        unique_together = ("name", "version")
        ordering = ["name", "version"]

    def __str__(self):
        """Return the source name and version so factor sources are clearly differentiated in admin and APIs."""
        return f"{self.name} {self.version}"


class EmissionFactor(TimeStampedModel):
    source = models.ForeignKey(EmissionFactorSource, on_delete=models.PROTECT, related_name="factors")
    category = models.ForeignKey(EmissionCategory, on_delete=models.PROTECT, related_name="factors")
    scope3_category = models.ForeignKey(Scope3Category, on_delete=models.PROTECT, null=True, blank=True, related_name="factors")
    gas_type = models.ForeignKey(GasType, on_delete=models.PROTECT, related_name="emission_factors")
    fuel_type = models.ForeignKey(FuelType,on_delete=models.PROTECT,null=True,blank=True,related_name="emission_factors")
    factor_code = models.CharField(max_length=100)
    factor_name = models.CharField(max_length=150)
    factor_value = models.DecimalField(max_digits=18, decimal_places=8)
    activity_unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="activity_factors")
    factor_unit = models.CharField(max_length=100, default="kg gas/unit")
    geography = models.ForeignKey(Country, on_delete=models.PROTECT, null=True, blank=True, related_name="emission_factors")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = (
            "source",
            "category",
            "scope3_category",
            "gas_type",
            "factor_code",
            "activity_unit",
            "geography",
            "valid_from",
        )
        indexes = [
            models.Index(fields=["factor_code", "valid_from"]),
            models.Index(fields=["category", "geography"]),
            models.Index(fields=["factor_code", "category", "activity_unit"])
        ]

    def clean(self):
        """Validate that factor validity dates are chronological before the factor can be saved."""
        if self.valid_to and self.valid_from > self.valid_to:
            raise ValidationError("valid_from must be earlier than valid_to")

    def __str__(self):
        """Return the factor code with gas type so factor rows stay identifiable when codes are reused across gases."""
        return f"{self.factor_code} - {self.gas_type.code}"


class EmissionActivity(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="emission_activities")
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="emission_activities")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="emission_activities")
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="emission_activities")
    category = models.ForeignKey(EmissionCategory, on_delete=models.PROTECT, related_name="activities")
    scope3_category = models.ForeignKey(Scope3Category, on_delete=models.PROTECT, null=True, blank=True, related_name="activities")

    activity_name = models.CharField(max_length=150)
    activity_date = models.DateField()
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="activities")
    factor_code = models.CharField(max_length=100)
    scope2_method = models.CharField(max_length=20, choices=Scope2Method.choices, default=Scope2Method.NOT_APPLICABLE)
    data_quality = models.CharField(max_length=20, choices=ActivityDataQuality.choices, default=ActivityDataQuality.ACTUAL)
    fuel_type = models.ForeignKey(FuelType,on_delete=models.PROTECT,null=True,blank=True,related_name="activities")
    supplier_name = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    total_co2e = models.DecimalField(max_digits=30, decimal_places=6, default=Decimal("0"))
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.DRAFT)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entered_emission_activities")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_emission_activities")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-activity_date", "-id"]
        indexes = [
        models.Index(fields=['organization', 'reporting_period', 'status']),
        models.Index(fields=['facility', 'category', 'activity_date']),
        models.Index(fields=['factor_code', 'activity_date']),
    ]
    

    def clean(self):
        """Validate organization ownership, scope-specific fields, and reporting-period boundaries for each activity."""
        if self.facility.organization_id != self.organization_id:
            raise ValidationError("Facility must belong to the selected organization")
        if self.reporting_period.organization_id != self.organization_id:
            raise ValidationError("Reporting period must belong to the selected organization")
        if self.category.scope != EmissionScope.SCOPE_3 and self.scope3_category_id:
            raise ValidationError("Scope 3 category is allowed only for Scope 3 activities")
        if self.category.scope == EmissionScope.SCOPE_3 and not self.scope3_category_id:
            raise ValidationError("Scope 3 activities require a Scope 3 category")
        if self.category.scope != EmissionScope.SCOPE_2 and self.scope2_method != Scope2Method.NOT_APPLICABLE:
            raise ValidationError("Scope 2 methodology is only valid for Scope 2 activities")
        if self.category.scope == EmissionScope.SCOPE_2 and self.scope2_method == Scope2Method.NOT_APPLICABLE:
            raise ValidationError("Scope 2 activities must set a Scope 2 methodology")
        if self.activity_date < self.reporting_period.start_date or self.activity_date > self.reporting_period.end_date:
            raise ValidationError("activity_date must fall inside the reporting period")

    def __str__(self):
        """Return the activity name with its date so approved records are easy to identify in lists and admin."""
        return f"{self.activity_name} - {self.activity_date}"

    # @transaction.atomic
    # def recalculate_emissions(self):
    #     factor_filters = {
    #         "category": self.category,
    #         "factor_code": self.factor_code,
    #         "activity_unit": self.unit,
    #         "is_active": True,
    #     }
    #     if self.scope3_category_id:
    #         factor_filters["scope3_category"] = self.scope3_category

    #     country = self.facility.location.country if self.facility_id else None
    #     factors = EmissionFactor.objects.filter(**factor_filters).filter(
    #         models.Q(geography=country) | models.Q(geography__isnull=True)
    #     ).order_by("-geography_id", "-valid_from")

    #     self.calculations.all().delete()
    #     total = Decimal("0")

    #     for factor in factors:
    #         gas_amount = self.quantity * factor.factor_value
    #         co2e_amount = gas_amount * factor.gas_type.gwp_value
    #         EmissionCalculation.objects.create(
    #             activity=self,
    #             factor=factor,
    #             gas_type=factor.gas_type,
    #             activity_quantity=self.quantity,
    #             factor_value=factor.factor_value,
    #             gas_amount=gas_amount,
    #             co2e_amount=co2e_amount,
    #         )
    #         total += co2e_amount

    #     self.total_co2e = total
    #     EmissionActivity.objects.filter(pk=self.pk).update(total_co2e=total, updated_at=timezone.now())
    #     self.total_co2e = total
    #     return total

    @transaction.atomic
    def recalculate_emissions(self):
        """Rebuild per-gas calculations from matching factors and store the summed CO2e total for the activity date."""
        factor_filters = {
            "category": self.category,
            # "factor_code": self.factor_code,
            "activity_unit": self.unit,
            "is_active": True,
        }

        if self.fuel_type:
            factor_filters["fuel_type"] = self.fuel_type

        if self.scope3_category_id:
            factor_filters["scope3_category"] = self.scope3_category

        country = self.facility.location.country if self.facility_id else None

        factors = EmissionFactor.objects.filter(**factor_filters).filter(
            models.Q(geography=country) | models.Q(geography__isnull=True)
        ).filter(
            valid_from__lte=self.activity_date
        ).filter(
            models.Q(valid_to__gte=self.activity_date) | models.Q(valid_to__isnull=True)
        ).order_by("-geography_id", "-valid_from")

        self.calculations.all().delete()

        total = Decimal("0")

        for factor in factors:
            # Quantize intermediate values to match EmissionCalculation field precision (8 decimals)
            gas_amount = (self.quantity * factor.factor_value).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
            co2e_amount = (gas_amount * factor.gas_type.gwp_value).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

            EmissionCalculation.objects.create(
                activity=self,
                factor=factor,
                gas_type=factor.gas_type,
                activity_quantity=self.quantity,
                factor_value=factor.factor_value,
                gas_amount=gas_amount,
                co2e_amount=co2e_amount,
            )

            total += co2e_amount

        # Quantize total to match `total_co2e` field (6 decimals)
        total = total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        self.total_co2e = total
        return self.total_co2e

    # @transaction.atomic
    # def save(self, *args, **kwargs):
    #     is_new = self.pk is None
    #     super().save(*args, **kwargs)
    #     self.recalculate_emissions()
    #     if not is_new:
    #         super().save(update_fields=["updated_at"])
    # def save(self, *args, **kwargs):
    #     super().save(*args, **kwargs)
    #     self.recalculate_emissions()

    #     EmissionActivity.objects.filter(pk=self.pk).update(
    #         total_co2e=self.total_co2e,
    #         updated_at=timezone.now()
        # )
    @transaction.atomic
    def save(self, *args, **kwargs):
        """Persist the activity first, then recalculate and save total CO2e when the record is new or flagged for recompute."""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new or self._needs_recalc:  # Add flag
            self.total_co2e = self.recalculate_emissions()
            super().save(update_fields=['total_co2e', 'updated_at'])
    
    def get_category_hierarchy(self):
        """Return the parent category and subcategory pair so breakdown builders can group activities consistently."""
        parent = self.category.parent
        if parent:
            return parent, self.category
        return self.category, None


class EmissionCalculation(TimeStampedModel):
    activity = models.ForeignKey(EmissionActivity, on_delete=models.CASCADE, related_name="calculations")
    factor = models.ForeignKey(EmissionFactor, on_delete=models.PROTECT, related_name="calculations")
    gas_type = models.ForeignKey(GasType, on_delete=models.PROTECT, related_name="calculations")
    activity_quantity = models.DecimalField(max_digits=18, decimal_places=6)
    factor_value = models.DecimalField(max_digits=18, decimal_places=8)
    gas_amount = models.DecimalField(max_digits=18, decimal_places=8)
    co2e_amount = models.DecimalField(max_digits=18, decimal_places=8)

    class Meta:
        unique_together = ("activity", "factor", "gas_type")
        

    def __str__(self):
        """Return the activity id and gas code so calculation rows are easy to trace back to their source activity."""
        return f"{self.activity_id} - {self.gas_type.code}"

class DataEvidence(TimeStampedModel):
    activity = models.ForeignKey(EmissionActivity, on_delete=models.CASCADE, related_name="evidences")
    name = models.CharField(max_length=200)
    file_url = models.URLField(blank=True, null=True)
    document_number = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_evidences",
        null=True,
        blank=True,
    )

    def __str__(self):
        """Return the evidence name so uploaded supporting documents display with a simple readable label."""
        return self.name


class AirEmission(TimeStampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name="air_emissions")
    reporting_period = models.ForeignKey(ReportingPeriod, on_delete=models.CASCADE, related_name="air_emissions")
    pollutant_type = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="air_emissions")

    def __str__(self):
        """Return the pollutant and facility names so air-emission rows remain understandable in admin and exports."""
        return f"{self.pollutant_type} - {self.facility.name}"
    
class EmissionBreakdown(TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="emission_breakdowns"
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, null=True, blank=True,
        related_name="emission_breakdowns"
    )
    reporting_period = models.ForeignKey(
        ReportingPeriod, on_delete=models.CASCADE,
        related_name="emission_breakdowns"
    )

    # Breakdown hierarchy
    scope = models.CharField(max_length=100, choices=EmissionScope.choices)
    category = models.ForeignKey(
        EmissionCategory, on_delete=models.CASCADE,
        related_name="breakdowns"
    )
    subcategory = models.ForeignKey(
        EmissionCategory, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="subcategory_breakdowns"
    )
    fuel_type = models.ForeignKey(FuelType,on_delete=models.CASCADE,null=True,blank=True)
    
    scope3_category = models.ForeignKey(
        Scope3Category, on_delete=models.CASCADE,
        null=True, blank=True
    )

    gas_type = models.ForeignKey(
        GasType, on_delete=models.CASCADE,
        null=True, blank=True
    )

    # Aggregated values
    total_co2e = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    total_quantity = models.DecimalField(max_digits=18, decimal_places=6, default=0)

    class Meta:
        unique_together = (
            "organization",
            "facility",
            "reporting_period",
            "scope",
            "category",
            "subcategory",
            "scope3_category",
            "gas_type",
            "fuel_type"
        )
    def clean(self):
        """Validate that breakdown rows use a category node plus an optional subcategory node of the correct types."""
        if self.subcategory and self.subcategory.category_type != "subcategory":
            raise ValidationError("subcategory must be of type 'subcategory'")

        if self.category.category_type != "category":
            raise ValidationError("category must be of type 'category'")
