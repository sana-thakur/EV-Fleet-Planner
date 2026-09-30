import copy
import dataclasses

import pytest

from solver.instance import build_instance, make_random_instance, make_toy_instance
from solver.milp import _assign_units, explain_solution, solve_milp
from solver.plan_checker import check_plan


def _with_plugs(inst, station_id, plug, n):
    stations = copy.deepcopy(inst.stations)
    next(s for s in stations if s["station_id"] == station_id)["plugs"][plug] = n
    return dataclasses.replace(inst, stations=stations)


def _intervals(plan, inst):
    out = {}
    for r in plan["routes"]:
        for cs in r["charging_stops"]:
            start = cs["planned_charge_start"]
            end = start + inst.charge_minutes(cs["station_id"], cs["plug_type_used"], cs["energy_requested_kwh"])
            out.setdefault((cs["station_id"], cs["plug_type_used"]), []).append((start, end))
    return out


def _check_basic(plan, inst):
    served = [n for r in plan["routes"] for n in r["stop_sequence"] if n in inst.customer_window]
    assert sorted(served) == sorted(inst.customers)  # every customer exactly once
    for r in plan["routes"]:
        k, seq = r["vehicle_id"], r["stop_sequence"]
        battery = inst.vehicle(k)["battery_capacity_kwh"]
        charges = iter(r["charging_stops"])
        for u, v in zip(seq, seq[1:]):
            battery -= inst.energy(k, u, v)
            assert battery >= -1e-3, f"{k} battery negative at {v}"
            if isinstance(v, str):
                cs = next(charges)
                assert inst.compatible(k, cs["plug_type_used"])
                battery += cs["energy_requested_kwh"]
                assert battery <= inst.vehicle(k)["battery_capacity_kwh"] + 1e-3
    for (sid, p), ivs in _intervals(plan, inst).items():
        assert None not in _assign_units(sorted(ivs), inst.plugs(sid, p)), f"{sid} {p} overbooked"
    res = check_plan(plan, inst)
    assert res["feasible"], res["violations"]


@pytest.fixture(scope="module")
def toy_solution():
    inst = make_toy_instance()
    return inst, *solve_milp(inst, time_limit_s=60)


def test_toy_optimal(toy_solution):
    inst, plan, info = toy_solution
    assert info["status"] == "Optimal"
    assert info["objective_km"] == pytest.approx(470.0)
    assert info["runtime_s"] < 60
    _check_basic(plan, inst)


def test_toy_2w_never_on_ccs2(toy_solution):
    _, plan, _ = toy_solution
    for r in plan["routes"]:
        if r["vehicle_id"].startswith("V_2W"):
            assert all(cs["plug_type_used"] == "LEV" for cs in r["charging_stops"])
            assert len(r["charging_stops"]) == 1


def test_toy_single_lev_not_overlapping(toy_solution):
    inst, plan, _ = toy_solution
    (a0, a1), (b0, b1) = sorted(_intervals(plan, inst)[("S_01", "LEV")])
    assert a1 <= b0 + 1e-6


def test_toy_more_plugs_never_costs_more(toy_solution):
    inst, _, info = toy_solution
    _, info2 = solve_milp(_with_plugs(inst, "S_01", "LEV", 2), time_limit_s=60)
    assert info2["status"] == "Optimal"
    assert info2["objective_km"] <= info["objective_km"] + 1e-6


def _forced_overlap_instance(lev_plugs):
    """Two 2Ws, each MUST charge outbound at S_01 at t=80 to meet a tight window,
    so one LEV plug is infeasible and two are feasible. Needs 2 visits (charge again on return)."""
    coords = {0: (0, 0), 1: (-10, 80), 2: (10, 80), 9: (0, 40)}
    dist = {str(u): {str(v): float(abs(pu[0] - pv[0]) + abs(pu[1] - pv[1])) for v, pv in coords.items()} for u, pu in coords.items()}
    time = {u: {v: 2.0 * d for v, d in row.items()} for u, row in dist.items()}
    two_w = {"vehicle_type": "e-2W", "battery_capacity_kwh": 3.0, "energy_consumption_per_km": 0.025, "compatible_plugs": ["LEV"]}
    return build_instance(
        0,
        [{"node_id": c, "time_window": [185, 192], "service_time_min": 5} for c in (1, 2)],
        [{"station_id": "S_01", "node_id": 9, "plugs": {"LEV": lev_plugs, "CCS2": 1},
          "charge_rate_kwh_per_hour": {"LEV": 3.3, "CCS2": 30.0}}],
        [{"vehicle_id": "V_A", **two_w}, {"vehicle_id": "V_B", **two_w}],
        dist, time, horizon_min=480,
    )


def test_capacity_constraint_binds():
    plan, info = solve_milp(_forced_overlap_instance(1), time_limit_s=60, max_station_visits=2)
    assert info["status"] == "Infeasible"
    assert plan["routes"] == [] and sorted(plan["unserved_customers"]) == [1, 2]

    inst2 = _forced_overlap_instance(2)
    plan2, info2 = solve_milp(inst2, time_limit_s=60, max_station_visits=2)
    assert info2["status"] == "Optimal"
    _check_basic(plan2, inst2)
    starts = sorted(s for s, _ in _intervals(plan2, inst2)[("S_01", "LEV")])
    assert starts[0] == starts[1] == pytest.approx(80.0)  # both charge outbound in parallel


@pytest.mark.parametrize("n_c, n_v, seed", [(5, 2, 1), (5, 3, 2), (6, 3, 3)])
def test_random_small(n_c, n_v, seed):
    inst = make_random_instance(n_c, n_v, seed)
    plan, info = solve_milp(inst, time_limit_s=120)
    if info["status"] == "Infeasible":
        pytest.skip("random instance infeasible")
    assert info["status"] == "Optimal"
    _check_basic(plan, inst)


def test_explain_solution_runs(toy_solution):
    inst, plan, _ = toy_solution
    text = explain_solution(plan, inst)
    assert "OVERBOOKED" not in text and "S_01 LEV unit 0" in text


def test_toy_passes_plan_checker(toy_solution):
    inst, plan, _ = toy_solution
    res = check_plan(plan, inst)
    assert res["feasible"], res["violations"]
