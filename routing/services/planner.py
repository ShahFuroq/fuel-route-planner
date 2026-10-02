"""Build a fuel plan for a trip: resolve the places, fetch the route, pick the stops."""

import time
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from routing.services.corridor import RouteStation, Station, station_index
from routing.services.geometry import decode_polyline, mile_markers, thin
from routing.services.locations import Location, LocationError, resolve_location
from routing.services.optimizer import FuelPoint, NoFeasiblePlan, plan_fuel_stops
from routing.services.osrm import Route, fetch_route

CENT = Decimal("0.01")


def plan_trip(start_query: str, finish_query: str, stop_penalty: float, start_fuel_gallons: float) -> dict:
    """Return the full response for a trip. Makes at most one routing API call."""
    started = time.perf_counter()
    timings: dict[str, float] = {}

    start = resolve_location(start_query)
    finish = resolve_location(finish_query)
    timings["resolve_locations"] = _since(started)

    if _point_key(start) == _point_key(finish):
        raise LocationError("Start and finish are the same place.")
    route, route_cache_hit = _get_route(start, finish, timings)

    plan_key = f"plan:{_coordinate_key(start, finish)}:{stop_penalty:.2f}:{start_fuel_gallons:.2f}"
    body = cache.get(plan_key)
    if body is None:
        body = _build_plan(start, finish, route, stop_penalty, start_fuel_gallons, timings)
        cache.set(plan_key, body, settings.ROUTE_CACHE_SECONDS)

    timings["total"] = _since(started)
    meta = {
        "routing_api_calls": 0 if route_cache_hit else 1,
        "route_cache_hit": route_cache_hit,
        "timings_ms": timings,
    }
    return {**body, "meta": {**meta, **body["meta"]}}


def _get_route(start: Location, finish: Location, timings: dict) -> tuple[Route, bool]:
    key = f"route:{_coordinate_key(start, finish)}"
    route = cache.get(key)
    if route is not None:
        return route, True
    began = time.perf_counter()
    route = fetch_route(start.latitude, start.longitude, finish.latitude, finish.longitude)
    timings["routing_api"] = _since(began)
    cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return route, False


def _coordinate_key(start: Location, finish: Location) -> str:
    """Rounded to 3 decimals (about 100 m), so equivalent inputs share a cache entry."""
    return f"{_point_key(start)}:{_point_key(finish)}"


def _point_key(location: Location) -> str:
    return f"{location.latitude:.3f},{location.longitude:.3f}"


def _build_plan(
    start: Location, finish: Location, route: Route, stop_penalty: float, start_fuel_gallons: float, timings: dict
) -> dict:
    mpg = settings.VEHICLE_MPG
    tank_range = settings.VEHICLE_RANGE_MILES

    began = time.perf_counter()
    points = decode_polyline(route.polyline)
    markers = mile_markers(points, route.distance_miles)
    timings["geometry"] = _since(began)

    index = station_index()
    if not index.stations:
        raise RuntimeError("No fuel stations are loaded. Run: python manage.py load_fuel_stations")

    # With an empty tank the trip begins by filling up at the cheapest station near the start.
    origin: RouteStation | None = None
    if start_fuel_gallons <= 0:
        station, distance = index.starting_station(
            start.latitude, start.longitude, settings.START_STATION_RADIUS_MILES
        )
        origin = RouteStation(station=station, mile=0.0, offset_miles=distance)

    corridor_ms = optimizer_ms = 0.0
    widths = (settings.CORRIDOR_MILES, settings.CORRIDOR_FALLBACK_MILES)
    for attempt, width in enumerate(widths):
        began = time.perf_counter()
        found = index.along_route(points, markers, width)
        if origin is not None:
            found = [origin] + [f for f in found if f.station.opis_id != origin.station.opis_id]
        corridor_ms += _since(began)

        fuel_points = [
            FuelPoint(
                mile=f.mile,
                price=float(f.station.price),
                penalty=stop_penalty,
            )
            for f in found
        ]
        if origin is None:
            fuel_points.insert(0, FuelPoint(mile=0.0, price=None))
            found = [None] + found
        fuel_points.append(FuelPoint(mile=route.distance_miles, price=None))

        began = time.perf_counter()
        try:
            purchases = plan_fuel_stops(fuel_points, tank_range, mpg, start_range=start_fuel_gallons * mpg)
            optimizer_ms += _since(began)
            break
        except NoFeasiblePlan:
            optimizer_ms += _since(began)
            if attempt == len(widths) - 1:
                raise
    timings["corridor_search"] = round(corridor_ms, 1)
    timings["optimizer"] = round(optimizer_ms, 1)

    stops = []
    total_cost = Decimal("0")
    total_gallons = Decimal("0")
    for order, purchase in enumerate(purchases, start=1):
        found_station: RouteStation = found[purchase.index]
        station: Station = found_station.station
        gallons = Decimal(str(round(purchase.gallons, 2)))
        cost = (gallons * station.price).quantize(CENT)
        total_cost += cost
        total_gallons += gallons
        stops.append(
            {
                "order": order,
                "station_id": station.opis_id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "lat": round(station.latitude, 5),
                "lng": round(station.longitude, 5),
                "mile_marker": round(found_station.mile, 1),
                "miles_off_route": round(found_station.offset_miles, 1),
                "price_per_gallon": float(station.price.quantize(Decimal("0.001"))),
                "gallons": float(gallons),
                "cost": float(cost),
            }
        )

    assumptions = [
        f"Vehicle range {tank_range:.0f} miles at {mpg:.0f} mpg ({tank_range / mpg:.0f} gallon tank).",
        "The vehicle arrives with an empty tank; every gallon bought is burned on the trip.",
        "Station positions are town centres, so they can be a few miles from the real location.",
        f"Stations within {width:.0f} miles of the route were considered.",
    ]
    if origin is not None:
        assumptions.insert(
            1,
            "The tank starts empty and the trip begins with a fill-up at the cheapest station within "
            f"{settings.START_STATION_RADIUS_MILES:.0f} miles of the start, or the nearest one if none "
            f"is that close (chosen station: {origin.offset_miles:.1f} miles away).",
        )
    else:
        assumptions.insert(1, f"The tank starts with {start_fuel_gallons:g} gallons, which are not charged.")

    geojson_points = thin(points, settings.MAX_ROUTE_GEOJSON_POINTS)
    return {
        "start": _location_json(start),
        "finish": _location_json(finish),
        "distance_miles": round(route.distance_miles, 1),
        "duration_hours": round(route.duration_hours, 2),
        "fuel": {
            "mpg": mpg,
            "range_miles": tank_range,
            "start_fuel_gallons": start_fuel_gallons,
            "stop_penalty": stop_penalty,
            "total_gallons": float(total_gallons),
            "total_cost": float(total_cost),
            "average_price_paid": float((total_cost / total_gallons).quantize(Decimal("0.001")))
            if total_gallons
            else None,
            "stop_count": len(stops),
        },
        "stops": stops,
        "route": {
            "type": "LineString",
            "coordinates": [[round(lng, 5), round(lat, 5)] for lat, lng in geojson_points],
        },
        "meta": {"corridor_miles": width, "assumptions": assumptions},
    }


def _location_json(location: Location) -> dict:
    return {
        "query": location.query,
        "name": location.name,
        "lat": round(location.latitude, 5),
        "lng": round(location.longitude, 5),
    }


def _since(began: float) -> float:
    return round((time.perf_counter() - began) * 1000, 1)
