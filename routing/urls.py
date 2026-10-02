from django.urls import path

from routing.views import RouteMapView, RoutePlanView

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
    path("route/map/", RouteMapView.as_view(), name="route-map"),
]
