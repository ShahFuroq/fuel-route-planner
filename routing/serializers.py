"""Request validation and response shaping for the route API."""

from django.conf import settings
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from routing.services.trip import TripPlan, TripResult


class RouteQuerySerializer(serializers.Serializer):
    """Query parameters for the route planner."""

    start = serializers.CharField(max_length=120, help_text="'City, ST', a 5-digit ZIP code, or 'lat,lng'.")
    finish = serializers.CharField(max_length=120, help_text="'City, ST', a 5-digit ZIP code, or 'lat,lng'.")
    stop_penalty = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="Dollar cost assigned to each stop when choosing stops. Default 5; 0 gives the lowest fuel cost.",
    )
    start_fuel_gallons = serializers.FloatField(
        required=False, min_value=0, default=0.0, help_text="Fuel already in the tank. Default 0."
    )

    def validate_start_fuel_gallons(self, value: float) -> float:
        tank = settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG
        if value > tank:
            raise serializers.ValidationError(f"The tank holds {tank:.0f} gallons.")
        return value

    def validate(self, attrs: dict) -> dict:
        attrs.setdefault("stop_penalty", settings.DEFAULT_STOP_PENALTY)
        return attrs


class RoundedFloatField(serializers.FloatField):
    """A JSON number rounded to a fixed number of decimal places."""

    def __init__(self, places: int, **kwargs):
        self.places = places
        super().__init__(**kwargs)

    def to_representation(self, value) -> float:
        return round(float(value), self.places)


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField()
    name = serializers.CharField()
    lat = RoundedFloatField(5, source="latitude")
    lng = RoundedFloatField(5, source="longitude")


class FuelStopSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    station_id = serializers.IntegerField(source="station.opis_id")
    name = serializers.CharField(source="station.name")
    address = serializers.CharField(source="station.address")
    city = serializers.CharField(source="station.city")
    state = serializers.CharField(source="station.state")
    lat = RoundedFloatField(5, source="station.latitude")
    lng = RoundedFloatField(5, source="station.longitude")
    mile_marker = RoundedFloatField(1, source="mile")
    miles_off_route = RoundedFloatField(1, source="offset_miles")
    price_per_gallon = RoundedFloatField(3, source="station.price")
    gallons = RoundedFloatField(2)
    cost = RoundedFloatField(2)


class FuelSummarySerializer(serializers.Serializer):
    mpg = serializers.FloatField()
    range_miles = serializers.FloatField()
    start_fuel_gallons = serializers.FloatField()
    stop_penalty = serializers.FloatField()
    total_gallons = RoundedFloatField(2)
    total_cost = RoundedFloatField(2)
    average_price_paid = RoundedFloatField(3, allow_null=True)
    stop_count = serializers.IntegerField()


class RouteGeometrySerializer(serializers.Serializer):
    """The route as a GeoJSON LineString."""

    type = serializers.CharField()
    coordinates = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))


class MetaSerializer(serializers.Serializer):
    routing_api_calls = serializers.IntegerField()
    route_cache_hit = serializers.BooleanField()
    timings_ms = serializers.DictField(child=serializers.FloatField())
    corridor_miles = serializers.FloatField()
    assumptions = serializers.ListField(child=serializers.CharField())


class TripResultSerializer(serializers.Serializer):
    """The response of GET /api/route/."""

    start = LocationSerializer(source="plan.start")
    finish = LocationSerializer(source="plan.finish")
    distance_miles = RoundedFloatField(1, source="plan.distance_miles")
    duration_hours = RoundedFloatField(2, source="plan.duration_hours")
    fuel = FuelSummarySerializer(source="plan")
    stops = FuelStopSerializer(many=True, source="plan.stops")
    route = serializers.SerializerMethodField()
    map_url = serializers.SerializerMethodField()
    meta = serializers.SerializerMethodField()

    @extend_schema_field(RouteGeometrySerializer)
    def get_route(self, result: TripResult) -> dict:
        return {
            "type": "LineString",
            "coordinates": [[round(lng, 5), round(lat, 5)] for lat, lng in result.plan.route_points],
        }

    @extend_schema_field(serializers.URLField)
    def get_map_url(self, result: TripResult) -> str:
        request = self.context["request"]
        return request.build_absolute_uri(f"{reverse('route-map')}?{request.GET.urlencode()}")

    @extend_schema_field(MetaSerializer)
    def get_meta(self, result: TripResult) -> dict:
        return {
            "routing_api_calls": result.stats.routing_api_calls,
            "route_cache_hit": result.stats.route_cache_hit,
            "timings_ms": result.stats.timings_ms,
            "corridor_miles": result.plan.corridor_miles,
            "assumptions": describe_assumptions(result.plan),
        }


def describe_assumptions(plan: TripPlan) -> list[str]:
    """The assumptions behind a plan, in plain sentences for the API consumer."""
    tank_gallons = plan.range_miles / plan.mpg
    if plan.start_station_miles is not None:
        radius = settings.START_STATION_RADIUS_MILES
        starting = (
            f"The tank starts empty and the trip begins with a fill-up at the cheapest station within "
            f"{radius:.0f} miles of the start, or the nearest one if none is that close "
            f"(chosen station: {plan.start_station_miles:.1f} miles away)."
        )
    else:
        starting = f"The tank starts with {plan.start_fuel_gallons:g} gallons, which are not charged."
    return [
        f"Vehicle range {plan.range_miles:.0f} miles at {plan.mpg:.0f} mpg ({tank_gallons:.0f} gallon tank).",
        starting,
        "The vehicle arrives with an empty tank; every gallon bought is burned on the trip.",
        "Station positions are town centres, so they can be a few miles from the real location.",
        f"Stations within {plan.corridor_miles:.0f} miles of the route were considered.",
    ]
