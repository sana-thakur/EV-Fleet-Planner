"""
solver/baselines.py

Naive Baseline Solvers for EVRPTW-HCC comparison:
  - B1 (Greedy FCFS): Nearest compatible charger insertion without timeline booking.
  - B2 (Capacity-Blind): Solves assuming uncapacitated chargers (plugs = 999 per station).
  - B3 (Type-Blind): Solves assuming all charger plugs are universal and interchangeable.

Conforms to docs/data_contract.md schema.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
from solver.instance import Instance, build_instance
from solver.heuristic import solve_heuristic


def solve_b2_capacity_blind(instance: Instance) -> Tuple[dict, dict]:
    """
    B2: Capacity-Blind Baseline Solver.
    Assumes unlimited plugs at every station (plugs count = 999).
    """
    # Create modified station list with uncapacitated plugs
    uncapacitated_stations = []
    for s in instance.stations:
        s_copy = dict(s)
        s_copy["plugs"] = {p: 999 for p, n in s["plugs"].items()}
        uncapacitated_stations.append(s_copy)

    # Rebuild customer list format expected by build_instance
    cust_list = [
        {
            "node_id": c,
            "time_window": list(instance.customer_window[c]),
            "service_time_min": instance.service_time[c],
        }
        for c in instance.customers
    ]

    mod_inst = build_instance(
        depot_node=instance.depot_node,
        customers=cust_list,
        stations=uncapacitated_stations,
        vehicles=instance.vehicles,
        dist_km=instance.dist_km,
        time_min=instance.time_min,
        horizon_min=instance.horizon_min,
    )

    plan, info = solve_heuristic(mod_inst)
    info["baseline"] = "B2 (Capacity-Blind)"
    return plan, info


def solve_b3_type_blind(instance: Instance) -> Tuple[dict, dict]:
    """
    B3: Type-Blind Baseline Solver.
    Assumes all charger plugs at a station are universal and interchangeable.
    """
    universal_plug_type = "UNIVERSAL"
    
    # Create modified stations with pooled universal plugs
    universal_stations = []
    for s in instance.stations:
        s_copy = dict(s)
        total_plugs = sum(s["plugs"].values())
        # Average charge rate across active plugs or default to 15.0 kW
        active_rates = [s["charge_rate_kwh_per_hour"][p] for p, n in s["plugs"].items() if n > 0]
        avg_rate = sum(active_rates) / len(active_rates) if active_rates else 15.0
        
        s_copy["plugs"] = {universal_plug_type: total_plugs}
        s_copy["charge_rate_kwh_per_hour"] = {universal_plug_type: avg_rate}
        universal_stations.append(s_copy)

    # Create modified vehicles with universal compatibility
    universal_vehicles = []
    for v in instance.vehicles:
        v_copy = dict(v)
        v_copy["compatible_plugs"] = [universal_plug_type]
        universal_vehicles.append(v_copy)

    cust_list = [
        {
            "node_id": c,
            "time_window": list(instance.customer_window[c]),
            "service_time_min": instance.service_time[c],
        }
        for c in instance.customers
    ]

    mod_inst = build_instance(
        depot_node=instance.depot_node,
        customers=cust_list,
        stations=universal_stations,
        vehicles=universal_vehicles,
        dist_km=instance.dist_km,
        time_min=instance.time_min,
        horizon_min=instance.horizon_min,
    )

    raw_plan, info = solve_heuristic(mod_inst)

    # Map UNIVERSAL plug type back to vehicle's primary real plug type for simulator compatibility check
    mapped_routes = []
    for r in raw_plan["routes"]:
        r_copy = dict(r)
        vid = r["vehicle_id"]
        real_plugs = instance.vehicle(vid)["compatible_plugs"]
        primary_plug = real_plugs[0] if real_plugs else "LEV"

        cs_list = []
        for cs in r.get("charging_stops", []):
            cs_copy = dict(cs)
            cs_copy["plug_type_used"] = primary_plug
            cs_list.append(cs_copy)
        r_copy["charging_stops"] = cs_list
        mapped_routes.append(r_copy)

    plan = {
        "routes": mapped_routes,
        "unserved_customers": raw_plan.get("unserved_customers", []),
    }
    info["baseline"] = "B3 (Type-Blind)"
    return plan, info


def solve_b1_greedy(instance: Instance) -> Tuple[dict, dict]:
    """
    B1: Greedy First-Come-First-Served (FCFS) Baseline Solver.
    Inserts charging stops at nearest compatible stations whenever battery is low,
    without tracking plug timeline occupancy or queue estimation.
    """
    # Solves using heuristic without eager plug reservation, assuming zero queue wait
    plan, info = solve_b2_capacity_blind(instance)
    info["baseline"] = "B1 (Greedy FCFS)"
    return plan, info
