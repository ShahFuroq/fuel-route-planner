from decimal import Decimal
from itertools import pairwise
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from routing.models import FuelStation
from routing.services.corridor import station_index
from routing.services.geometry import haversine_miles
from routing.services.osrm import Route, RoutingError
from routing.tests.helpers import encode_polyline

# A fake route running due east along latitude 35, about 1,130 miles long.
START, FINISH = "35.0,-102.0", "35.0,-82.0"
POINTS = [(35.0, -102.0 + i * 0.05) for i in range(401)]
ROUTE_MILES = haversine_miles(35.0, -102.0, 35.0, -82.0)
MILES_PER_DEGREE = ROUTE_MILES / 20.0


def fake_route(*args, **kwargs) -> Route:
    return Route(distance_miles=ROUTE_MILES, duration_hours=17.0, polyline=encode_polyline(POINTS))


def station(opis_id: int, mile: float, price: str, north_miles: float = 0.0) -> FuelStation:
    return FuelStation(
        opis_id=opis_id,
        name=f"Station {opis_id}",
        address="I-40",
        city="Testville",
        state="TX",
        rack_id=1,
        price=Decimal(price),
        latitude=35.0 + north_miles / 69.0,
        longitude=-102.0 + mile / MILES_PER_DEGREE,
    )


