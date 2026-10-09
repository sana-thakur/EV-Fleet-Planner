"""
solver/simulator.py

Reality Engine Simulator for EVRPTW-HCC.

Replays planned vehicle routes under discrete-event simulation with:
  - Hard per-plug-type station capacity constraints
  - Strict FIFO queueing when all plugs of a compatible type are busy
  - Plug compatibility enforcement
  - Battery depletion and vehicle stranding detection
  - Dynamic arrival time propagation and delay ripple effect tracking

Conforms to docs/data_contract.md schema.
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import Any, Dict, List, Tuple

from solver.instance import Instance
from solver.objective import late_minutes


class StationPlugPool:
    """Manages physical plug slots and FIFO queue for a specific (station_id, plug_type)."""

    def __init__(self, station_id: str, plug_type: str, capacity: int) -> None:
        self.station_id = station_id
        self.plug_type = plug_type
        self.capacity = capacity
        self.active_units = 0
        self.fifo_queue: deque = deque()  # stores (arrival_time, vehicle_id, stop_index, cs_dict)


def simulate_plan(plan: dict, instance: Instance) -> Tuple[dict, dict]:
    """
    Replays a planned route set through the discrete-event Reality Engine simulator.

    Args:
        plan: Planned routes dictionary containing 'routes' and optional 'unserved_customers'.
        instance: Benchmark Instance object.

    Returns:
        (simulated_plan, sim_stats)
        - simulated_plan: Annotated copy of plan with actual_arrival_times, wait_time_minutes,
                          actual_charge_start/end, and updated unserved_customers.
        - sim_stats: Summary dictionary with key empirical performance indicators.
    """
    # Deep copy plan structure to build simulated_plan
    sim_routes = []
    unserved_set = set(plan.get("unserved_customers", []))

    # Initialize station plug pools: pools[(station_id, plug_type)]
    pools: Dict[Tuple[str, str], StationPlugPool] = {}
    for st in instance.stations:
        sid = st["station_id"]
        for ptype, cap in st["plugs"].items():
            pools[(sid, ptype)] = StationPlugPool(sid, ptype, cap)

    # Prepare per-vehicle tracking state
    vehicle_states: Dict[str, dict] = {}
    for r in plan["routes"]:
        vid = r["vehicle_id"]
        v_info = instance.vehicle(vid)
        seq = list(r["stop_sequence"])
        planned_times = list(r.get("planned_arrival_times", []))

        # Copy charging stops structure
        cs_list = []
        for cs in r.get("charging_stops", []):
            cs_copy = dict(cs)
            cs_copy["actual_arrival_time"] = None
            cs_copy["wait_time_minutes"] = 0.0
            cs_copy["actual_charge_start"] = None
            cs_copy["actual_charge_end"] = None
            cs_list.append(cs_copy)

        sim_r = {
            "vehicle_id": vid,
            "stop_sequence": seq,
            "planned_arrival_times": planned_times,
            "actual_arrival_times": [None] * len(seq),
            "charging_stops": cs_list,
            "stranded": False,
            "stranding_reason": None,
        }
        sim_routes.append(sim_r)
        vehicle_states[vid] = {
            "sim_r": sim_r,
            "cs_by_index": {},
            "battery_capacity": v_info["battery_capacity_kwh"],
            "current_battery": instance.initial_battery(vid),
        }

        # Map charging stops to their stop_sequence indices (Fix E3)
        station_visits = [
            idx for idx, stop in enumerate(seq)
            if isinstance(stop, str) and stop in instance._station
        ]
        visits_by_station: Dict[str, List[int]] = {}
        for idx in station_visits:
            sid = seq[idx]
            visits_by_station.setdefault(sid, []).append(idx)

        cs_by_station: Dict[str, List[dict]] = {}
        for cs in sim_r["charging_stops"]:
            sid = cs.get("station_id")
            if sid:
                cs_by_station.setdefault(sid, []).append(cs)

        for sid, cs_items in cs_by_station.items():
            avail_visits = list(visits_by_station.get(sid, []))
            for cs in cs_items:
                if not avail_visits:
                    break
                if "planned_arrival_time" in cs and planned_times:
                    cs_plan_t = cs["planned_arrival_time"]
                    best_v_idx = min(
                        avail_visits,
                        key=lambda v_i: abs((planned_times[v_i] if v_i < len(planned_times) else 0.0) - cs_plan_t),
                    )
                    vehicle_states[vid]["cs_by_index"][best_v_idx] = cs
                    avail_visits.remove(best_v_idx)
                else:
                    best_v_idx = avail_visits.pop(0)
                    vehicle_states[vid]["cs_by_index"][best_v_idx] = cs

    # Event Queue: items are (event_time, priority, event_type, payload)
    # Event types & priority tie-breakers:
    #   0: PLUG_RELEASE
    #   1: VEHICLE_DEPARTURE
    #   2: VEHICLE_ARRIVAL
    event_queue: List[Tuple[float, int, str, dict]] = []
    event_counter = 0

    def push_event(time_val: float, event_priority: int, event_type: str, payload: dict) -> None:
        nonlocal event_counter
        event_counter += 1
        heapq.heappush(event_queue, (time_val, event_priority, event_type, event_counter, payload))

    def compute_departure_time(vid: str, from_idx: int, to_idx: int, finish_t: float) -> float:
        """
        Computes vehicle departure time from from_idx to to_idx (Fix E1).
        Vehicles follow the plan's timing: they never arrive earlier than planned (they wait at the
        previous stop instead), nor before a customer's window opens. Delays propagate (finish_t).
        Holding at stations too stops a vehicle from grabbing a plug slot booked by another vehicle.
        """
        sim_r = vehicle_states[vid]["sim_r"]
        seq = sim_r["stop_sequence"]
        planned_times = sim_r["planned_arrival_times"]
        u, v = seq[from_idx], seq[to_idx]
        travel_t = instance.time(u, v)

        planned_arr = planned_times[to_idx] if to_idx < len(planned_times) else 0.0
        target_arr = planned_arr
        if v in instance.customer_window:
            target_arr = max(planned_arr, instance.customer_window[v][0])
        if v == seq[-1] and to_idx == len(seq) - 1:
            return finish_t  # returning to the depot: no reason to wait
        return max(finish_t, target_arr - travel_t)

    # Schedule initial departure from depot for each vehicle at t = planned_departure or 0.0
    for r in plan["routes"]:
        vid = r["vehicle_id"]
        seq = r["stop_sequence"]
        if not seq:
            continue
        vehicle_states[vid]["sim_r"]["actual_arrival_times"][0] = instance.depot_open_min
        if len(seq) > 1:
            depart_t = compute_departure_time(vid, 0, 1, finish_t=instance.depot_open_min)
            push_event(
                depart_t,
                1,
                "VEHICLE_DEPARTURE",
                {
                    "vehicle_id": vid,
                    "from_stop_idx": 0,
                    "to_stop_idx": 1,
                    "depart_time": depart_t,
                },
            )

    # Main Discrete Event Simulation Loop
    n_stranded = 0
    n_time_window_violations = 0
    total_late_minutes = 0.0

    while event_queue:
        event_time, priority, event_type, _, payload = heapq.heappop(event_queue)

        if event_type == "VEHICLE_DEPARTURE":
            vid = payload["vehicle_id"]
            from_idx = payload["from_stop_idx"]
            to_idx = payload["to_stop_idx"]
            depart_t = payload["depart_time"]

            v_state = vehicle_states[vid]
            sim_r = v_state["sim_r"]

            if sim_r["stranded"]:
                continue

            seq = sim_r["stop_sequence"]
            u, v = seq[from_idx], seq[to_idx]

            travel_t = instance.time(u, v)
            energy_req = instance.energy(vid, u, v)

            arrival_t = depart_t + travel_t
            remaining_bat = v_state["current_battery"] - energy_req

            if remaining_bat < -1e-6:
                # Vehicle runs out of battery on leg u -> v
                sim_r["stranded"] = True
                sim_r["stranding_reason"] = f"Battery depleted ({remaining_bat:.2f} kWh) on leg {u} -> {v}"
                n_stranded += 1
                # Mark remaining customer stops on this route as unserved
                for idx in range(to_idx, len(seq)):
                    node = seq[idx]
                    if node in instance.customer_window:
                        unserved_set.add(node)
                continue

            v_state["current_battery"] = max(0.0, remaining_bat)
            push_event(
                arrival_t,
                2,
                "VEHICLE_ARRIVAL",
                {
                    "vehicle_id": vid,
                    "stop_idx": to_idx,
                    "arrival_time": arrival_t,
                },
            )

        elif event_type == "VEHICLE_ARRIVAL":
            vid = payload["vehicle_id"]
            stop_idx = payload["stop_idx"]
            arr_t = payload["arrival_time"]

            v_state = vehicle_states[vid]
            sim_r = v_state["sim_r"]

            if sim_r["stranded"]:
                continue

            seq = sim_r["stop_sequence"]
            curr_stop = seq[stop_idx]
            sim_r["actual_arrival_times"][stop_idx] = arr_t

            # CASE A: Stop is Customer
            if curr_stop in instance.customer_window:
                window_a, window_b = instance.customer_window[curr_stop]

                # Vehicle arrives early -> absorbs slack by waiting at stop until window_a
                service_start_t = max(arr_t, window_a)

                # Check time window violation (arrived late) -- shared rule with objective.py
                late_min = late_minutes(arr_t, (window_a, window_b))
                if late_min > 1e-6:
                    n_time_window_violations += 1
                    total_late_minutes += late_min

                serv_dur = instance.service_time.get(curr_stop, 5.0)
                finish_t = service_start_t + serv_dur

                next_idx = stop_idx + 1
                if next_idx < len(seq):
                    depart_t = compute_departure_time(vid, stop_idx, next_idx, finish_t)
                    push_event(
                        depart_t,
                        1,
                        "VEHICLE_DEPARTURE",
                        {
                            "vehicle_id": vid,
                            "from_stop_idx": stop_idx,
                            "to_stop_idx": next_idx,
                            "depart_time": depart_t,
                        },
                    )

            # CASE B: Stop is Charging Station
            elif isinstance(curr_stop, str) and curr_stop in instance._station:
                sid = curr_stop
                cs = v_state["cs_by_index"].get(stop_idx)

                # Fix E2: Pass-through station visit with no matching planned charging stop
                if cs is None:
                    finish_t = arr_t
                    next_idx = stop_idx + 1
                    if next_idx < len(seq):
                        depart_t = compute_departure_time(vid, stop_idx, next_idx, finish_t)
                        push_event(
                            depart_t,
                            1,
                            "VEHICLE_DEPARTURE",
                            {
                                "vehicle_id": vid,
                                "from_stop_idx": stop_idx,
                                "to_stop_idx": next_idx,
                                "depart_time": depart_t,
                            },
                        )
                    continue

                plug_type = cs["plug_type_used"]
                kwh_req = cs["energy_requested_kwh"]

                # Check plug compatibility and station availability
                pool = pools.get((sid, plug_type))

                if pool is None or pool.capacity == 0 or not instance.compatible(vid, plug_type):
                    # Incompatible plug or station has no plugs of this type
                    sim_r["stranded"] = True
                    sim_r["stranding_reason"] = f"Incompatible plug '{plug_type}' or 0 plugs at station '{sid}'"
                    n_stranded += 1
                    for idx in range(stop_idx, len(seq)):
                        node = seq[idx]
                        if node in instance.customer_window:
                            unserved_set.add(node)
                    continue

                cs["actual_arrival_time"] = arr_t

                # Fix E15: Cap charging at remaining battery capacity
                current_soc = v_state["current_battery"]
                battery_cap = v_state["battery_capacity"]
                remaining_cap = max(0.0, battery_cap - current_soc)
                kwh_absorbed = max(0.0, min(kwh_req, remaining_cap))
                charge_dur = instance.charge_minutes(sid, plug_type, kwh_absorbed)

                # Check plug pool capacity
                if pool.active_units < pool.capacity:
                    # Plug available immediately
                    pool.active_units += 1
                    charge_start_t = arr_t
                    wait_t = 0.0
                    charge_end_t = charge_start_t + charge_dur

                    cs["wait_time_minutes"] = wait_t
                    cs["actual_charge_start"] = charge_start_t
                    cs["actual_charge_end"] = charge_end_t

                    v_state["current_battery"] = min(battery_cap, current_soc + kwh_absorbed)

                    # Fix E1: Release plug immediately upon charge completion
                    push_event(
                        charge_end_t,
                        0,
                        "PLUG_RELEASE",
                        {
                            "station_id": sid,
                            "plug_type": plug_type,
                        },
                    )

                    # Fix E1: Hold departure at previous stop (waiting off-plug)
                    next_idx = stop_idx + 1
                    if next_idx < len(seq):
                        depart_t = compute_departure_time(vid, stop_idx, next_idx, charge_end_t)
                        push_event(
                            depart_t,
                            1,
                            "VEHICLE_DEPARTURE",
                            {
                                "vehicle_id": vid,
                                "from_stop_idx": stop_idx,
                                "to_stop_idx": next_idx,
                                "depart_time": depart_t,
                            },
                        )
                else:
                    # All plugs of this type busy -> enter FIFO queue
                    pool.fifo_queue.append((arr_t, vid, stop_idx, cs))

            # CASE C: Return to Depot
            else:
                # Vehicle reached depot successfully
                pass

        elif event_type == "PLUG_RELEASE":
            sid = payload["station_id"]
            plug_type = payload["plug_type"]
            pool = pools[(sid, plug_type)]

            if pool.fifo_queue:
                # Pop next waiting vehicle from FIFO queue
                arr_t, vid, stop_idx, cs = pool.fifo_queue.popleft()
                v_state = vehicle_states[vid]
                sim_r = v_state["sim_r"]

                charge_start_t = event_time
                wait_t = charge_start_t - arr_t

                # Fix E15: Cap charging at remaining battery capacity
                current_soc = v_state["current_battery"]
                battery_cap = v_state["battery_capacity"]
                remaining_cap = max(0.0, battery_cap - current_soc)
                kwh_absorbed = max(0.0, min(cs["energy_requested_kwh"], remaining_cap))
                charge_dur = instance.charge_minutes(sid, plug_type, kwh_absorbed)
                charge_end_t = charge_start_t + charge_dur

                cs["wait_time_minutes"] = wait_t
                cs["actual_charge_start"] = charge_start_t
                cs["actual_charge_end"] = charge_end_t

                v_state["current_battery"] = min(battery_cap, current_soc + kwh_absorbed)

                # Fix E1: Re-schedule plug release for this new occupant immediately upon charge completion
                push_event(
                    charge_end_t,
                    0,
                    "PLUG_RELEASE",
                    {
                        "station_id": sid,
                        "plug_type": plug_type,
                    },
                )

                # Fix E1: Schedule vehicle departure (waiting off-plug if held)
                seq = sim_r["stop_sequence"]
                next_idx = stop_idx + 1
                if next_idx < len(seq):
                    depart_t = compute_departure_time(vid, stop_idx, next_idx, charge_end_t)
                    push_event(
                        depart_t,
                        1,
                        "VEHICLE_DEPARTURE",
                        {
                            "vehicle_id": vid,
                            "from_stop_idx": stop_idx,
                            "to_stop_idx": next_idx,
                            "depart_time": depart_t,
                        },
                    )
            else:
                pool.active_units -= 1

    # Fill default actual_arrival_times for any remaining unreached stops
    for sim_r in sim_routes:
        seq_len = len(sim_r["stop_sequence"])
        for idx in range(seq_len):
            if sim_r["actual_arrival_times"][idx] is None:
                if idx < len(sim_r["planned_arrival_times"]):
                    sim_r["actual_arrival_times"][idx] = sim_r["planned_arrival_times"][idx]
                else:
                    sim_r["actual_arrival_times"][idx] = 0.0

    # Aggregate simulation statistics
    total_wait_minutes = sum(
        cs.get("wait_time_minutes", 0.0) for sim_r in sim_routes for cs in sim_r["charging_stops"]
    )
    total_charges = sum(len(sim_r["charging_stops"]) for sim_r in sim_routes)

    sim_plan = {
        "routes": sim_routes,
        "unserved_customers": sorted(list(unserved_set)),
    }

    sim_stats = {
        "total_wait_time_minutes": round(total_wait_minutes, 2),
        "n_charging_stops": total_charges,
        "n_stranded_vehicles": n_stranded,
        "n_time_window_violations": n_time_window_violations,
        "total_late_minutes": round(total_late_minutes, 2),
        "unserved_customer_count": len(unserved_set),
    }

    return sim_plan, sim_stats
