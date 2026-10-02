import random
from itertools import pairwise

from django.test import SimpleTestCase

from routing.services.optimizer import FuelPoint, NoFeasiblePlan, plan_fuel_stops


def fuel_cost(points, purchases):
    return sum(p.gallons * points[p.index].price for p in purchases)


def greedy_minimum_cost(points, tank_range, mpg):
    """Independent textbook algorithm for the no-penalty case.

    At each station: if a cheaper one is within range, buy just enough to reach
    it; otherwise fill up and drive to the cheapest station within range.
    """
    fuel = cost = 0.0
    i = 0
    last = len(points) - 1
    while i != last:
        here = points[i]
        reachable = [j for j in range(i + 1, last + 1) if points[j].mile - here.mile <= tank_range + 1e-9]
        if not reachable:
            return None
        target = next((j for j in reachable if j == last or points[j].price < here.price), None)
        if target is not None:
            needed = points[target].mile - here.mile
        else:
            target = min(reachable, key=lambda j: points[j].price)
            needed = tank_range
        buy = max(0.0, needed - fuel)
        cost += buy / mpg * here.price
        fuel = fuel + buy - (points[target].mile - here.mile)
        i = target
    return cost


def brute_force_objective(points, tank_range, penalty):
    """Exhaustive search over whole-unit purchases (integer miles, 1 mpg)."""
    tank = int(tank_range)
    best = {0: 0.0}  # fuel on arrival -> cheapest objective
    for i, point in enumerate(points[:-1]):
        distance = int(points[i + 1].mile - point.mile)
        following: dict[int, float] = {}
        for fuel, cost in best.items():
            for buy in range(0, tank - fuel + 1):
                if fuel + buy < distance:
                    continue
                total = cost + buy * point.price + (penalty if buy else 0.0)
                left = fuel + buy - distance
                if total < following.get(left, float("inf")):
                    following[left] = total
        best = following
        if not best:
            return None
    return min(best.values())


class PlanFuelStopsTests(SimpleTestCase):
    def test_single_leg_buys_exactly_the_fuel_needed(self):
        points = [FuelPoint(0, 3.0), FuelPoint(200, None)]
        purchases = plan_fuel_stops(points, tank_range=500, mpg=10)
        self.assertEqual(len(purchases), 1)
        self.assertAlmostEqual(purchases[0].gallons, 20.0)

    def test_buys_only_enough_to_reach_a_cheaper_station(self):
        points = [FuelPoint(0, 4.0), FuelPoint(100, 3.0), FuelPoint(400, None)]
        purchases = plan_fuel_stops(points, tank_range=500, mpg=10)
        self.assertEqual([(p.index, round(p.gallons, 3)) for p in purchases], [(0, 10.0), (1, 30.0)])

    def test_fills_up_at_a_cheap_station_before_an_expensive_one(self):
        # 700 miles; the cheap station is first, so fill there and top up later.
        points = [FuelPoint(0, 3.0), FuelPoint(400, 4.0), FuelPoint(700, None)]
        purchases = plan_fuel_stops(points, tank_range=500, mpg=10)
        self.assertEqual([(p.index, round(p.gallons, 3)) for p in purchases], [(0, 50.0), (1, 20.0)])
        self.assertAlmostEqual(fuel_cost(points, purchases), 230.0)

    def test_never_drives_further_than_the_tank_allows(self):
        random.seed(7)
        miles = sorted(random.uniform(1, 2990) for _ in range(120))
        points = [FuelPoint(0, 3.2)] + [FuelPoint(m, random.uniform(2.8, 4.0)) for m in miles] + [FuelPoint(3000, None)]
        purchases = plan_fuel_stops(points, tank_range=500, mpg=10)
        stops = [points[p.index].mile for p in purchases] + [3000]
        self.assertTrue(all(b - a <= 500 + 1e-6 for a, b in pairwise(stops)))
        self.assertAlmostEqual(sum(p.gallons for p in purchases), 300.0, places=6)

    def test_unreachable_gap_is_reported_with_its_location(self):
        points = [FuelPoint(0, 3.0), FuelPoint(300, 3.0), FuelPoint(900, 3.0), FuelPoint(1000, None)]
        with self.assertRaises(NoFeasiblePlan) as caught:
            plan_fuel_stops(points, tank_range=500, mpg=10)
        self.assertEqual((caught.exception.from_mile, caught.exception.to_mile), (300, 900))

    def test_stop_penalty_reduces_the_number_of_stops(self):
        random.seed(3)
        miles = sorted(random.uniform(1, 1990) for _ in range(80))

        def build(penalty):
            random.seed(11)
            return (
                [FuelPoint(0, 3.3, penalty)]
                + [FuelPoint(m, random.uniform(2.8, 3.8), penalty) for m in miles]
                + [FuelPoint(2000, None)]
            )

        free = plan_fuel_stops(build(0.0), tank_range=500, mpg=10)
        penalised = plan_fuel_stops(build(10.0), tank_range=500, mpg=10)
        self.assertLess(len(penalised), len(free))
        self.assertGreaterEqual(fuel_cost(build(10.0), penalised), fuel_cost(build(0.0), free) - 1e-6)

    def test_starting_fuel_is_used_before_buying(self):
        points = [FuelPoint(0, None), FuelPoint(100, 3.0), FuelPoint(400, None)]
        purchases = plan_fuel_stops(points, tank_range=500, mpg=10, start_range=250)
        # 250 miles in the tank, 400 to drive: buy the missing 150 miles = 15 gallons.
        self.assertEqual([(p.index, round(p.gallons, 3)) for p in purchases], [(1, 15.0)])

    def test_enough_starting_fuel_means_no_purchases(self):
        points = [FuelPoint(0, None), FuelPoint(100, 3.0), FuelPoint(300, None)]
        self.assertEqual(plan_fuel_stops(points, tank_range=500, mpg=10, start_range=500), [])

    def test_matches_the_textbook_greedy_when_there_is_no_penalty(self):
        random.seed(42)
        for _ in range(200):
            count = random.randint(1, 40)
            total = random.uniform(100, 3000)
            miles = sorted(random.uniform(0.5, total - 0.5) for _ in range(count))
            points = (
                [FuelPoint(0, random.uniform(2.7, 4.2))]
                + [FuelPoint(m, random.uniform(2.7, 4.2)) for m in miles]
                + [FuelPoint(total, None)]
            )
            expected = greedy_minimum_cost(points, 500, 10)
            if expected is None:
                with self.assertRaises(NoFeasiblePlan):
                    plan_fuel_stops(points, 500, 10)
                continue
            self.assertAlmostEqual(fuel_cost(points, plan_fuel_stops(points, 500, 10)), expected, places=6)

    def test_matches_brute_force_with_a_penalty(self):
        random.seed(5)
        for _ in range(300):
            count = random.randint(1, 6)
            miles = sorted(random.sample(range(1, 30), count))
            penalty = random.choice([0.0, 1.5, 4.0])
            points = (
                [FuelPoint(0, random.randint(2, 9), penalty)]
                + [FuelPoint(m, random.randint(2, 9), penalty) for m in miles]
                + [FuelPoint(30, None)]
            )
            expected = brute_force_objective(points, tank_range=10, penalty=penalty)
            if expected is None:
                with self.assertRaises(NoFeasiblePlan):
                    plan_fuel_stops(points, tank_range=10, mpg=1)
                continue
            purchases = plan_fuel_stops(points, tank_range=10, mpg=1)
            objective = fuel_cost(points, purchases) + penalty * len(purchases)
            self.assertAlmostEqual(objective, expected, places=6)
