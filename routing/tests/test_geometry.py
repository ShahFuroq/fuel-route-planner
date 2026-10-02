from django.test import SimpleTestCase

from routing.services.geometry import decode_polyline, haversine_miles, mile_markers, thin
from routing.tests.helpers import encode_polyline


class DecodePolylineTests(SimpleTestCase):
    def test_decodes_the_reference_example(self):
        # Example from Google's polyline algorithm documentation.
        points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(points, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_round_trips_with_the_test_encoder(self):
        points = [(35.0, -100.0), (35.12345, -99.5), (34.9, -98.25)]
        self.assertEqual(decode_polyline(encode_polyline(points)), points)

    def test_empty_string_gives_no_points(self):
        self.assertEqual(decode_polyline(""), [])


class DistanceTests(SimpleTestCase):
    def test_haversine_matches_a_known_distance(self):
        # New York City to Los Angeles is about 2,446 miles in a straight line.
        miles = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(miles, 2446, delta=5)

    def test_mile_markers_start_at_zero_and_end_at_the_reported_total(self):
        points = [(35.0, -100.0), (35.0, -99.0), (35.0, -98.0)]
        markers = mile_markers(points, total_miles=120.0)
        self.assertEqual(markers[0], 0.0)
        self.assertAlmostEqual(markers[-1], 120.0)
        self.assertAlmostEqual(markers[1], 60.0, delta=0.5)

    def test_thin_keeps_the_first_and_last_point(self):
        points = [(float(i), 0.0) for i in range(1000)]
        kept = thin(points, 100)
        self.assertLessEqual(len(kept), 101)
        self.assertEqual(kept[0], points[0])
        self.assertEqual(kept[-1], points[-1])

    def test_thin_leaves_short_lists_alone(self):
        points = [(1.0, 1.0), (2.0, 2.0)]
        self.assertEqual(thin(points, 100), points)
