"""
solver/baselines.py

Naive Baseline Solvers for EVRPTW-HCC comparison:
  - B1 (Greedy FCFS): Nearest compatible charger insertion on demand with linear plug queueing.
  - B2 (Capacity-Blind): Solves assuming uncapacitated chargers (plugs = 999 per active plug type).
  - B3 (Type-Blind): Solves assuming all charger plugs at a station are interchangeable while maintaining true vehicle rates.

Conforms to docs/data_contract.md schema.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from solver.instance import Instance, build_instance
from solver.heuristic import solve_heuristic, _orderings


def solve_b2_capacity_blind(instance: Instance) -> Tuple[dict, dict]:
    """
    B2: Capacity-Blind Baseline Solver.
    Assumes unlimited plugs for active plug types at every station (plugs count = 999 if n > 0 else 0).
    """
    uncapacitated_stations = []
    for s in instance.stations:
        s_copy = dict(s)
        # E7: Set station plug capacity to 999 if n > 0 else 0 to prevent assigning non-existent plug types
        s_copy["plugs"] = {p: (999 if n > 0 else 0) for p, n in s["plugs"].items()}
        uncapacitated_stations.append(s_copy)

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
        depot_open_min=instance.depot_open_min,
    )

    plan, info = solve_heuristic(mod_inst)
    info["baseline"] = "B2 (Capacity-Blind)"
    return plan, info


def solve_b3_type_blind(instance: Instance) -> Tuple[dict, dict]:
    """
    B3: Type-Blind Baseline Solver.
    Assumes all charger plugs that exist at a station are interchangeable (pooled capacity),
    while maintaining vehicles' true charging rates and selecting plug types that actually exist.
    """
    type_blind_stations = []
    for s in instance.stations:
        s_copy = dict(s)
        total_plugs = sum(n for n in s["plugs"].values() if n > 0)
        # E8: Set capacity of active plugs to total_plugs, preserving 0 for non-existent plugs,
        # and keeping the true charging rates per plug type.
        s_copy["plugs"] = {p: (total_plugs if n > 0 else 0) for p, n in s["plugs"].items()}
        type_blind_stations.append(s_copy)

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
        stations=type_blind_stations,
        vehicles=instance.vehicles,
        dist_km=instance.dist_km,
        time_min=instance.time_min,
        horizon_min=instance.horizon_min,
        depot_open_min=instance.depot_open_min,
    )

    plan, info = solve_heuristic(mod_inst)

    # E8: Ensure every charging stop selects a compatible plug type that actually exists at the station
    for r in plan["routes"]:
        vid = r["vehicle_id"]
        compat = instance.vehicle(vid)["compatible_plugs"]
        for cs in r.get("charging_stops", []):
            sid = cs["station_id"]
            usable = [p for p in compat if instance.plugs(sid, p) > 0]
            if cs["plug_type_used"] not in usable and usable:
                cs["plug_type_used"] = max(usable, key=lambda p: instance.rate(sid, p))

    info["baseline"] = "B3 (Type-Blind)"
    return plan, info


def _simulate_route_b1(
    inst: Instance,
    vehicle_id: str,
    customers: List[Any],
    plug_free_times: Dict[Tuple[str, str], List[float]],
) -> Tuple[Optional[dict], List[str]]:
    """
    Simulate a vehicle route greedily: on-demand insertion of nearest compatible charger,
    first-come-first-served with linear plug queueing.
    Returns (route_dict, constraint_failures).
    """
    v_info = inst.vehicle(vehicle_id)
    q = v_info["battery_capacity_kwh"]
    e = lambda u, v: inst.energy(vehicle_id, u, v)

    compatible_stations = [s["station_id"] for s in inst.stations if inst.usable_plugs(vehicle_id, s["station_id"])]
    safe_points = compatible_stations + [inst.depot_node]
    targets = list(customers) + [inst.depot_node]

    after_kwh = [0.0] * len(targets)
    for i in range(len(targets) - 2, -1, -1):
        after_kwh[i] = after_kwh[i + 1] + e(targets[i], targets[i + 1])

    cur = inst.depot_node
    ready = inst.depot_open_min
    battery = inst.initial_battery(vehicle_id)

    stops = [inst.depot_node]
    times = [inst.depot_open_min]
    charging_stops = []
    failures = []

    for idx, target in enumerate(targets):
        is_last = (idx == len(targets) - 1)
        reserve = 0.0 if is_last else min(e(target, p) for p in safe_points)

        for attempt in range(3):
            forced = (battery - e(cur, target) < reserve - 1e-9)
            if not forced:
                break

            # Nearest reachable compatible charger
            reachable = [sid for sid in compatible_stations if sid != cur and e(cur, sid) <= battery + 1e-9]
            if not reachable:
                min_need = min((e(cur, s) for s in compatible_stations if s != cur), default=0.0)
                failures.append(
                    f"Vehicle {vehicle_id} range limit failure at node {cur}: battery {battery:.2f} kWh < {min_need:.2f} kWh needed to reach nearest charger"
                )
                return None, failures

            sid = min(reachable, key=lambda s: inst.dist(cur, s))

            travel_t = inst.time(cur, sid)
            battery -= e(cur, sid)
            arr_t = ready + travel_t

            remaining_needed = e(sid, target) + after_kwh[idx]
            kwh = round(min(q - battery, max(0.0, remaining_needed * 1.05 - battery)), 4)
            if kwh <= 1e-4:
                kwh = round(min(q - battery, e(sid, target) + reserve - battery), 4)
            if kwh <= 1e-4:
                kwh = round(q - battery, 4)

            usable = inst.usable_plugs(vehicle_id, sid)
            p = max(usable, key=lambda plug: inst.rate(sid, plug))

            units = plug_free_times.get((sid, p), [inst.depot_open_min])
            earliest_free = min(units)
            unit_idx = units.index(earliest_free)

            start = max(arr_t, earliest_free)
            wait = start - arr_t
            dur = inst.charge_minutes(sid, p, kwh)
            end = start + dur
            units[unit_idx] = end

            battery = min(q, battery + kwh)
            ready = end
            cur = sid

            stops.append(sid)
            times.append(round(arr_t, 4))
            charging_stops.append({
                "station_id": sid,
                "plug_type_used": p,
                "planned_arrival_time": round(arr_t, 4),
                "actual_arrival_time": round(arr_t, 4),
                "wait_time_minutes": round(wait, 4),
                "energy_requested_kwh": kwh,
                "planned_charge_start": round(start, 4),
            })

        if battery - e(cur, target) < reserve - 1e-4:
            failures.append(
                f"Vehicle {vehicle_id} range limit failure: cannot safely reach {target} from {cur} (battery {battery:.2f} kWh)"
            )
            return None, failures

        travel_t = inst.time(cur, target)
        battery -= e(cur, target)
        arr_t = ready + travel_t

        if not is_last:
            a, b = inst.customer_window[target]
            arr_t = max(arr_t, a)
            if arr_t > b + 1e-9:
                return None, [f"Vehicle {vehicle_id} late arrival at customer {target} ({arr_t:.2f} > {b:.2f})"]
            ready = arr_t + inst.service_time[target]
        else:
            if arr_t > inst.horizon_min + 1e-9:
                return None, [f"Vehicle {vehicle_id} exceeded horizon at depot ({arr_t:.2f} > {inst.horizon_min:.2f})"]
            ready = arr_t

        stops.append(target)
        times.append(round(arr_t, 4))
        cur = target

    route_dict = {
        "vehicle_id": vehicle_id,
        "stop_sequence": stops,
        "planned_arrival_times": times,
        "actual_arrival_times": list(times),
        "charging_stops": charging_stops,
        "stranded": False,
        "stranding_reason": None,
    }
    return route_dict, []


def solve_b1_greedy(instance: Instance) -> Tuple[dict, dict]:
    """
    B1: Greedy First-Come-First-Served (FCFS) Baseline Solver.
    Inserts charging stops at nearest compatible stations on demand whenever battery is low,
    with linear plug queueing (first-come, first-served).
    Reports exact constraint failures if routes are infeasible due to range limits.
    """
    t0 = time.perf_counter()
    best_plan = None
    best_score = float("inf")
    all_failures = []

    for order in _orderings(instance):
        routes_cust = {v["vehicle_id"]: [] for v in instance.vehicles}
        unserved = []

        for c in order:
            best_choice = None
            best_cost = float("inf")

            for vid in routes_cust:
                seq = routes_cust[vid]
                for pos in range(len(seq) + 1):
                    cand_seq = seq[:pos] + [c] + seq[pos:]
                    # Tentative evaluation with independent plug queue
                    test_queues = {
                        (s["station_id"], p): [instance.depot_open_min] * n
                        for s in instance.stations for p, n in s["plugs"].items() if n > 0
                    }
                    r_dict, fails = _simulate_route_b1(instance, vid, cand_seq, test_queues)
                    if fails:
                        all_failures.extend(fails)
                    if r_dict is not None:
                        stops = r_dict["stop_sequence"]
                        dist_val = sum(instance.dist(stops[i], stops[i+1]) for i in range(len(stops) - 1))
                        wait_val = sum(cs.get("wait_time_minutes", 0.0) for cs in r_dict["charging_stops"])
                        score = dist_val + 0.5 * wait_val
                        if score < best_cost:
                            best_cost = score
                            best_choice = (vid, cand_seq)

            if best_choice is not None:
                routes_cust[best_choice[0]] = best_choice[1]
            else:
                unserved.append(c)

        # Re-simulate all vehicles together in fleet order with shared linear plug queues
        plug_free_times = {
            (s["station_id"], p): [instance.depot_open_min] * n
            for s in instance.stations for p, n in s["plugs"].items() if n > 0
        }
        final_routes = []
        for v in instance.vehicles:
            vid = v["vehicle_id"]
            custs = routes_cust[vid]
            if not custs:
                continue
            r_dict, fails = _simulate_route_b1(instance, vid, custs, plug_free_times)
            if fails:
                all_failures.extend(fails)
            if r_dict is not None:
                final_routes.append(r_dict)
            else:
                unserved.extend(custs)

        total_km = sum(instance.dist(r["stop_sequence"][i], r["stop_sequence"][i+1])
                       for r in final_routes for i in range(len(r["stop_sequence"]) - 1))
        order_score = total_km + len(unserved) * 5000.0
        if order_score < best_score:
            best_score = order_score
            best_plan = {
                "routes": final_routes,
                "unserved_customers": unserved,
            }

    info = {
        "baseline": "B1 (Greedy FCFS)",
        "runtime_s": time.perf_counter() - t0,
        "n_unserved": len(best_plan.get("unserved_customers", [])) if best_plan else len(instance.customers),
        "constraint_failures": all_failures,
    }
    return best_plan if best_plan else {"routes": [], "unserved_customers": list(instance.customers)}, info
