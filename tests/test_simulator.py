"""
tests/test_simulator.py

Unit tests for solver/simulator.py (Reality Engine Discrete-Event Simulator).
"""

import pytest
from solver.instance import make_toy_instance, make_random_instance, build_instance
from solver.heuristic import solve_heuristic
from solver.milp import solve_milp
from solver.simulator import simulate_plan
from solver.plan_checker import check_plan
from solver.objective import calculate_route_cost


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


def test_no_competition_exact_match():
    """A plan with NO competition for plugs must simulate with exactly its planned arrival times, wait times, and cost (within float tolerance)."""
    inst = make_toy_instance()
    planned, info = solve_heuristic(inst)
    sim_plan, stats = simulate_plan(planned, inst)

    assert stats["n_stranded_vehicles"] == 0
    assert stats["unserved_customer_count"] == 0
    assert stats["total_wait_time_minutes"] == pytest.approx(0.0)

    # Check planned arrival times match actual arrival times within float tolerance
    for planned_r, sim_r in zip(planned["routes"], sim_plan["routes"]):
        assert len(sim_r["actual_arrival_times"]) == len(planned_r["planned_arrival_times"])
        for act, plan_t in zip(sim_r["actual_arrival_times"], planned_r["planned_arrival_times"]):
            assert act == pytest.approx(plan_t, abs=1e-3)
        for cs in sim_r["charging_stops"]:
            assert cs["wait_time_minutes"] == pytest.approx(0.0, abs=1e-3)

    # Check that route cost matches within float tolerance
    cust_windows = {str(k): list(v) for k, v in inst.customer_window.items()}
    cost_plan = calculate_route_cost(planned["routes"], inst.dist_km, cust_windows, planned.get("unserved_customers", []))
    cost_sim = calculate_route_cost(sim_plan["routes"], inst.dist_km, cust_windows, sim_plan.get("unserved_customers", []))
    assert cost_sim["total_score"] == pytest.approx(cost_plan["total_score"], abs=1e-3)
    assert cost_sim["wait_cost"] == pytest.approx(0.0, abs=1e-3)
    assert cost_sim["time_window_penalty_cost"] == pytest.approx(0.0, abs=1e-3)


def test_station_pass_through_without_charge():
    """(a) A route that passes through a station without a planned charge (no charge, no delay, no plug usage)."""
    inst = make_toy_instance()
    # V_2W_A passes through S_01 at t=80 without charging.
    # V_2W_B arrives at S_01 at t=80 with a planned charge on LEV.
    # S_01 has only 1 LEV plug. V_2W_B must NOT wait in queue.
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 325.0],
                "charging_stops": [],  # pass-through: no charge
            },
            {
                "vehicle_id": "V_2W_B",
                "stop_sequence": [0, "S_01", 2, 0],
                "planned_arrival_times": [0.0, 80.0, 178.18, 343.18],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 1.0,
                    }
                ],
            },
        ],
        "unserved_customers": [3, 4],
    }
    sim_plan, stats = simulate_plan(planned, inst)
    r_a = sim_plan["routes"][0]
    r_b = sim_plan["routes"][1]

    # V_2W_A has 0 delay at S_01: arrives at S_01 at 80, departs at 80, arrives at C1 at 160.0
    assert r_a["actual_arrival_times"][1] == pytest.approx(80.0, abs=1e-3)
    assert r_a["actual_arrival_times"][2] == pytest.approx(160.0, abs=1e-3)
    assert len(r_a["charging_stops"]) == 0

    # V_2W_A did not use a plug, so V_2W_B experiences 0 wait time despite arriving at the same time
    assert r_b["charging_stops"][0]["wait_time_minutes"] == pytest.approx(0.0, abs=1e-3)
    assert stats["total_wait_time_minutes"] == pytest.approx(0.0, abs=1e-3)


