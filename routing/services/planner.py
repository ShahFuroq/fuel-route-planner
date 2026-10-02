"""Plan a trip: resolve the places, fetch the route, choose the fuel stops.

This module only orchestrates. Each step lives in its own module and knows
nothing about HTTP or JSON.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from routing.services.corridor import RouteStation, StationIndex, station_index
from routing.services.geometry import Point, decode_polyline, mile_markers, thin
from routing.services.locations import Location, LocationError, resolve_location
from routing.services.optimizer import FuelPoint, NoFeasiblePlan, Purchase, plan_fuel_stops
from routing.services.osrm import Route, fetch_route
from routing.services.trip import FuelStop, PlanningStats, TripPlan, TripResult

CENT = Decimal("0.01")


class Stopwatch:
    """Collects how long each named step took, in milliseconds."""

    def __init__(self) -> None:
        self.timings_ms: dict[str, float] = {}
        self._started = time.perf_counter()

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        began = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - began) * 1000
            self.timings_ms[name] = round(self.timings_ms.get(name, 0.0) + elapsed, 1)

    def finish(self) -> dict[str, float]:
        self.timings_ms["total"] = round((time.perf_counter() - self._started) * 1000, 1)
        return self.timings_ms


def plan_trip(start: str, finish: str, stop_penalty: float, start_fuel_gallons: float) -> TripResult:
    """Plan a trip between two places. Makes at most one routing API call."""
    watch = Stopwatch()
    with watch.measure("resolve_locations"):
        origin = resolve_location(start)
        destination = resolve_location(finish)
    if _point_key(origin) == _point_key(destination):
        raise LocationError("Start and finish are the same place.")

    route, route_cache_hit = _get_route(origin, destination, watch)

    plan_key = f"plan:{_trip_key(origin, destination)}:{stop_penalty:.2f}:{start_fuel_gallons:.2f}"
    plan = cache.get(plan_key)
    if plan is None:
        plan = _build_plan(origin, destination, route, stop_penalty, start_fuel_gallons, watch)
        cache.set(plan_key, plan, settings.ROUTE_CACHE_SECONDS)

    stats = PlanningStats(
        routing_api_calls=0 if route_cache_hit else 1,
        route_cache_hit=route_cache_hit,
        timings_ms=watch.finish(),
    )
    return TripResult(plan=plan, stats=stats)


def _get_route(origin: Location, destination: Location, watch: Stopwatch) -> tuple[Route, bool]:
    """Return the route and whether it came from the cache."""
    key = f"route:{_trip_key(origin, destination)}"
    route = cache.get(key)
    if route is not None:
        return route, True
    with watch.measure("routing_api"):
        route = fetch_route(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
    cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return route, False


def _trip_key(origin: Location, destination: Location) -> str:
    return f"{_point_key(origin)}:{_point_key(destination)}"


def _point_key(location: Location) -> str:
    """Rounded to 3 decimals (about 100 m), so equivalent inputs share a cache entry."""
    return f"{location.latitude:.3f},{location.longitude:.3f}"


def _build_plan(
    origin: Location,
    destination: Location,
    route: Route,
    stop_penalty: float,
    start_fuel_gallons: float,
    watch: Stopwatch,
) -> TripPlan:
    with watch.measure("geometry"):
        points = decode_polyline(route.polyline)
        markers = mile_markers(points, route.distance_miles)

    index = station_index()

    # With an empty tank the trip begins by filling up at the cheapest station near the start.
    first_fill: RouteStation | None = None
    if start_fuel_gallons <= 0:
        station, distance = index.starting_station(
            origin.latitude, origin.longitude, settings.START_STATION_RADIUS_MILES
        )
        first_fill = RouteStation(station=station, mile=0.0, offset_miles=distance)

    stops, corridor_miles = _choose_stops(
        index, points, markers, route.distance_miles, first_fill, stop_penalty, start_fuel_gallons, watch
    )
    return TripPlan(
        start=origin,
        finish=destination,
        distance_miles=route.distance_miles,
        duration_hours=route.duration_hours,
        stops=stops,
        route_points=tuple(thin(points, settings.MAX_ROUTE_GEOJSON_POINTS)),
        mpg=settings.VEHICLE_MPG,
        range_miles=settings.VEHICLE_RANGE_MILES,
        stop_penalty=stop_penalty,
        start_fuel_gallons=start_fuel_gallons,
        corridor_miles=corridor_miles,
        start_station_miles=first_fill.offset_miles if first_fill else None,
    )


def _choose_stops(
    index: StationIndex,
    points: list[Point],
    markers: list[float],
    total_miles: float,
    first_fill: RouteStation | None,
    stop_penalty: float,
    start_fuel_gallons: float,
    watch: Stopwatch,
) -> tuple[tuple[FuelStop, ...], float]:
    """Pick the stops, widening the corridor once if the narrow one leaves a gap."""
    widths = (settings.CORRIDOR_MILES, settings.CORRIDOR_FALLBACK_MILES)
    for width in widths:
        with watch.measure("corridor_search"):
            candidates = index.along_route(points, markers, width)
            if first_fill is not None:
                first_id = first_fill.station.opis_id
                candidates = [first_fill] + [c for c in candidates if c.station.opis_id != first_id]
        try:
            with watch.measure("optimizer"):
                stops = _optimise(candidates, total_miles, first_fill is not None, stop_penalty, start_fuel_gallons)
            return stops, width
        except NoFeasiblePlan:
            if width == widths[-1]:
                raise
    raise AssertionError("unreachable")  # the loop always returns or raises


def _optimise(
    candidates: list[RouteStation],
    total_miles: float,
    starts_at_station: bool,
    stop_penalty: float,
    start_fuel_gallons: float,
) -> tuple[FuelStop, ...]:
    """Run the optimizer over the candidate stations and turn its purchases into stops."""
    mpg = settings.VEHICLE_MPG
    fuel_points = [FuelPoint(mile=c.mile, price=float(c.station.price), penalty=stop_penalty) for c in candidates]
    # When the tank starts with fuel, the start is a point where nothing can be bought.
    leading = [] if starts_at_station else [FuelPoint(mile=0.0, price=None)]
    line = leading + fuel_points + [FuelPoint(mile=total_miles, price=None)]

    purchases = plan_fuel_stops(line, settings.VEHICLE_RANGE_MILES, mpg, start_range=start_fuel_gallons * mpg)
    return tuple(
        _to_stop(order, purchase, candidates[purchase.index - len(leading)])
        for order, purchase in enumerate(purchases, start=1)
    )


def _to_stop(order: int, purchase: Purchase, at: RouteStation) -> FuelStop:
    gallons = Decimal(str(round(purchase.gallons, 2)))
    return FuelStop(
        order=order,
        station=at.station,
        mile=at.mile,
        offset_miles=at.offset_miles,
        gallons=gallons,
        cost=(gallons * at.station.price).quantize(CENT),
    )
