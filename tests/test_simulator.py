"""
tests/test_simulator.py

Unit tests for solver/simulator.py (Reality Engine Discrete-Event Simulator).
"""

import pytest
from solver.instance import make_toy_instance, make_random_instance
from solver.heuristic import solve_heuristic
from solver.milp import solve_milp
from solver.simulator import simulate_plan
from solver.plan_checker import check_plan


def test_toy_instance_simulation():
    """Verify that the optimal plan on the toy instance passes through simulation with zero queue wait."""
    inst = make_toy_instance()
    planned, info = solve_heuristic(inst)
    
    sim_plan, stats = simulate_plan(planned, inst)
    
    assert stats["n_stranded_vehicles"] == 0
    assert stats["unserved_customer_count"] == 0
    # On the toy instance, the timeline-aware heuristic scheduled charges so there is 0 queue wait
    assert stats["total_wait_time_minutes"] == 0.0


def test_fifo_queueing_bottleneck():
    """Verify strict FIFO queueing when 2 vehicles contend for 1 single plug at the exact same time."""
    inst = make_toy_instance()
    
    # Construct a synthetic capacity-blind plan where 2 LEV vehicles arrive at S_01 at t=80
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 300.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 1.0,
                    }
                ]
            },
            {
                "vehicle_id": "V_2W_B",
                "stop_sequence": [0, "S_01", 2, 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 300.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 1.0,
                    }
                ]
            }
        ],
        "unserved_customers": [3, 4]
    }
    
    sim_plan, stats = simulate_plan(planned, inst)
    
    # Plug rate = 3.3 kW/h -> 1.0 kWh takes 60 * 1.0 / 3.3 = 18.1818 minutes
    dur = 60.0 * 1.0 / 3.3
    assert stats["total_wait_time_minutes"] == pytest.approx(dur, abs=0.01)
    
    # Check that one vehicle got wait = 0 and the second got wait = dur
    waits = [cs["wait_time_minutes"] for r in sim_plan["routes"] for cs in r["charging_stops"]]
    assert sorted(waits) == [pytest.approx(0.0), pytest.approx(dur, abs=0.01)]


def test_plug_type_isolation():
    """Verify that a 4W vehicle on CCS2 does not queue behind or block a 2W vehicle on LEV."""
    inst = make_toy_instance()
    
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 300.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 1.0,
                    }
                ]
            },
            {
                "vehicle_id": "V_4W",
                "stop_sequence": [0, "S_01", 3, 0],
                "planned_arrival_times": [0.0, 80.0, 150.0, 300.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "CCS2",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 5.0,
                    }
                ]
            }
        ],
        "unserved_customers": [2, 4]
    }
    
    sim_plan, stats = simulate_plan(planned, inst)
    
    # Both use different plug types, so zero wait time for both!
    assert stats["total_wait_time_minutes"] == 0.0


def test_battery_stranding():
    """Verify that a route exceeding vehicle battery range marks the vehicle stranded."""
    inst = make_toy_instance()
    
    # Route V_2W_A to C3 (0, -65) then C1 (-10, 70) without charging -> leg 3->1 is 145 km (3.625 kWh > 1.375 kWh remaining)
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, 3, 1, 0],
                "planned_arrival_times": [0.0, 130.0, 400.0, 600.0],
                "charging_stops": []
            }
        ],
        "unserved_customers": [2, 4]
    }
    
    sim_plan, stats = simulate_plan(planned, inst)
    
    assert stats["n_stranded_vehicles"] == 1
    # Customer 1 was on the leg where battery ran out, so it becomes unserved
    assert 1 in sim_plan["unserved_customers"]


def test_random_instances_simulation():
    """Verify simulation runs without error on random benchmark instances."""
    inst = make_random_instance(n_customers=8, n_vehicles=3, seed=42)
    plan, info = solve_heuristic(inst)
    
    sim_plan, stats = simulate_plan(plan, inst)
    assert isinstance(sim_plan, dict)
    assert "routes" in sim_plan
    assert "unserved_customers" in sim_plan
