"""Load the fuel price CSV into the database. Safe to run again: it replaces the data."""

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routing.models import FuelPriceObservation, FuelStation
from routing.services.locations import SUPPORTED_STATES, find_city


class Command(BaseCommand):
    help = "Load fuel stations and prices from the CSV, attaching town coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(settings.FUEL_PRICES_CSV), help="Path to the fuel price CSV.")

    def handle(self, *args, **options):
        path = Path(options["csv"])
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")

        rows_by_station: dict[int, list[dict]] = defaultdict(list)
        skipped_non_us = 0
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row = {key: (value or "").strip() for key, value in row.items()}
                if row["State"] not in SUPPORTED_STATES:
                    skipped_non_us += 1
                    continue
                rows_by_station[int(row["OPIS Truckstop ID"])].append(row)

        stations: list[FuelStation] = []
        observations: list[tuple[int, str, Decimal]] = []
        unlocated: list[str] = []
        for opis_id, rows in rows_by_station.items():
            first = rows[0]
            coordinates = find_city(first["City"], first["State"])
            if coordinates is None:
                unlocated.append(f"{opis_id} {first['City']}, {first['State']}")
                continue
            prices = [Decimal(row["Retail Price"]) for row in rows]
            average = (sum(prices) / len(prices)).quantize(Decimal("0.00001"))
            stations.append(
                FuelStation(
                    opis_id=opis_id,
                    name=first["Truckstop Name"],
                    address=first["Address"],
                    city=first["City"],
                    state=first["State"],
                    rack_id=int(first["Rack ID"]),
                    price=average,
                    latitude=coordinates[0],
                    longitude=coordinates[1],
                )
            )
            observations.extend((opis_id, row["Truckstop Name"], Decimal(row["Retail Price"])) for row in rows)

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)
            pk_by_opis = dict(FuelStation.objects.values_list("opis_id", "pk"))
            FuelPriceObservation.objects.bulk_create(
                [
                    FuelPriceObservation(station_id=pk_by_opis[opis_id], reported_name=name, price=price)
                    for opis_id, name, price in observations
                ],
                batch_size=1000,
            )
        cache.clear()  # cached plans were built from the old prices

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} stations and {len(observations)} price rows "
                f"({skipped_non_us} non-US rows skipped)."
            )
        )
        if unlocated:
            self.stdout.write(self.style.WARNING(f"{len(unlocated)} stations had no matching town and were skipped:"))
            for line in unlocated:
                self.stdout.write(f"  {line}")
