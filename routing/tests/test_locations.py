from django.test import SimpleTestCase

from routing.services.locations import LocationError, find_city, normalize_place, resolve_location


class NormalizeTests(SimpleTestCase):
    def test_variants_of_the_same_town_match(self):
        self.assertEqual(normalize_place("Saint Louis"), normalize_place("St. Louis"))
        self.assertEqual(normalize_place("Winston-Salem"), normalize_place("winston salem"))
        self.assertEqual(normalize_place("  Effingham     "), "effingham")


class ResolveLocationTests(SimpleTestCase):
    def test_city_and_state(self):
        location = resolve_location("Chicago, IL")
        self.assertAlmostEqual(location.latitude, 41.85, delta=0.3)
        self.assertAlmostEqual(location.longitude, -87.65, delta=0.3)
        self.assertEqual(location.name, "Chicago, IL")

    def test_full_state_name(self):
        self.assertEqual(resolve_location("dallas, texas").name, "Dallas, TX")

    def test_zip_code(self):
        location = resolve_location("10001")
        self.assertEqual(location.name, "New York, NY")

    def test_coordinates(self):
        location = resolve_location("41.8781, -87.6298")
        self.assertEqual((location.latitude, location.longitude), (41.8781, -87.6298))

    def test_spacing_differences_still_match(self):
        self.assertIsNotNone(find_city("De Forest", "WI"))

    def test_alaska_and_hawaii_are_rejected_with_a_reason(self):
        for query in ("Honolulu, HI", "Anchorage, AK"):
            with self.assertRaisesMessage(LocationError, "48 contiguous states"):
                resolve_location(query)

    def test_coordinates_outside_the_us_are_rejected(self):
        with self.assertRaisesMessage(LocationError, "outside the contiguous United States"):
            resolve_location("51.5, -0.12")

    def test_unknown_town_unknown_zip_and_bad_format(self):
        for query in ("Nowhereville, TX", "00000", "Dallas", "", "Dallas, ZZ"):
            with self.assertRaises(LocationError):
                resolve_location(query)
