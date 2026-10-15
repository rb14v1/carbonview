from django.db.models import Sum
from apps.emission.models import EmissionActivity, EmissionBreakdown, RecordStatus


def generate_breakdown(org, period, facility=None):
    """Rebuild aggregate emission-breakdown rows by grouping approved activities for the chosen org, period, and facility."""
    qs = EmissionActivity.objects.filter(
        organization=org,
        reporting_period=period,
        status=RecordStatus.APPROVED
    )

    if facility:
        qs = qs.filter(facility=facility)

    breakdowns = qs.values(
        "category",
        "category__parent",
        "category__category_type",
        "category__code",
        "scope3_category"
    ).annotate(
        total_co2e=Sum("total_co2e"),
        total_quantity=Sum("quantity")
    )

    # Delete old
    EmissionBreakdown.objects.filter(
        organization=org,
        reporting_period=period,
        facility=facility
    ).delete()

    objs = []

    for row in breakdowns:
        category_id = row["category"]
        parent_id = row["category__parent"]

        # -----------------------------------------
        # ✅ FIX: ALWAYS ENSURE CATEGORY IS NOT NULL
        # -----------------------------------------

        if parent_id:
            # Normal case → category = parent
            category = parent_id
            subcategory = category_id
        else:
            # Top-level category (like S2)
            category = category_id
            subcategory = None

        # Extract scope safely (S1, S2, S3)
        scope = row["category__code"].split("-")[0]

        objs.append(
            EmissionBreakdown(
                organization=org,
                facility=facility,
                reporting_period=period,

                scope=scope,
                category_id=category,        # ✅ NEVER NULL NOW
                subcategory_id=subcategory,  # optional
                scope3_category_id=row["scope3_category"],

                total_co2e=row["total_co2e"] or 0,
                total_quantity=row["total_quantity"] or 0,
            )
        )

    EmissionBreakdown.objects.bulk_create(objs)
