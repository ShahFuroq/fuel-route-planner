"""Choose where to buy fuel along a fixed route at the lowest cost.

The route is reduced to a line: each fuel point has a mile marker and a price.
The optimizer minimises (fuel cost + a penalty for each stop) and is exact for
that objective.

It relies on a known property of this problem (Khuller, Malekian and Mestre,
"To Fill or Not to Fill: The Gas Station Problem"): in an optimal plan, at
every stop you either buy just enough to reach the next stop with an empty
tank, or you fill the tank. So the fuel you arrive with is always zero or
"a full tank minus the distance from the previous stop", which keeps the
number of states small.

Fuel is tracked in miles of range to keep the arithmetic simple.
"""

from bisect import bisect_right
from dataclasses import dataclass

EPSILON = 1e-9


class NoFeasiblePlan(Exception):
    """Some stretch of the route is longer than the vehicle can drive between fuel points."""

    def __init__(self, from_mile: float, to_mile: float):
        super().__init__(f"No fuel station between mile {from_mile:.0f} and mile {to_mile:.0f}.")
        self.from_mile = from_mile
        self.to_mile = to_mile


@dataclass(frozen=True)
class FuelPoint:
    mile: float
    price: float | None  # dollars per gallon; None means fuel cannot be bought here
    penalty: float = 0.0  # cost of stopping here; steers the choice only


@dataclass(frozen=True)
class Purchase:
    index: int  # position in the list passed to plan_fuel_stops
    gallons: float


def plan_fuel_stops(points: list[FuelPoint], tank_range: float, mpg: float, start_range: float = 0.0) -> list[Purchase]:
    """Return the purchases of the cheapest plan.

    points[0] is the start and points[-1] the destination, in route order.
    start_range is the fuel in the tank at the start, in miles.
    """
    last = len(points) - 1
    # states[i][fuel_on_arrival] = (cost so far, (previous point, its arrival fuel))
    states: list[dict[float, tuple[float, tuple[int, float] | None]]] = [{} for _ in points]
    states[0][min(start_range, tank_range)] = (0.0, None)

    def relax(index: int, fuel: float, cost: float, back: tuple[int, float]) -> None:
        known = states[index].get(fuel)
        if known is None or cost < known[0]:
            states[index][fuel] = (cost, back)

    for here in range(last):
        if not states[here]:
            continue
        point = points[here]
        arrivals = sorted(states[here])

        # Driving on without buying: only possible on the fuel already in the tank.
        # Later points get this for free, because skipping a stop is a direct edge.
        if point.price is None or here == 0:
            for fuel in arrivals:
                cost = states[here][fuel][0]
                for there in range(here + 1, last + 1):
                    distance = points[there].mile - point.mile
                    if distance > fuel + EPSILON:
                        break
                    relax(there, max(fuel - distance, 0.0), cost, (here, fuel))
        if point.price is None:
            continue

        per_mile = point.price / mpg
        # Value each arrival state as if its leftover fuel were refunded at this
        # station's price. The best state to buy from is then a running minimum.
        best_so_far: list[tuple[float, float]] = []
        running = (float("inf"), 0.0)
        for fuel in arrivals:
            running = min(running, (states[here][fuel][0] - fuel * per_mile, fuel))
            best_so_far.append(running)
        fill_value, fill_from = best_so_far[-1]

        for there in range(here + 1, last + 1):
            distance = points[there].mile - point.mile
            if distance > tank_range + EPSILON:
                break
            # Option 1: buy just enough to arrive empty.
            position = bisect_right(arrivals, distance + EPSILON) - 1
            if position >= 0:
                value, fuel = best_so_far[position]
                relax(there, 0.0, value + distance * per_mile + point.penalty, (here, fuel))
            # Option 2: fill the tank (pointless at the destination).
            if there != last:
                relax(
                    there,
                    tank_range - distance,
                    fill_value + tank_range * per_mile + point.penalty,
                    (here, fill_from),
                )

    if not states[last]:
        raise _gap_error(points, tank_range, start_range)

    # Walk back from the cheapest arrival at the destination.
    fuel = min(states[last], key=lambda f: states[last][f][0])
    index = last
    purchases: list[Purchase] = []
    while True:
        back = states[index][fuel][1]
        if back is None:
            break
        previous, previous_fuel = back
        distance = points[index].mile - points[previous].mile
        bought = fuel + distance - previous_fuel
        if bought > 1e-6:
            purchases.append(Purchase(index=previous, gallons=bought / mpg))
        index, fuel = previous, previous_fuel
    purchases.reverse()
    return purchases


def _gap_error(points: list[FuelPoint], tank_range: float, start_range: float) -> NoFeasiblePlan:
    """Locate the first stretch that cannot be crossed, for a useful error message."""
    reach = points[0].mile + (tank_range if points[0].price is not None else start_range)
    previous = points[0].mile
    for point in points[1:]:
        if point.mile > reach + EPSILON:
            return NoFeasiblePlan(previous, point.mile)
        if point.price is not None:
            previous = point.mile
            reach = point.mile + tank_range
    return NoFeasiblePlan(previous, points[-1].mile)
