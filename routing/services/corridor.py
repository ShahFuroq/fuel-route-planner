"""Find fuel stations near a route, using a grid index held in memory."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from routing.models import FuelStation
from routing.services.geometry import Point, haversine_miles

CELL_DEGREES = 0.25  # about 17 miles north-south; wider than the widest corridor
SAMPLE_EVERY_MILES = 1.0


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
    def __init__(self, stations: list[Station]):
        self.stations = stations
        self.grid: dict[tuple[int, int], list[Station]] = defaultdict(list)
        for station in stations:
            self.grid[self._cell(station.latitude, station.longitude)].append(station)

    @staticmethod
    def _cell(lat: float, lng: float) -> tuple[int, int]:
        return int(lat // CELL_DEGREES), int(lng // CELL_DEGREES)

    def starting_station(self, lat: float, lng: float, radius_miles: float) -> tuple[Station, float]:
        """Where a trip with an empty tank fills up first, with its distance in miles.

        The cheapest station within radius_miles of the point; if there is none
        that close, the nearest station.
        """
        distances = [(haversine_miles(lat, lng, s.latitude, s.longitude), s) for s in self.stations]
        nearby = [(distance, s) for distance, s in distances if distance <= radius_miles]
        if nearby:
            distance, station = min(nearby, key=lambda pair: (pair[1].price, pair[0]))
        else:
            distance, station = min(distances, key=lambda pair: pair[0])
        return station, distance

    def along_route(self, points: list[Point], markers: list[float], width_miles: float) -> list[RouteStation]:
        """Stations within width_miles of the route, ordered by position along it."""
        best: dict[int, RouteStation] = {}
        last_sampled = -SAMPLE_EVERY_MILES
        for (lat, lng), mile in zip(points, markers):
            if mile - last_sampled < SAMPLE_EVERY_MILES and mile != markers[-1]:
                continue
            last_sampled = mile
            cell_x, cell_y = self._cell(lat, lng)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for station in self.grid.get((cell_x + dx, cell_y + dy), ()):
                        offset = haversine_miles(lat, lng, station.latitude, station.longitude)
                        if offset > width_miles:
                            continue
                        current = best.get(station.opis_id)
                        if current is None or offset < current.offset_miles:
                            best[station.opis_id] = RouteStation(station, mile, offset)
        return sorted(best.values(), key=lambda found: found.mile)


@lru_cache(maxsize=1)
def station_index() -> StationIndex:
    """Build the index from the database on first use, once per process."""
    stations = [
        Station(*row)
        for row in FuelStation.objects.values_list(
            "opis_id", "name", "address", "city", "state", "price", "latitude", "longitude"
        )
    ]
    return StationIndex(stations)
