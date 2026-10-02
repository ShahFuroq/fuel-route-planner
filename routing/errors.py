"""Translate planning failures into HTTP responses, in one place."""

import logging

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from routing.services.corridor import StationsNotLoaded
from routing.services.locations import LocationError
from routing.services.optimizer import NoFeasiblePlan
from routing.services.osrm import RoutingError

logger = logging.getLogger(__name__)


def error_for(exc: Exception) -> tuple[int, dict] | None:
    """Status code and body for an expected failure, or None if it is not one."""
    if isinstance(exc, ValidationError):
        return status.HTTP_400_BAD_REQUEST, {"error": "Invalid parameters.", "details": exc.detail}
    if isinstance(exc, LocationError):
        return status.HTTP_400_BAD_REQUEST, {"error": str(exc)}
    if isinstance(exc, NoFeasiblePlan):
        return status.HTTP_422_UNPROCESSABLE_ENTITY, {
            "error": f"{exc} That is further than the vehicle's range.",
            "gap": {"from_mile": round(exc.from_mile, 1), "to_mile": round(exc.to_mile, 1)},
        }
    if isinstance(exc, RoutingError):
        code = status.HTTP_504_GATEWAY_TIMEOUT if exc.timed_out else status.HTTP_502_BAD_GATEWAY
        return code, {"error": str(exc)}
    if isinstance(exc, StationsNotLoaded):
        return status.HTTP_503_SERVICE_UNAVAILABLE, {"error": str(exc)}
    return None


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler: planning failures first, then DRF's defaults."""
    mapped = error_for(exc)
    if mapped is None:
        return exception_handler(exc, context)
    code, body = mapped
    if code >= 500:
        logger.warning("Request failed with %d: %s", code, body["error"])
    return Response(body, status=code)
