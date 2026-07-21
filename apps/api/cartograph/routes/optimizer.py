"""Single-driver multi-stop sequencing: nearest-neighbor + 2-opt.

Pure algorithm over a precomputed travel-time matrix — no I/O here. The
pickup-before-delivery constraint is enforced both during construction
(nearest-neighbor only picks feasible stops) and during improvement (a 2-opt
reversal is rejected if it would put any delivery before its pickup).

For ≤ 20 stops a full 2-opt pass is O(N²) reversals × O(N) validity check,
comfortably under the 1-second budget; ``max_passes`` bounds pathological
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

StopKind = Literal["pickup", "delivery"]

# (from_vertex, to_vertex) -> seconds. Missing implies unreachable.
CostMatrix = dict[tuple[int, int], float]


class UnreachableStop(Exception):
    """Some stop can't be reached from another on the road network."""


@dataclass(frozen=True)
class Stop:
    order_id: UUID
    kind: StopKind
    vertex: int
    lng: float
    lat: float


def _cost(matrix: CostMatrix, u: int, v: int) -> float:
    """Missing pairs cost inf — reachability is asymmetric on real one-way
    road networks, and a candidate move touching an unreachable pair must be
    priced out, not abort the search. optimize_sequence raises only if the
    best final tour itself is unbuildable."""
    if u == v:
        return 0.0
    return matrix.get((u, v), float("inf"))


def _pickup_position(stops: list[Stop], order_id: UUID) -> int | None:
    for i, stop in enumerate(stops):
        if stop.order_id == order_id and stop.kind == "pickup":
            return i
    return None


def _precedence_pairs(stops: list[Stop]) -> list[tuple[int, int]]:
    """(pickup_index, delivery_index) for orders that have both stops."""
    pairs: list[tuple[int, int]] = []
    for i, stop in enumerate(stops):
        if stop.kind == "delivery":
            pickup = _pickup_position(stops, stop.order_id)
            if pickup is not None:
                pairs.append((pickup, i))
    return pairs


def _is_feasible(tour: list[int], pairs: list[tuple[int, int]]) -> bool:
    position = {stop_index: pos for pos, stop_index in enumerate(tour)}
    return all(position[p] < position[d] for p, d in pairs)


def tour_cost(matrix: CostMatrix, stops: list[Stop], start_vertex: int, tour: list[int]) -> float:
    total = 0.0
    prev = start_vertex
    for stop_index in tour:
        total += _cost(matrix, prev, stops[stop_index].vertex)
        prev = stops[stop_index].vertex
    return total


def _nearest_neighbor(
    matrix: CostMatrix, stops: list[Stop], start_vertex: int, first_choice: int = 0
) -> list[int]:
    """Greedy construction; ``first_choice`` > 0 starts from the k-th cheapest
    feasible first stop instead of the cheapest (multi-start diversity)."""
    remaining = set(range(len(stops)))
    tour: list[int] = []
    visited_pickups: set[UUID] = set()
    current = start_vertex

    while remaining:
        feasible = sorted(
            (
                i
                for i in remaining
                if stops[i].kind == "pickup"
                or _pickup_position(stops, stops[i].order_id) is None
                or stops[i].order_id in visited_pickups
            ),
            key=lambda i: _cost(matrix, current, stops[i].vertex),
        )
        rank = first_choice if not tour else 0
        best = feasible[min(rank, len(feasible) - 1)]
        tour.append(best)
        remaining.remove(best)
        if stops[best].kind == "pickup":
            visited_pickups.add(stops[best].order_id)
        current = stops[best].vertex

    return tour


def _two_opt_pass(
    matrix: CostMatrix,
    stops: list[Stop],
    start_vertex: int,
    tour: list[int],
    best_cost: float,
    pairs: list[tuple[int, int]],
) -> tuple[list[int], float, bool]:
    n = len(tour)
    improved = False
    for i in range(n - 1):
        for j in range(i + 1, n):
            candidate = tour[:i] + tour[i : j + 1][::-1] + tour[j + 1 :]
            if not _is_feasible(candidate, pairs):
                continue
            cost = tour_cost(matrix, stops, start_vertex, candidate)
            if cost < best_cost - 1e-9:
                tour, best_cost, improved = candidate, cost, True
    return tour, best_cost, improved


def _or_opt_pass(
    matrix: CostMatrix,
    stops: list[Stop],
    start_vertex: int,
    tour: list[int],
    best_cost: float,
    pairs: list[tuple[int, int]],
) -> tuple[list[int], float, bool]:
    """Relocate segments of 1–3 stops — escapes 2-opt's local optima."""
    n = len(tour)
    improved = False
    for length in (1, 2, 3):
        for i in range(n - length + 1):
            segment = tour[i : i + length]
            rest = tour[:i] + tour[i + length :]
            for k in range(len(rest) + 1):
                if k == i:
                    continue
                candidate = rest[:k] + segment + rest[k:]
                if not _is_feasible(candidate, pairs):
                    continue
                cost = tour_cost(matrix, stops, start_vertex, candidate)
                if cost < best_cost - 1e-9:
                    tour, best_cost, improved = candidate, cost, True
                    rest = tour[:i] + tour[i + length :]
                    segment = tour[i : i + length]
    return tour, best_cost, improved


def _local_search(
    matrix: CostMatrix,
    stops: list[Stop],
    start_vertex: int,
    tour: list[int],
    max_passes: int,
) -> tuple[list[int], float]:
    pairs = _precedence_pairs(stops)
    best_cost = tour_cost(matrix, stops, start_vertex, tour)
    for _ in range(max_passes):
        tour, best_cost, improved_2opt = _two_opt_pass(
            matrix, stops, start_vertex, tour, best_cost, pairs
        )
        tour, best_cost, improved_oropt = _or_opt_pass(
            matrix, stops, start_vertex, tour, best_cost, pairs
        )
        if not (improved_2opt or improved_oropt):
            break
    return tour, best_cost


def optimize_sequence(
    matrix: CostMatrix,
    stops: list[Stop],
    start_vertex: int,
    max_passes: int = 25,
) -> list[int]:
    """Return stop indices in visit order (near-optimal by travel time).

    Multi-start: nearest-neighbor from the k cheapest feasible first stops,
    each polished with alternating 2-opt / or-opt passes; best tour wins.
    """
    if not stops:
        return []

    starts = min(len(stops), 8)
    best_tour: list[int] | None = None
    best_cost = float("inf")
    for first_choice in range(starts):
        tour = _nearest_neighbor(matrix, stops, start_vertex, first_choice)
        tour, cost = _local_search(matrix, stops, start_vertex, tour, max_passes)
        if best_tour is None or cost < best_cost:
            best_tour, best_cost = tour, cost
    assert best_tour is not None
    if best_cost == float("inf"):
        raise UnreachableStop("No feasible tour: some stop is unreachable from the ones before it")
    return best_tour