def test_pass_through_station_a_before_charge_at_station_b():
    """(b) A pass-through visit at station A before a planned charge at station B (charge must land on B)."""
    # Create an instance with 2 stations S_01 and S_02
    inst = make_random_instance(n_customers=4, n_vehicles=1, seed=42)
    # Vehicle visits S_01 (pass-through) then S_02 (planned charge)
    t0_s1 = inst.time(0, "S_01")
    t_s1_s2 = inst.time("S_01", "S_02")
    t_s2_0 = inst.time("S_02", 0)

    arr_s1 = t0_s1
    arr_s2 = arr_s1 + t_s1_s2  # 0 delay at S_01
    dur_charge = inst.charge_minutes("S_02", "LEV", 0.5)
    arr_depot = arr_s2 + dur_charge + t_s2_0

    planned = {
        "routes": [
            {
                "vehicle_id": "V_001",
                "stop_sequence": [0, "S_01", "S_02", 0],
                "planned_arrival_times": [0.0, arr_s1, arr_s2, arr_depot],
                "charging_stops": [
                    {
                        "station_id": "S_02",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": arr_s2,
                        "energy_requested_kwh": 0.5,
                    }
                ],
            }
        ],
        "unserved_customers": [1, 2, 3, 4],
    }

    sim_plan, stats = simulate_plan(planned, inst)
    r = sim_plan["routes"][0]
    assert len(r["charging_stops"]) == 1
    cs = r["charging_stops"][0]
    # Charge must land on S_02, NOT S_01!
    assert cs["station_id"] == "S_02"
    assert cs["actual_arrival_time"] == pytest.approx(arr_s2, abs=1e-3)
    assert cs["actual_charge_start"] == pytest.approx(arr_s2, abs=1e-3)
    assert cs["actual_charge_end"] == pytest.approx(arr_s2 + dur_charge, abs=1e-3)
    # S_01 had 0 delay
    assert r["actual_arrival_times"][1] == pytest.approx(arr_s1, abs=1e-3)
    assert r["actual_arrival_times"][2] == pytest.approx(arr_s2, abs=1e-3)


def test_same_station_visited_twice_by_one_vehicle():
    """(c) The same station visited twice by one vehicle."""
    inst = make_toy_instance()
    # Route: 0 -> S_01 (pass-through) -> C1 -> S_01 (charge) -> 0
    # First visit to S_01 is pass-through (arr 80.0, departs 80.0)
    # Arrival at C1: 160.0. Service: 5 min -> departs 165.0.
    # Second visit to S_01 is charge (arr 245.0)
    dur_charge = 60.0 * 1.0 / 3.3
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, "S_01", 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 245.0, 245.0 + dur_charge + 80.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 245.0,
                        "energy_requested_kwh": 1.0,
                    }
                ],
            }
        ],
        "unserved_customers": [2, 3, 4],
    }

    sim_plan, stats = simulate_plan(planned, inst)
    r = sim_plan["routes"][0]
    assert len(r["charging_stops"]) == 1
    cs = r["charging_stops"][0]

    # First visit (idx=1) was a pass-through: arrival 80.0, departs immediately at 80.0
    assert r["actual_arrival_times"][1] == pytest.approx(80.0, abs=1e-3)
    assert r["actual_arrival_times"][2] == pytest.approx(160.0, abs=1e-3)

    # Second visit (idx=3) received the planned charging stop: arrival 245.0
    assert r["actual_arrival_times"][3] == pytest.approx(245.0, abs=1e-3)
    assert cs["actual_arrival_time"] == pytest.approx(245.0, abs=1e-3)
    assert cs["actual_charge_start"] == pytest.approx(245.0, abs=1e-3)
    assert cs["actual_charge_end"] == pytest.approx(245.0 + dur_charge, abs=1e-3)
    assert r["actual_arrival_times"][4] == pytest.approx(245.0 + dur_charge + 80.0, abs=1e-3)


