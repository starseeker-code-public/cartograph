"""Pure optimizer unit tests (Phase 7): quality vs brute force, precedence.

These need no database — the matrix is synthetic Euclidean.
"""

from __future__ import annotations

import math
import random
import time
from itertools import permutations
from uuid import uuid4

from cartograph.routes.optimizer import (
    CostMatrix,
    Stop,
    optimize_sequence,
    tour_cost,
)

START_VERTEX = 0


def _euclidean_matrix(coords: dict[int, tuple[float, float]]) -> CostMatrix:
    matrix: CostMatrix = {}
    for u, (ux, uy) in coords.items():
        for v, (vx, vy) in coords.items():
            if u != v:
                matrix[(u, v)] = math.hypot(ux - vx, uy - vy)
    return matrix


def _random_problem(
    n_orders: int, rng: random.Random, paired: bool = True
) -> tuple[CostMatrix, list[Stop]]:
    coords: dict[int, tuple[float, float]] = {START_VERTEX: (0.0, 0.0)}
    stops: list[Stop] = []
    vertex = 1
    for _ in range(n_orders):
        order_id = uuid4()
        if paired:
            coords[vertex] = (rng.uniform(0, 100), rng.uniform(0, 100))
            stops.append(Stop(order_id=order_id, kind="pickup", vertex=vertex, lng=0, lat=0))
            vertex += 1
        coords[vertex] = (rng.uniform(0, 100), rng.uniform(0, 100))
        stops.append(Stop(order_id=order_id, kind="delivery", vertex=vertex, lng=0, lat=0))
        vertex += 1
    return _euclidean_matrix(coords), stops


def _brute_force_cost(matrix: CostMatrix, stops: list[Stop]) -> float:
    pickup_pos = {s.order_id: i for i, s in enumerate(stops) if s.kind == "pickup"}
    best = math.inf
    for perm in permutations(range(len(stops))):
        order_seen: set[int] = set()
        ok = True
        for stop_index in perm:
            stop = stops[stop_index]
            if (
                stop.kind == "delivery"
                and stop.order_id in pickup_pos
                and pickup_pos[stop.order_id] not in order_seen
            ):
                ok = False
                break
            order_seen.add(stop_index)
        if ok:
            best = min(best, tour_cost(matrix, stops, START_VERTEX, list(perm)))
    return best


def _assert_precedence(stops: list[Stop], tour: list[int]) -> None:
    seen_pickups: set[object] = set()
    for stop_index in tour:
        stop = stops[stop_index]
        if stop.kind == "pickup":
            seen_pickups.add(stop.order_id)
        elif any(s.kind == "pickup" and s.order_id == stop.order_id for s in stops):
            assert stop.order_id in seen_pickups, "delivery before its pickup"


def test_within_5_percent_of_brute_force_delivery_only() -> None:
    """7 unpaired stops — the DoD quality bar."""
    for seed in range(8):
        rng = random.Random(seed)
        matrix, stops = _random_problem(7, rng, paired=False)
        tour = optimize_sequence(matrix, stops, START_VERTEX)
        cost = tour_cost(matrix, stops, START_VERTEX, tour)
        optimal = _brute_force_cost(matrix, stops)
        assert cost <= optimal * 1.05, f"seed {seed}: {cost} vs optimal {optimal}"


def test_within_5_percent_of_brute_force_paired() -> None:
    """3 orders = 6 stops with pickup→delivery precedence."""
    for seed in range(8):
        rng = random.Random(seed)
        matrix, stops = _random_problem(3, rng, paired=True)
        tour = optimize_sequence(matrix, stops, START_VERTEX)
        _assert_precedence(stops, tour)
        cost = tour_cost(matrix, stops, START_VERTEX, tour)
        optimal = _brute_force_cost(matrix, stops)
        assert cost <= optimal * 1.05, f"seed {seed}: {cost} vs optimal {optimal}"


def test_precedence_holds_on_larger_instances() -> None:
    for seed in range(5):
        rng = random.Random(100 + seed)
        matrix, stops = _random_problem(10, rng, paired=True)  # 20 stops
        tour = optimize_sequence(matrix, stops, START_VERTEX)
        assert sorted(tour) == list(range(len(stops)))
        _assert_precedence(stops, tour)


def test_20_stops_under_one_second() -> None:
    rng = random.Random(42)
    matrix, stops = _random_problem(10, rng, paired=True)  # 20 stops
    started = time.perf_counter()
    optimize_sequence(matrix, stops, START_VERTEX)
    assert time.perf_counter() - started < 1.0


def test_empty_and_single_stop() -> None:
    assert optimize_sequence({}, [], START_VERTEX) == []

    coords = {START_VERTEX: (0.0, 0.0), 1: (1.0, 1.0)}
    stops = [Stop(order_id=uuid4(), kind="delivery", vertex=1, lng=0, lat=0)]
    assert optimize_sequence(_euclidean_matrix(coords), stops, START_VERTEX) == [0]
