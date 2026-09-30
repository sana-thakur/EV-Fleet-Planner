import json

import pytest

from solver.heuristic import PlugTimeline, apply_overrides, solve_heuristic
from solver.instance import make_random_instance, make_toy_instance
from solver.plan_checker import check_plan


def _feasible(plan, inst):
    res = check_plan(plan, inst)
    assert res["feasible"], res["violations"]
    return res


def test_plug_timeline_slots():
    tl = PlugTimeline(1)
    tl.reserve(0, 10, 20, "A")
    assert tl.earliest_slot(0, 10) == (0, 0)  # fits before
    assert tl.earliest_slot(5, 10) == (0, 20)  # overlaps -> after
    assert tl.earliest_slot(5, 10, exclude="A") == (0, 5)
    tl.release_vehicle("A")
    assert tl.units == [[]]
    two = PlugTimeline(2)
    two.reserve(0, 0, 100, "A")
    assert two.earliest_slot(10, 5) == (1, 10)  # second unit free


def test_toy_feasible_and_rules():
    inst = make_toy_instance()
    plan, info = solve_heuristic(inst)
    res = _feasible(plan, inst)
    assert info["n_unserved"] == 0 and plan["unserved_customers"] == []
    assert res["summary"]["max_concurrent_charging"].get("S_01/LEV", 0) <= 1
    assert info["internal_cost"] == pytest.approx(470.0)  # MILP optimum, no queue wait (one 2W charges early)
    for r in plan["routes"]:
        if r["vehicle_id"].startswith("V_2W"):
            assert all(cs["plug_type_used"] == "LEV" for cs in r["charging_stops"])


def test_broken_charger_override():
    inst = make_toy_instance()
    plan, info = solve_heuristic(inst, station_overrides={"S_01": {"LEV": 0}})
    broken = apply_overrides(inst, {"S_01": {"LEV": 0}})
    _feasible(plan, broken)
    for r in plan["routes"]:
        if r["vehicle_id"].startswith("V_2W"):
            assert r["charging_stops"] == []
    assert info["n_unserved"] > 0  # the 2Ws can't reach the north customers without charging
    assert inst.plugs("S_01", "LEV") == 1  # original instance untouched


def test_deterministic():
    inst = make_random_instance(15, 5, seed=7)
    a = json.dumps(solve_heuristic(inst)[0], sort_keys=True)
    b = json.dumps(solve_heuristic(inst)[0], sort_keys=True)
    assert a == b


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_30_customers_fast_and_feasible(seed):
    inst = make_random_instance(30, 8, seed)
    plan, info = solve_heuristic(inst)
    assert info["runtime_s"] < 5
    _feasible(plan, inst)
