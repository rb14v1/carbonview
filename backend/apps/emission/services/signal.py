from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.emission.models import EmissionActivity, RecordStatus
from apps.emission.services.breakdown_services import generate_breakdown

@receiver(post_save, sender=EmissionActivity)
def update_breakdown(sender, instance, **kwargs):
    """Regenerate emission breakdowns after an activity save so dashboard aggregates stay aligned with activity data."""
    # if instance.status == RecordStatus.APPROVED:
    generate_breakdown(
            org=instance.organization,
            period=instance.reporting_period,
            facility=instance.facility
        )
