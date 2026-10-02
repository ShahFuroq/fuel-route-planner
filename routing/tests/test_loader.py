import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from routing.models import FuelPriceObservation, FuelStation

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
128,THE EFFINGHAM CHROME SHOP,"I-57 & I-70, EXIT 159",Effingham                               ,IL,510,3.399
128,THE EFFINGHAM CHROME SHOP,"I-57 & I-70, EXIT 159",Effingham                               ,IL,510,3.349
128,THE EFFINGHAM CHROME SHOP,"I-57 & I-70, EXIT 159",Effingham                               ,IL,510,3.549
7,WOODSHED OF BIG CABIN,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,3.00733333
629,FLYING J #850,TCH-16,Edmonton,AB,80,4.39948962
99999,NOWHERE FUEL,US-1,Zzyzx Nonexistent Town,TX,1,3.000
"""


class LoadFuelStationsTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "prices.csv"
        self.path.write_text(CSV, encoding="utf-8")

    def load(self) -> str:
        out = StringIO()
        call_command("load_fuel_stations", csv=str(self.path), stdout=out)
        return out.getvalue()

    def test_loads_us_stations_and_skips_canadian_rows(self):
        output = self.load()
        self.assertEqual(set(FuelStation.objects.values_list("opis_id", flat=True)), {128, 7})
        self.assertIn("1 non-US rows skipped", output)

    def test_duplicate_rows_are_kept_and_averaged(self):
        self.load()
        station = FuelStation.objects.get(opis_id=128)
        self.assertEqual(station.price, Decimal("3.43233"))
        self.assertEqual(station.observations.count(), 3)
        self.assertEqual(FuelPriceObservation.objects.count(), 4)

    def test_whitespace_is_trimmed_and_coordinates_attached(self):
        self.load()
        station = FuelStation.objects.get(opis_id=128)
        self.assertEqual(station.city, "Effingham")
        self.assertAlmostEqual(station.latitude, 39.12, delta=0.2)
        self.assertAlmostEqual(station.longitude, -88.55, delta=0.2)

    def test_stations_without_a_known_town_are_reported_not_loaded(self):
        output = self.load()
        self.assertIn("99999 Zzyzx Nonexistent Town, TX", output)
        self.assertFalse(FuelStation.objects.filter(opis_id=99999).exists())

    def test_running_twice_does_not_duplicate_data(self):
        self.load()
        self.load()
        self.assertEqual(FuelStation.objects.count(), 2)
        self.assertEqual(FuelPriceObservation.objects.count(), 4)
