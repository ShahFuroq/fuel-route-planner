from django.shortcuts import render
from django.views import View
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.errors import error_for
from routing.serializers import RouteQuerySerializer, TripResultSerializer
from routing.services.planner import plan_trip
from routing.services.trip import TripResult


def plan_from_query(query_params) -> TripResult:
    """Validate the query parameters and plan the trip. Raises on any failure."""
    query = RouteQuerySerializer(data=query_params)
    query.is_valid(raise_exception=True)
    return plan_trip(**query.validated_data)


class RoutePlanView(APIView):
    """Plan a driving route and the cheapest fuel stops along it."""

    @extend_schema(
        summary="Plan a route with fuel stops",
        description=(
            "Returns the driving route between two US locations, the fuel stops that minimise cost "
            "for a vehicle with a 500-mile range at 10 mpg, and the total fuel cost. "
            "Makes one routing API call, or none when the route is cached."
        ),
        parameters=[RouteQuerySerializer],
        responses={
            200: TripResultSerializer,
            400: OpenApiResponse(description="Missing, unreadable, unknown or unsupported location or parameter."),
            422: OpenApiResponse(description="A stretch of the route has no fuel station within range."),
            502: OpenApiResponse(description="The routing service failed."),
            503: OpenApiResponse(description="Fuel station data has not been loaded."),
            504: OpenApiResponse(description="The routing service timed out."),
        },
    )
    def get(self, request: Request) -> Response:
        result = plan_from_query(request.query_params)
        return Response(TripResultSerializer(result, context={"request": request}).data)


class RouteMapView(View):
    """Show the same plan on a map. Reuses the cached route, so it adds no routing call."""

    template_name = "routing/map.html"

    def get(self, request):
        try:
            result = plan_from_query(request.GET)
        except Exception as exc:
            mapped = error_for(exc)
            if mapped is None:
                raise
            code, body = mapped
            return render(request, self.template_name, {"error": body["error"]}, status=code)
        plan = TripResultSerializer(result, context={"request": request}).data
        return render(request, self.template_name, {"plan": plan})
