from django.db import models


class FuelStation(models.Model):
    """One truck stop, with the price the planner uses and its approximate position."""

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()
    # Average of this station's price rows in the source file (dollars per gallon).
    price = models.DecimalField(max_digits=8, decimal_places=5)
    # Centre of the station's town; the source file has no coordinates.
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        # No lookup indexes beyond the unique opis_id: the planner reads every
        # station once per process and searches them in memory.
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="fuel_station_price_positive"),
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
                name="fuel_station_coordinates_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"


class FuelPriceObservation(models.Model):
    """A raw price row from the source file. Some stations have several."""

    station = models.ForeignKey(FuelStation, on_delete=models.CASCADE, related_name="observations")
    reported_name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=8)

    def __str__(self) -> str:
        return f"{self.station.opis_id}: {self.price}"
