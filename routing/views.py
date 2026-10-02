from django.shortcuts import render
from django.views import View
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
