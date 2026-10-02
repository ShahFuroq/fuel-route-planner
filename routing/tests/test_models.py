from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from routing.models import FuelStation


def station(**overrides) -> FuelStation:
    values = {
        "opis_id": 1,
        "name": "Test",
        "address": "I-40",
        "city": "Amarillo",
        "state": "TX",
        "rack_id": 1,
        "price": Decimal("3.000"),
        "latitude": 35.2,
        "longitude": -101.8,
    }
    return FuelStation(**{**values, **overrides})


class FuelStationConstraintTests(TestCase):
    def test_a_valid_station_saves(self):
        station().save()
        self.assertEqual(FuelStation.objects.count(), 1)

    def test_price_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            station(price=Decimal("0")).save()

    def test_coordinates_must_be_on_the_globe(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            station(latitude=135.0).save()

    def test_opis_id_is_unique(self):
        station().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            station(name="Copy").save()
