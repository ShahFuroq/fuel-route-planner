from django.conf import settings
from rest_framework import serializers


class RouteQuerySerializer(serializers.Serializer):
    """Query parameters for the route planner."""

    start = serializers.CharField(max_length=120, help_text="'City, ST', a ZIP code, or 'lat,lng'.")
    finish = serializers.CharField(max_length=120, help_text="'City, ST', a ZIP code, or 'lat,lng'.")
    stop_penalty = serializers.FloatField(
        required=False, min_value=0, max_value=100, help_text="Dollar cost assigned to each stop."
    )
    start_fuel_gallons = serializers.FloatField(required=False, min_value=0, default=0.0)

    def validate_start_fuel_gallons(self, value: float) -> float:
        tank = settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG
        if value > tank:
            raise serializers.ValidationError(f"The tank holds {tank:.0f} gallons.")
        return value

    def validate(self, attrs: dict) -> dict:
        attrs.setdefault("stop_penalty", settings.DEFAULT_STOP_PENALTY)
        return attrs
