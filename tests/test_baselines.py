"""
tests/test_baselines.py

Unit tests for solver/baselines.py (B1, B2, B3 Baseline Solvers).
"""

import copy
from solver.instance import make_toy_instance, make_random_instance, build_instance
from solver.baselines import solve_b1_greedy, solve_b2_capacity_blind, solve_b3_type_blind
from solver.plan_checker import check_plan
from solver.simulator import simulate_plan


def test_b2_capacity_blind_solver():
    inst = make_toy_instance()
    plan, info = solve_b2_capacity_blind(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert "unserved_customers" in plan
    assert info["baseline"] == "B2 (Capacity-Blind)"


def test_b2_capacity_blind_preserves_zero_plugs():
    # E7: Verify station plug capacity is set to 999 if n > 0 else 0
    inst = make_toy_instance()
    plan, info = solve_b2_capacity_blind(inst)
    
    # In toy instance, S_01 has Type2: 0. Ensure no route used Type2 at S_01.
    for r in plan["routes"]:
        for cs in r.get("charging_stops", []):
            if cs["station_id"] == "S_01":
                assert cs["plug_type_used"] != "Type2"


def test_b3_type_blind_solver():
    inst = make_toy_instance()
    plan, info = solve_b3_type_blind(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert info["baseline"] == "B3 (Type-Blind)"
    
    # E8: Check that charging stops mapped back to valid plug types that actually exist at the station
    for r in plan["routes"]:
        vid = r["vehicle_id"]
        compat = inst.vehicle(vid)["compatible_plugs"]
        for cs in r.get("charging_stops", []):
            assert cs["plug_type_used"] in compat
            assert inst.plugs(cs["station_id"], cs["plug_type_used"]) > 0


def test_b1_greedy_solver():
    inst = make_random_instance(n_customers=6, n_vehicles=2, seed=42)
    plan, info = solve_b1_greedy(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert info["baseline"] == "B1 (Greedy FCFS)"


def test_b1_greedy_toy_plan():
    # E4: Verify B1 produces valid route with charging on toy instance
    toy = make_toy_instance()
    plan, info = solve_b1_greedy(toy)
    
    check = check_plan(plan, toy)
    assert check["feasible"], f"B1 plan not feasible: {check['violations']}"
    
    sim_plan, sim_stats = simulate_plan(plan, toy)
    assert sim_stats["n_stranded_vehicles"] == 0
    assert sim_stats["total_wait_time_minutes"] > 0, "Expected non-zero wait time in toy under FCFS contention"


def test_b1_greedy_reports_constraint_failures_on_range_exhaustion():
    # E4: Verify exact range limit constraint failure is reported when vehicle battery is insufficient
    toy = make_toy_instance()
    vehicles = copy.deepcopy(toy.vehicles)
    # Set tiny battery capacity so vehicle cannot even reach nearest charger/customer
    for v in vehicles:
        v["battery_capacity_kwh"] = 0.001
        v["initial_soc"] = 0.01

    cust_list = [
        {"node_id": c, "time_window": list(toy.customer_window[c]), "service_time_min": toy.service_time[c]}
        for c in toy.customers
    ]
    starved_inst = build_instance(
        depot_node=toy.depot_node,
        customers=cust_list,
        stations=toy.stations,
        vehicles=vehicles,
        dist_km=toy.dist_km,
        time_min=toy.time_min,
        horizon_min=toy.horizon_min,
        depot_open_min=toy.depot_open_min,
    )

    plan, info = solve_b1_greedy(starved_inst)
    assert "constraint_failures" in info
    assert len(info["constraint_failures"]) > 0
    assert any("range limit failure" in f for f in info["constraint_failures"])
