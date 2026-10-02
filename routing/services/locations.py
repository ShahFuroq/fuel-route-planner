"""Turn a start/finish input into coordinates using a bundled place file.

No network call is made. The file is the GeoNames US postal code list
(https://download.geonames.org/export/zip/, CC BY 4.0).
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

STATE_NAMES = {
    "alabama": "AL", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
# The fuel price file covers the 48 contiguous states, so routing is limited to them.
SUPPORTED_STATES = frozenset(STATE_NAMES.values())
UNSUPPORTED_STATES = {"AK": "Alaska", "HI": "Hawaii", "ALASKA": "Alaska", "HAWAII": "Hawaii"}

# Rough box around the contiguous United States, used for raw coordinates.
LAT_RANGE = (24.4, 49.4)
LNG_RANGE = (-124.9, -66.9)

COORDINATE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
ZIP_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")


class LocationError(ValueError):
    """The input could not be resolved to a supported US location."""


@dataclass(frozen=True)
class Location:
    query: str
    name: str
    latitude: float
    longitude: float


def normalize_place(name: str) -> str:
    """Normalize a town name so 'Saint Louis', 'St. Louis' and 'st louis' all match."""
    name = name.lower().strip().replace(".", "").replace("'", "").replace("-", " ")
    name = re.sub(r"^saint ", "st ", name)
    return re.sub(r"\s+", " ", name)


@dataclass(frozen=True)
class PlaceIndex:
    by_city: dict[tuple[str, str], tuple[float, float]]
    by_compact: dict[tuple[str, str], tuple[float, float]]
    by_zip: dict[str, tuple[str, str, float, float]]


@lru_cache(maxsize=1)
def place_index() -> PlaceIndex:
    """Load the place file once per process."""
    sums: dict[tuple[str, str], list[float]] = {}
    by_zip: dict[str, tuple[str, str, float, float]] = {}
    with open(settings.PLACES_FILE, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            try:
                zip_code, place, state = fields[1], fields[2], fields[4]
                lat, lng = float(fields[9]), float(fields[10])
            except (IndexError, ValueError):
                continue
            by_zip[zip_code] = (place, state, lat, lng)
            entry = sums.setdefault((normalize_place(place), state), [0.0, 0.0, 0])
            entry[0] += lat
            entry[1] += lng
            entry[2] += 1
    # A town with several ZIP codes is placed at the average of their centres.
    by_city = {key: (lat / n, lng / n) for key, (lat, lng, n) in sums.items()}
    # Second lookup that ignores spaces, so "De Forest" finds "DeForest".
    by_compact = {(name.replace(" ", ""), state): value for (name, state), value in by_city.items()}
    return PlaceIndex(by_city=by_city, by_compact=by_compact, by_zip=by_zip)


def find_city(city: str, state: str) -> tuple[float, float] | None:
    index = place_index()
    name, state = normalize_place(city), state.upper()
    return index.by_city.get((name, state)) or index.by_compact.get((name.replace(" ", ""), state))


def resolve_location(query: str) -> Location:
    """Resolve 'City, ST', a 5-digit ZIP code, or 'lat,lng' to coordinates."""
    text = (query or "").strip()
    if not text:
        raise LocationError("Location is empty.")

    match = COORDINATE_RE.match(text)
    if match:
        lat, lng = float(match.group(1)), float(match.group(2))
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
            raise LocationError(f"'{text}' is outside the contiguous United States.")
        return Location(query=text, name=f"{lat:.4f}, {lng:.4f}", latitude=lat, longitude=lng)

    match = ZIP_RE.match(text)
    if match:
        found = place_index().by_zip.get(match.group(1))
        if not found:
            raise LocationError(f"ZIP code '{match.group(1)}' was not found.")
        place, state, lat, lng = found
        _require_supported(state, text)
        return Location(query=text, name=f"{place}, {state}", latitude=lat, longitude=lng)

    if "," not in text:
        raise LocationError(
            f"Could not read '{text}'. Use 'City, ST', a 5-digit ZIP code, or 'lat,lng'."
        )
    city, _, state_text = text.rpartition(",")
    state_text = state_text.strip()
    state = STATE_NAMES.get(state_text.lower(), state_text.upper())
    _require_supported(state, text)
    coordinates = find_city(city, state)
    if coordinates is None:
        raise LocationError(f"'{text}' was not found. Check the spelling or use a ZIP code.")
    return Location(
        query=text, name=f"{city.strip().title()}, {state}", latitude=coordinates[0], longitude=coordinates[1]
    )


def _require_supported(state: str, text: str) -> None:
    if state in SUPPORTED_STATES:
        return
    if state.upper() in UNSUPPORTED_STATES:
        raise LocationError(
            f"'{text}' is in {UNSUPPORTED_STATES[state.upper()]}. Only the 48 contiguous states "
            "and DC are supported, because the fuel price data covers only those."
        )
    raise LocationError(f"'{text}' is not a recognised US state.")
