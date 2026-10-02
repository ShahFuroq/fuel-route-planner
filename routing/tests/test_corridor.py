from decimal import Decimal

from django.test import SimpleTestCase

from routing.services.corridor import Station, StationIndex
from routing.services.geometry import haversine_miles


def make_station(opis_id: int, lat: float, lng: float, price: str = "3.000") -> Station:
    return Station(opis_id, f"Station {opis_id}", "I-00", "Town", "TX", Decimal(price), lat, lng)


def miles_east(lat: float, miles: float) -> float:
    """Degrees of longitude that cover the given distance at this latitude."""
    return miles / haversine_miles(lat, 0.0, lat, 1.0)


class StationIndexTests(SimpleTestCase):
    def test_within_respects_the_radius(self):
        index = StationIndex([make_station(1, 35.0, -100.0), make_station(2, 35.0, -100.0 + miles_east(35.0, 8))])
        found = {station.opis_id for station, _ in index.within(35.0, -100.0, 5.0)}
        self.assertEqual(found, {1})

    def test_wide_search_reaches_across_grid_cells_at_northern_latitudes(self):
        # At latitude 48 a grid cell is only about 11.5 miles wide, so a 15-mile
        # search has to look more than one cell to the east and west.
        lat, lng = 48.1, -99.999
        for miles in (-14.0, 14.0):
            with self.subTest(miles=miles):
                index = StationIndex([make_station(1, lat, lng + miles_east(lat, miles))])
                self.assertEqual(len(index.within(lat, lng, 15.0)), 1)

    def test_along_route_orders_by_mile_and_records_the_offset(self):
        points = [(35.0, -100.0 + i * 0.01) for i in range(201)]
        markers = [i * 0.5653 for i in range(201)]  # about 113 miles in total
        far = make_station(1, 35.0 + 3 / 69.0, -98.5)
        near = make_station(2, 35.0, -99.5)
        outside = make_station(3, 35.0 + 9 / 69.0, -99.0)
        found = StationIndex([far, near, outside]).along_route(points, markers, 5.0)
        self.assertEqual([f.station.opis_id for f in found], [2, 1])
        self.assertAlmostEqual(found[0].offset_miles, 0.0, delta=0.6)
        self.assertAlmostEqual(found[1].offset_miles, 3.0, delta=0.3)

    def test_starting_station_prefers_cheap_and_close_over_nearest(self):
        nearest = make_station(1, 35.0, -100.0, "3.500")
        cheaper = make_station(2, 35.0 + 6 / 69.0, -100.0, "3.100")
        index = StationIndex([nearest, cheaper])
        self.assertEqual(index.starting_station(35.0, -100.0, 10.0)[0].opis_id, 2)
        self.assertEqual(index.starting_station(35.0, -100.0, 3.0)[0].opis_id, 1)

    def test_starting_station_falls_back_to_the_nearest_when_none_is_close(self):
        index = StationIndex([make_station(1, 36.0, -100.0), make_station(2, 38.0, -100.0)])
        station, distance = index.starting_station(35.0, -100.0, 10.0)
        self.assertEqual(station.opis_id, 1)
        self.assertAlmostEqual(distance, 69.0, delta=1.0)

