"""
tests/test_baselines.py

Unit tests for solver/baselines.py (B1, B2, B3 Baseline Solvers).
"""

from solver.instance import make_toy_instance, make_random_instance
from solver.baselines import solve_b1_greedy, solve_b2_capacity_blind, solve_b3_type_blind
from solver.plan_checker import check_plan


def test_b2_capacity_blind_solver():
    inst = make_toy_instance()
    plan, info = solve_b2_capacity_blind(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert "unserved_customers" in plan
    assert info["baseline"] == "B2 (Capacity-Blind)"


def test_b3_type_blind_solver():
    inst = make_toy_instance()
    plan, info = solve_b3_type_blind(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert info["baseline"] == "B3 (Type-Blind)"
    
    # Check that charging stops mapped back to valid plug types
    for r in plan["routes"]:
        vid = r["vehicle_id"]
        compat = inst.vehicle(vid)["compatible_plugs"]
        for cs in r.get("charging_stops", []):
            assert cs["plug_type_used"] in compat


def test_b1_greedy_solver():
    inst = make_random_instance(n_customers=6, n_vehicles=2, seed=42)
    plan, info = solve_b1_greedy(inst)
    
    assert isinstance(plan, dict)
    assert "routes" in plan
    assert info["baseline"] == "B1 (Greedy FCFS)"
