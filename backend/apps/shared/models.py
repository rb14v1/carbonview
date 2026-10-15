from django.db import models

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Resource(TimeStampedModel):
    name = models.CharField(max_length=200, blank=True)
    url = models.URLField(blank=True, null=True)
    description = models.TextField(blank=True)

    def __str__(self):
        """Return the most descriptive available label so resources are easy to identify in admin and serializers."""
        return self.name or self.url or "Resource"

class Country(models.Model):
    code = models.CharField(max_length=2, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        """Return the country name for human-readable dropdowns, relations, and admin lists."""
        return self.name


class State(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="states")
    code = models.CharField(max_length=10, blank=True)
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("country", "name")
        ordering = ["country__name", "name"]

    def __str__(self):
        """Return the state name with its country code to distinguish duplicate state names across countries."""
        return f"{self.name}, {self.country.code}"


class City(models.Model):
    state = models.ForeignKey(State, on_delete=models.CASCADE, related_name="cities")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("state", "name")
        ordering = ["state__name", "name"]

    def __str__(self):
        """Return the city with its parent state so location references stay clear in the UI and admin."""
        return f"{self.name}, {self.state.name}"


class Location(TimeStampedModel):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="locations")
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="locations", null=True, blank=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="locations", null=True, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        """Build a compact address label by joining the street, city, and country fields that are present."""
        parts = [self.street_address, self.city.name if self.city else "", self.country.name]
        return ", ".join([p for p in parts if p])

