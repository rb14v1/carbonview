from django.apps import AppConfig


class EmissionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.emission'

    def ready(self):
        """Import signal handlers during app startup so emission saves automatically refresh aggregate breakdowns."""
        import apps.emission.services.signal  
