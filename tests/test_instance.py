import copy

import pytest

from solver.instance import build_instance, make_random_instance, make_toy_instance


def _raw():
    dist = {"0": {"0": 0.0, "1": 10.0, "9": 5.0}, "1": {"0": 10.0, "1": 0.0, "9": 5.0}, "9": {"0": 5.0, "1": 5.0, "9": 0.0}}
    return dict(
        depot_node=0,
        customers=[{"node_id": 1, "time_window": [0, 100], "service_time_min": 5}],
        stations=[{"station_id": "S_01", "node_id": 9, "plugs": {"LEV": 1, "CCS2": 0},
                   "charge_rate_kwh_per_hour": {"LEV": 3.3, "CCS2": 30.0}}],
        vehicles=[{"vehicle_id": "V_1", "vehicle_type": "e-2W", "battery_capacity_kwh": 3.0,
                   "energy_consumption_per_km": 0.025, "compatible_plugs": ["LEV"]}],
        dist_km=dist,
        time_min=copy.deepcopy(dist),
    )


def test_valid_raw_builds_and_aliases_station():
    inst = build_instance(**_raw())
    assert inst.dist("S_01", 1) == inst.dist(9, 1) == 5.0
    assert inst.dist_km["0"]["S_01"] == 5.0
    assert inst.horizon_min == 220


@pytest.mark.parametrize("mutate, msg", [
    (lambda r: r.update(depot_node=42), "depot node 42"),
    (lambda r: r["customers"][0].update(node_id=77), "customer node 77"),
    (lambda r: r["customers"][0].update(time_window=[50, 10]), "a=50 > b=10"),
    (lambda r: r["stations"][0].update(node_id=88), "node 88"),
    (lambda r: r["vehicles"][0].update(compatible_plugs=["CCS2"]), "no compatible plug"),
])
def test_validation_errors(mutate, msg):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValueError, match=msg):
        build_instance(**raw)


def test_toy_2w_range_forces_charge():
    inst = make_toy_instance()
    for c in (1, 2):
        for v in ("V_2W_A", "V_2W_B"):
            round_trip = inst.energy(v, 0, c) + inst.energy(v, c, 0)
            assert round_trip > inst.vehicle(v)["battery_capacity_kwh"]
            # but reachable via S_01 with one charge (station on a shortest path)
            assert inst.energy(v, 0, "S_01") <= 3.0 and inst.energy(v, "S_01", c) + inst.energy(v, c, "S_01") <= 3.0
            assert inst.dist(0, "S_01") + inst.dist("S_01", c) == inst.dist(0, c)
    # south cluster is out of 2W range, fine for the 4W without charging
    south = inst.dist(0, 3) + inst.dist(3, 4) + inst.dist(4, 0)
    assert south * 0.025 > 3.0 and south * 0.15 < 30.0


def test_toy_plug_rules():
    inst = make_toy_instance()
    assert inst.usable_plugs("V_2W_A", "S_01") == ["LEV"]
    assert inst.usable_plugs("V_4W", "S_01") == ["CCS2"]  # Type2 has 0 plugs
    assert inst.plugs("S_01", "LEV") == 1
    assert abs(inst.charge_minutes("S_01", "LEV", 1.0) - 18.1818) < 1e-3


def test_random_instance_deterministic():
    a, b = make_random_instance(6, 3, seed=1), make_random_instance(6, 3, seed=1)
    assert a.dist_km == b.dist_km and a.customer_window == b.customer_window
    assert len(a.customers) == 6 and len(a.vehicles) == 3
