from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteQuerySerializer
from routing.services.locations import LocationError
from routing.services.optimizer import NoFeasiblePlan
from routing.services.osrm import RoutingError
from routing.services.planner import plan_trip


class PlanError(Exception):
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload


def build_plan(request) -> dict:
    """Validate the query, build the plan, and translate failures into HTTP errors."""
    serializer = RouteQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        raise PlanError(status.HTTP_400_BAD_REQUEST, {"error": "Invalid parameters.", "details": serializer.errors})
    params = serializer.validated_data
    try:
        plan = plan_trip(params["start"], params["finish"], params["stop_penalty"], params["start_fuel_gallons"])
    except LocationError as exc:
        raise PlanError(status.HTTP_400_BAD_REQUEST, {"error": str(exc)}) from exc
    except NoFeasiblePlan as exc:
        raise PlanError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "error": f"{exc} That is further than the vehicle's range.",
                "gap": {"from_mile": round(exc.from_mile, 1), "to_mile": round(exc.to_mile, 1)},
            },
        ) from exc
    except RoutingError as exc:
        code = status.HTTP_504_GATEWAY_TIMEOUT if exc.timed_out else status.HTTP_502_BAD_GATEWAY
        raise PlanError(code, {"error": str(exc)}) from exc
    map_path = f"{reverse('route-map')}?{request.query_params.urlencode()}"
    plan["map_url"] = request.build_absolute_uri(map_path)
    return plan


class RoutePlanView(APIView):
    """GET /api/route/?start=...&finish=... returns the route, fuel stops and total cost."""

    def get(self, request):
        try:
            return Response(build_plan(request))
        except PlanError as exc:
            return Response(exc.payload, status=exc.status_code)


class RouteMapView(APIView):
    """GET /api/route/map/ shows the same plan on a map. Reuses the cached route."""

    def get(self, request):
        try:
            plan = build_plan(request)
        except PlanError as exc:
            return render(request, "routing/map.html", {"error": exc.payload["error"]}, status=exc.status_code)
        return render(request, "routing/map.html", {"plan": plan})
