from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from routing.services.osrm import RoutingError, fetch_route


def response(payload, status=200):
    mock = Mock(status_code=status)
    mock.json.return_value = payload
    return mock


class FetchRouteTests(SimpleTestCase):
    @patch("routing.services.osrm.requests.get")
    def test_parses_distance_duration_and_geometry(self, mock_get):
        mock_get.return_value = response(
            {"code": "Ok", "routes": [{"distance": 160934.4, "duration": 7200, "geometry": "abc"}]}
        )
        route = fetch_route(35.0, -102.0, 35.0, -100.0)
        self.assertAlmostEqual(route.distance_miles, 100.0)
        self.assertAlmostEqual(route.duration_hours, 2.0)
        self.assertEqual(route.polyline, "abc")
        url = mock_get.call_args.args[0]
        self.assertIn("-102.000000,35.000000;-100.000000,35.000000", url)  # OSRM wants lng,lat
        self.assertIn("timeout", mock_get.call_args.kwargs)

    @patch("routing.services.osrm.requests.get")
    def test_no_route_raises(self, mock_get):
        mock_get.return_value = response({"code": "NoRoute", "routes": []})
        with self.assertRaisesMessage(RoutingError, "NoRoute"):
            fetch_route(35.0, -102.0, 35.0, -100.0)

    @patch("routing.services.osrm.requests.get", side_effect=requests.Timeout)
    def test_timeout_is_flagged(self, mock_get):
        with self.assertRaises(RoutingError) as caught:
            fetch_route(35.0, -102.0, 35.0, -100.0)
        self.assertTrue(caught.exception.timed_out)

    @patch("routing.services.osrm.requests.get", side_effect=requests.ConnectionError)
    def test_connection_failure_raises(self, mock_get):
        with self.assertRaises(RoutingError) as caught:
            fetch_route(35.0, -102.0, 35.0, -100.0)
        self.assertFalse(caught.exception.timed_out)
