import json
import os

import pytest

from solver.instance import build_instance

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "thane_benchmark.json")

pytestmark = pytest.mark.skipif(not os.path.exists(PATH) or os.path.getsize(PATH) == 0,
                                reason="run data_pipeline/generate_thane_network.py first")


@pytest.fixture(scope="module")
def bench():
    with open(PATH) as f:
        return json.load(f)


def test_structure_and_metadata(bench):
    assert set(bench) >= {"nodes", "edges", "distance_matrix", "time_matrix", "metadata"}
    m = bench["metadata"]
    assert m["crs"] == "EPSG:4326" and len(m["bbox"]) == 4
    assert m["node_count"] == len(bench["nodes"]) > 1000
    assert m["edge_count"] > m["node_count"]
    assert str(m["depot_node"]) in bench["distance_matrix"]
    assert all(str(n) in bench["distance_matrix"] for n in m["customer_pool"] + m["station_nodes"])
    north, south, east, west = m["bbox"]
    for n in bench["nodes"].values():
        assert south - 0.01 <= n["lat"] <= north + 0.01 and west - 0.01 <= n["lon"] <= east + 0.01


def test_matrices(bench):
    dist, time = bench["distance_matrix"], bench["time_matrix"]
    assert set(dist) == set(time)
    speed_km_per_min = bench["metadata"]["speed_kmh"] / 60
    for u, row in dist.items():
        assert isinstance(u, str) and set(row) == set(dist)
        assert row[u] == 0
        for v, d in row.items():
            assert d >= 0 and time[u][v] >= 0
            if u != v:
                assert d > 0
                assert abs(d / time[u][v] - speed_km_per_min) / speed_km_per_min < 0.10
                # one-way streets make it asymmetric, but not wildly
                assert dist[v][u] <= 3 * d + 1.0


def test_loads_into_workstream_a_instance(bench):
    m = bench["metadata"]
    pool = m["customer_pool"][:3]
    inst = build_instance(
        depot_node=m["depot_node"],
        customers=[{"node_id": c, "time_window": [540, 1020], "service_time_min": 5} for c in pool],
        stations=[{"station_id": "S_test", "node_id": m["customer_pool"][-1], "plugs": {"LEV": 1},
                   "charge_rate_kwh_per_hour": {"LEV": 3.3}}],
        vehicles=[{"vehicle_id": "V", "vehicle_type": "e-2W", "battery_capacity_kwh": 3.0,
                   "energy_consumption_per_km": 0.025, "compatible_plugs": ["LEV"]}],
        dist_km=bench["distance_matrix"],
        time_min=bench["time_matrix"],
    )
    assert inst.dist(m["depot_node"], "S_test") == bench["distance_matrix"][str(m["depot_node"])][str(m["customer_pool"][-1])]