def test_customer_window_opens_late_holds_departure():
    """(d) Customer window opens late: vehicle holds departure at previous stop
    (depart_t = max(finish_t, window_open - travel_time)) and recorded arrival is >= window_open.
    Also verifies plug is released immediately upon charge completion and vehicle waits off-plug.
    """
    coords = {0: (0, 0), 1: (-10, 70), 2: (10, 70), 3: (0, -65), 4: (10, -65), 5: (0, 40)}
    dist = {str(u): {str(v): float(abs(pu[0] - pv[0]) + abs(pu[1] - pv[1])) for v, pv in coords.items()} for u, pu in coords.items()}
    time = {u: {v: 2.0 * d for v, d in row.items()} for u, row in dist.items()}
    # Customer 1 time window opens late at 200 (was 160)
    customers = [
        {"node_id": 1, "time_window": [200, 250], "service_time_min": 5},
        {"node_id": 2, "time_window": [160, 180], "service_time_min": 5},
        {"node_id": 3, "time_window": [130, 145], "service_time_min": 5},
        {"node_id": 4, "time_window": [150, 175], "service_time_min": 5},
    ]
    stations = [{
        "station_id": "S_01", "node_id": 5,
        "plugs": {"LEV": 1, "CCS2": 1, "Type2": 0},
        "charge_rate_kwh_per_hour": {"LEV": 3.3, "CCS2": 30.0, "Type2": 22.0},
    }]
    two_w = {"vehicle_type": "e-2W", "battery_capacity_kwh": 3.0, "energy_consumption_per_km": 0.025, "compatible_plugs": ["LEV"]}
    vehicles = [
        {"vehicle_id": "V_2W_A", **two_w},
        {"vehicle_id": "V_2W_B", **two_w},
        {"vehicle_id": "V_4W", "vehicle_type": "e-4W", "battery_capacity_kwh": 30.0,
         "energy_consumption_per_km": 0.15, "compatible_plugs": ["CCS2", "Type2"]},
    ]
    inst = build_instance(0, customers, stations, vehicles, dist, time, horizon_min=480)

    # V_2W_A: 0 -> S_01 -> 1 -> 0
    # Travels 0 -> S_01: arrival 80.0
    # Charges 1.0 kWh: dur = 60 * 1.0 / 3.3 = 18.1818 min
    # Charge finish_t = 98.1818 min. Plug released at 98.1818 min.
    # Travel S_01 -> 1 is 80 min.
    # Window open at 1 is 200 min.
    # Vehicle must hold departure at S_01 until depart_t = max(98.1818, 200 - 80) = 120.0 min!
    # Recorded actual_arrival_times at C1 must be >= 200.0 (exactly 200.0).
    dur_charge = 60.0 * 1.0 / 3.3
    charge_finish = 80.0 + dur_charge

    # V_2W_B: arrives at S_01 right when V_2W_A finishes charging (at charge_finish = 98.1818 min).
    # Since V_2W_A releases the plug immediately and waits off-plug, V_2W_B should experience 0 wait time!
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, 0],
                "planned_arrival_times": [0.0, 80.0, 200.0, 365.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 1.0,
                    }
                ],
            },
            {
                "vehicle_id": "V_2W_B",
                "stop_sequence": [0, "S_01", 2, 0],
                "planned_arrival_times": [0.0, charge_finish, charge_finish + dur_charge + 80.0, 360.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": charge_finish,
                        "energy_requested_kwh": 1.0,
                    }
                ],
            },
        ],
        "unserved_customers": [3, 4],
    }

    sim_plan, stats = simulate_plan(planned, inst)
    r_a = sim_plan["routes"][0]
    r_b = sim_plan["routes"][1]

    # Recorded arrival at C1 must be >= window_open (200.0)
    assert r_a["actual_arrival_times"][2] >= 200.0
    assert r_a["actual_arrival_times"][2] == pytest.approx(200.0, abs=1e-3)

    # Plug was released immediately at charge_finish (98.1818), so V_2W_B gets 0 queue wait
    assert r_b["charging_stops"][0]["wait_time_minutes"] == pytest.approx(0.0, abs=1e-3)


def test_charge_request_larger_than_remaining_battery_capacity():
    """(e) Charge request larger than remaining battery capacity."""
    inst = make_toy_instance()
    # V_2W_A has capacity 3.0 kWh. Initial battery is 3.0 kWh.
    # Leg 0 -> S_01 is 40 km * 0.025 = 1.0 kWh.
    # Battery on arrival at S_01 is 2.0 kWh. Remaining capacity is 1.0 kWh.
    # Plan requests 2.5 kWh charging (larger than remaining capacity of 1.0 kWh).
    planned = {
        "routes": [
            {
                "vehicle_id": "V_2W_A",
                "stop_sequence": [0, "S_01", 1, 0],
                "planned_arrival_times": [0.0, 80.0, 160.0, 325.0],
                "charging_stops": [
                    {
                        "station_id": "S_01",
                        "plug_type_used": "LEV",
                        "planned_arrival_time": 80.0,
                        "energy_requested_kwh": 2.5,
                    }
                ],
            }
        ],
        "unserved_customers": [2, 3, 4],
    }

    sim_plan, stats = simulate_plan(planned, inst)
    r = sim_plan["routes"][0]
    cs = r["charging_stops"][0]

    # Absorbed energy must be capped at 1.0 kWh (3.0 - 2.0).
    # Duration must be strictly computed from 1.0 kWh: 60 * 1.0 / 3.3 = 18.1818 min
    expected_dur = 60.0 * 1.0 / 3.3
    actual_dur = cs["actual_charge_end"] - cs["actual_charge_start"]
    assert actual_dur == pytest.approx(expected_dur, abs=1e-3)

