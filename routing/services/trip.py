"""The result of planning a trip, independent of how it is presented."""

from dataclasses import dataclass
from decimal import Decimal

from routing.services.corridor import Station
from routing.services.geometry import Point
from routing.services.locations import Location


@dataclass(frozen=True)
class FuelStop:
    order: int
    station: Station
    mile: float  # distance along the route
    offset_miles: float  # distance of the station from the route
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True)
class TripPlan:
    start: Location
    finish: Location
    distance_miles: float
    duration_hours: float
    stops: tuple[FuelStop, ...]
    route_points: tuple[Point, ...]  # thinned for display
    mpg: float
    range_miles: float
    stop_penalty: float
    start_fuel_gallons: float
    corridor_miles: float
    # Distance from the start to the first fill-up; None when the tank did not start empty.
    start_station_miles: float | None

    @property
    def total_gallons(self) -> Decimal:
        return sum((stop.gallons for stop in self.stops), Decimal("0"))

    @property
    def total_cost(self) -> Decimal:
        return sum((stop.cost for stop in self.stops), Decimal("0"))

    @property
    def average_price_paid(self) -> Decimal | None:
        gallons = self.total_gallons
        return self.total_cost / gallons if gallons else None

    @property
    def stop_count(self) -> int:
        return len(self.stops)


@dataclass(frozen=True)
class PlanningStats:
    """How a result was produced: used to show the routing call budget was kept."""

    routing_api_calls: int
    route_cache_hit: bool
    timings_ms: dict[str, float]


@dataclass(frozen=True)
class TripResult:
    plan: TripPlan
    stats: PlanningStats