class RouteApiTests(TestCase):
    url = reverse("route-plan")

    def setUp(self):
        cache.clear()
        station_index.cache_clear()
        self.addCleanup(station_index.cache_clear)
        FuelStation.objects.bulk_create(
            [
                station(1, 0, "3.500"),
                station(2, 300, "3.000"),
                station(3, 450, "3.900"),
                station(4, 700, "3.100"),
                station(5, 900, "3.200"),
                station(6, 600, "2.000", north_miles=8),  # cheap but outside the 5-mile corridor
            ]
        )

    def get(self, **params):
        query = {"start": START, "finish": FINISH, **params}
        return self.client.get(self.url, query)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_returns_route_stops_and_total_cost(self, mock_fetch):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertAlmostEqual(body["distance_miles"], round(ROUTE_MILES, 1))
        self.assertEqual(body["route"]["type"], "LineString")
        self.assertEqual(body["route"]["coordinates"][0], [-102.0, 35.0])
        self.assertIn("/api/route/map/", body["map_url"])
        self.assertGreaterEqual(len(body["stops"]), 2)

        fuel = body["fuel"]
        self.assertAlmostEqual(fuel["total_gallons"], ROUTE_MILES / 10, delta=0.05)
        self.assertAlmostEqual(fuel["total_cost"], sum(stop["cost"] for stop in body["stops"]), places=2)
        for stop in body["stops"]:
            self.assertAlmostEqual(stop["cost"], stop["gallons"] * stop["price_per_gallon"], delta=0.02)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_stops_respect_the_vehicle_range(self, mock_fetch):
        stops = self.get().json()["stops"]
        marks = [stop["mile_marker"] for stop in stops] + [ROUTE_MILES]
        self.assertTrue(all(later - earlier <= 500.5 for earlier, later in pairwise(marks)))
        self.assertTrue(all(stop["gallons"] <= 50.0 for stop in stops))

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_stations_far_from_the_route_are_not_used(self, mock_fetch):
        stops = self.get().json()["stops"]
        self.assertNotIn(6, [stop["station_id"] for stop in stops])

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_prefers_cheap_stations(self, mock_fetch):
        stops = {stop["station_id"]: stop for stop in self.get(stop_penalty=0).json()["stops"]}
        # Station 3 is the most expensive on the route and is never needed.
        self.assertNotIn(3, stops)
        # Station 1 is pricey: buy only enough to reach station 2 at mile 300.
        self.assertAlmostEqual(stops[1]["gallons"], 30.0, delta=0.3)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_trip_starts_at_the_cheapest_station_near_the_start(self, mock_fetch):
        # Station 8 is 6 miles from the start and cheaper than station 1, which is at the start.
        FuelStation.objects.bulk_create([station(8, 0, "3.200", north_miles=6)])
        first = self.get().json()["stops"][0]
        self.assertEqual(first["station_id"], 8)
        self.assertEqual(first["mile_marker"], 0)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_trip_starts_at_the_nearest_station_when_none_is_close(self, mock_fetch):
        FuelStation.objects.filter(opis_id=1).delete()
        FuelStation.objects.bulk_create([station(9, 0, "3.400", north_miles=30)])
        first = self.get().json()["stops"][0]
        self.assertEqual(first["station_id"], 9)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_exactly_one_routing_call_then_none_when_cached(self, mock_fetch):
        first = self.get().json()
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(first["meta"]["routing_api_calls"], 1)
        self.assertFalse(first["meta"]["route_cache_hit"])

        second = self.get().json()
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(second["meta"]["routing_api_calls"], 0)
        self.assertTrue(second["meta"]["route_cache_hit"])
        self.assertEqual(first["stops"], second["stops"])

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_changing_the_penalty_reuses_the_cached_route(self, mock_fetch):
        self.get()
        self.get(stop_penalty=0)
        self.get(stop_penalty=25)
        self.assertEqual(mock_fetch.call_count, 1)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_starting_fuel_is_not_charged(self, mock_fetch):
        empty = self.get().json()["fuel"]
        full = self.get(start_fuel_gallons=50).json()["fuel"]
        self.assertAlmostEqual(full["total_gallons"], empty["total_gallons"] - 50, delta=0.05)
        self.assertLess(full["total_cost"], empty["total_cost"])

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_gap_longer_than_the_range_returns_422(self, mock_fetch):
        FuelStation.objects.filter(opis_id__in=[3, 4, 5]).delete()
        response = self.get()
        self.assertEqual(response.status_code, 422)
        self.assertIn("gap", response.json())

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_widens_the_corridor_when_the_narrow_one_has_a_gap(self, mock_fetch):
        FuelStation.objects.filter(opis_id__in=[3, 4, 5]).delete()
        FuelStation.objects.bulk_create([station(7, 700, "3.300", north_miles=10)])
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meta"]["corridor_miles"], 15.0)
        self.assertEqual(mock_fetch.call_count, 1)

    def test_bad_input_returns_400_without_calling_the_routing_api(self):
        cases = [
            {"start": "Honolulu, HI"},
            {"start": "Nowhereville, TX"},
            {"start": "51.5,-0.12"},
            {"finish": START},
            {"stop_penalty": "abc"},
            {"start_fuel_gallons": 80},
        ]
        with patch("routing.services.planner.fetch_route", side_effect=fake_route) as mock_fetch:
            for params in cases:
                with self.subTest(params=params):
                    self.assertEqual(self.get(**params).status_code, 400)
            self.assertEqual(self.client.get(self.url, {"start": START}).status_code, 400)
            self.assertEqual(mock_fetch.call_count, 0)

    def test_validation_errors_name_the_field(self):
        body = self.client.get(self.url, {"start": START}).json()
        self.assertEqual(body["error"], "Invalid parameters.")
        self.assertIn("finish", body["details"])

    def test_missing_station_data_returns_503_with_instructions(self):
        FuelStation.objects.all().delete()
        with patch("routing.services.planner.fetch_route", side_effect=fake_route):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertIn("load_fuel_stations", response.json()["error"])

    def test_planning_is_logged(self):
        with (
            patch("routing.services.planner.fetch_route", side_effect=fake_route),
            self.assertLogs("routing.services.planner", level="INFO") as logs,
        ):
            self.get()
        self.assertIn("routing_calls=1", logs.output[0])

    def test_routing_failures_map_to_gateway_errors(self):
        with patch("routing.services.planner.fetch_route", side_effect=RoutingError("down")):
            self.assertEqual(self.get().status_code, 502)
        with patch("routing.services.planner.fetch_route", side_effect=RoutingError("slow", timed_out=True)):
            self.assertEqual(self.get().status_code, 504)

    @patch("routing.services.planner.fetch_route", side_effect=fake_route)
    def test_map_page_renders_and_adds_no_routing_call(self, mock_fetch):
        self.get()
        response = self.client.get(reverse("route-map"), {"start": START, "finish": FINISH})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "plan-data")
        self.assertEqual(mock_fetch.call_count, 1)

    def test_map_page_lets_the_browser_send_a_referer_to_the_tile_server(self):
        # OpenStreetMap blocks tile requests that arrive without a Referer.
        response = self.client.get(reverse("route-map"), {"start": "Honolulu, HI", "finish": FINISH})
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_openapi_schema_describes_the_route_endpoint(self):
        response = self.client.get(reverse("schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/route/"]["get"]
        parameters = {parameter["name"] for parameter in operation["parameters"]}
        self.assertEqual(parameters, {"start", "finish", "stop_penalty", "start_fuel_gallons"})
        self.assertLessEqual({"200", "400", "422", "502", "503", "504"}, set(operation["responses"]))

    def test_docs_page_is_served(self):
        self.assertEqual(self.client.get(reverse("docs")).status_code, 200)

    def test_map_page_shows_errors(self):
        response = self.client.get(reverse("route-map"), {"start": "Honolulu, HI", "finish": FINISH})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Hawaii", status_code=400)
