"""Small geometry helpers: polyline decoding and distances along a route."""

import math

EARTH_DIAMETER_MILES = 7917.5
Point = tuple[float, float]  # (latitude, longitude)


def decode_polyline(encoded: str, precision: int = 5) -> list[Point]:
    """Decode a Google/OSRM encoded polyline into (lat, lng) points."""
    factor = 10**precision
    points: list[Point] = []
    index = lat = lng = 0
    length = len(encoded)
    while index < length:
        for is_lng in (False, True):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / factor, lng / factor))
    return points


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in miles."""
    rad = math.pi / 180
    a = (
        math.sin((lat2 - lat1) * rad / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lng2 - lng1) * rad / 2) ** 2
    )
    return EARTH_DIAMETER_MILES * math.asin(math.sqrt(a))


def mile_markers(points: list[Point], total_miles: float) -> list[float]:
    """Distance from the start to each point, scaled so the last equals total_miles.

    Straight-line sums between polyline points run slightly short of the road
    distance the routing API reports, so the markers are scaled to match it.
    """
    markers = [0.0]
    for (lat1, lng1), (lat2, lng2) in zip(points, points[1:]):
        markers.append(markers[-1] + haversine_miles(lat1, lng1, lat2, lng2))
    raw_total = markers[-1]
    if raw_total == 0:
        return markers
    scale = total_miles / raw_total
    return [m * scale for m in markers]


def thin(points: list[Point], max_points: int) -> list[Point]:
    """Keep at most max_points evenly spaced points, always including the last."""
    if len(points) <= max_points:
        return points
    step = math.ceil(len(points) / (max_points - 1))
    kept = points[::step]
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept
