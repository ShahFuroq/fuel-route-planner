"""The single outbound call: fetch a driving route from an OSRM server."""

from dataclasses import dataclass

import requests
from django.conf import settings

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    """The routing service failed or found no route."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_hours: float
    polyline: str


def fetch_route(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> Route:
    """One request returns distance, duration and the full route geometry."""
    url = (
        f"{settings.OSRM_BASE_URL}/route/v1/driving/"
        f"{start_lng:.6f},{start_lat:.6f};{end_lng:.6f},{end_lat:.6f}"
    )
    try:
        response = requests.get(
            url,
            params={"overview": "full", "geometries": "polyline", "steps": "false"},
            timeout=settings.OSRM_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise RoutingError("The routing service timed out.", timed_out=True) from exc
    except requests.RequestException as exc:
        raise RoutingError("The routing service could not be reached.") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise RoutingError(f"The routing service returned HTTP {response.status_code}.") from exc
    if body.get("code") != "Ok" or not body.get("routes"):
        raise RoutingError(f"No driving route was found ({body.get('code', 'unknown error')}).")

    route = body["routes"][0]
    return Route(
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_hours=route["duration"] / 3600,
        polyline=route["geometry"],
    )
