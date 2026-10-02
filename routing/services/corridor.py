"""Find fuel stations near a route, using a grid index held in memory."""

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from routing.models import FuelStation
from routing.services.geometry import Point, haversine_miles

CELL_DEGREES = 0.25
MILES_PER_DEGREE_LATITUDE = 69.0
SAMPLE_EVERY_MILES = 1.0

STATION_FIELDS = ("opis_id", "name", "address", "city", "state", "price", "latitude", "longitude")


class StationsNotLoaded(Exception):
    """The station table is empty; the load command has not been run."""


@dataclass(frozen=True)
class Station:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price: Decimal
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RouteStation:
    station: Station
    mile: float  # distance along the route to the closest point
    offset_miles: float  # straight-line distance from the route


class StationIndex:
    """Stations bucketed into a latitude/longitude grid for fast nearby lookups."""

    def __init__(self, stations: list[Station]):
        self.stations = stations
        self.grid: dict[tuple[int, int], list[Station]] = defaultdict(list)
        for station in stations:
            self.grid[self._cell(station.latitude, station.longitude)].append(station)

    @staticmethod
    def _cell(lat: float, lng: float) -> tuple[int, int]:
        return int(lat // CELL_DEGREES), int(lng // CELL_DEGREES)

    @staticmethod
    def _cell_reach(lat: float, radius_miles: float) -> tuple[int, int]:
        """How many cells to look in each direction to cover radius_miles.

        A degree of longitude shrinks towards the poles, so the east-west reach
        depends on the latitude.
        """
        cell_height = CELL_DEGREES * MILES_PER_DEGREE_LATITUDE
        cell_width = cell_height * math.cos(math.radians(lat))
        return math.ceil(radius_miles / cell_height), math.ceil(radius_miles / cell_width)

    def within(self, lat: float, lng: float, radius_miles: float) -> list[tuple[Station, float]]:
        """Stations within radius_miles of a point, each with its distance."""
        lat_cell, lng_cell = self._cell(lat, lng)
        lat_reach, lng_reach = self._cell_reach(lat, radius_miles)
        found = []
        for d_lat in range(-lat_reach, lat_reach + 1):
            for d_lng in range(-lng_reach, lng_reach + 1):
                for station in self.grid.get((lat_cell + d_lat, lng_cell + d_lng), ()):
                    distance = haversine_miles(lat, lng, station.latitude, station.longitude)
                    if distance <= radius_miles:
                        found.append((station, distance))
        return found

    def starting_station(self, lat: float, lng: float, radius_miles: float) -> tuple[Station, float]:
        """Where a trip with an empty tank fills up first, with its distance in miles.

        The cheapest station within radius_miles of the point; if there is none
        that close, the nearest station.
        """
        nearby = self.within(lat, lng, radius_miles)
        if nearby:
            return min(nearby, key=lambda pair: (pair[0].price, pair[1]))
        nearest = min(self.stations, key=lambda s: haversine_miles(lat, lng, s.latitude, s.longitude))
        return nearest, haversine_miles(lat, lng, nearest.latitude, nearest.longitude)

    def along_route(self, points: list[Point], markers: list[float], width_miles: float) -> list[RouteStation]:
        """Stations within width_miles of the route, ordered by position along it."""
        best: dict[int, RouteStation] = {}
        last_sampled = -SAMPLE_EVERY_MILES
        final_mile = markers[-1]
        for (lat, lng), mile in zip(points, markers, strict=True):
            if mile - last_sampled < SAMPLE_EVERY_MILES and mile != final_mile:
                continue
            last_sampled = mile
            for station, offset in self.within(lat, lng, width_miles):
                current = best.get(station.opis_id)
                if current is None or offset < current.offset_miles:
                    best[station.opis_id] = RouteStation(station, mile, offset)
        return sorted(best.values(), key=lambda found: found.mile)


@lru_cache(maxsize=1)
def station_index() -> StationIndex:
    """Build the index from the database on first use, once per process."""
    stations = [Station(**row) for row in FuelStation.objects.values(*STATION_FIELDS)]
    if not stations:
        station_index.cache_clear()  # do not remember an empty table
        raise StationsNotLoaded("No fuel stations are loaded. Run: python manage.py load_fuel_stations")
    return StationIndex(stations)
