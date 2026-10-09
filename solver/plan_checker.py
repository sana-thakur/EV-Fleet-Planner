"""
solver/plan_checker.py

Independent feasibility checker for a route plan (shares NO code with milp.py/heuristic.py).
Recomputes everything from stop_sequence, charging_stops, planned_arrival_times and the
Instance. This is NOT the simulator: it checks the plan obeys the model's rules
(it trusts the plan's own charge start times); the simulator checks FIFO reality.

Timing rules: a vehicle may wait at a previous stop, so planned arrival may be LATER
than the earliest possible arrival, but never earlier (ARRIVAL_TIME_MISMATCH).
Arriving before a customer's window opens means waiting until a_i before service.
"""

from __future__ import annotations

from collections import Counter

from solver.instance import Instance
from solver.objective import late_minutes

TIME_TOL = 0.01  # minutes


def check_plan(plan: dict, instance: Instance, tol: float = 1e-4) -> dict:
    """tol is the energy tolerance in kWh (plans round energy to 4 decimals)."""
    inst = instance
    violations = []
    intervals = {}  # (station_id, plug) -> [(start, end, vehicle_id)]
    total_km = 0.0

    def bad(kind, vehicle_id, node, detail):
        violations.append({"type": kind, "vehicle_id": vehicle_id, "node": node, "detail": detail})

    station_ids = {s["station_id"] for s in inst.stations}
    customers = set(inst.customers)
    served = Counter()

    for r in plan["routes"]:
        k, seq, times = r["vehicle_id"], r["stop_sequence"], r["planned_arrival_times"]
        if len(seq) != len(times) or len(seq) < 2 or seq[0] != inst.depot_node or seq[-1] != inst.depot_node:
            bad("MALFORMED_ROUTE", k, None, "route must start/end at depot with one time per stop")
            continue
        unknown = [n for n in seq[1:-1] if n not in customers and n not in station_ids]
        if unknown:
            bad("MALFORMED_ROUTE", k, unknown[0], "unknown node in stop_sequence")
            continue

        q = inst.vehicle(k)["battery_capacity_kwh"]
        battery, ready = inst.initial_battery(k), times[0]
        if times[0] < inst.depot_open_min - TIME_TOL:
            bad("ARRIVAL_TIME_MISMATCH", k, seq[0], f"leaves depot at {times[0]:.2f}, before it opens at {inst.depot_open_min}")
            ready = inst.depot_open_min
        pending = list(r.get("charging_stops", []))
        for idx in range(1, len(seq)):
            u, v, arrive = seq[idx - 1], seq[idx], times[idx]
            total_km += inst.dist(u, v)
            battery -= inst.energy(k, u, v)
            earliest = ready + inst.time(u, v)
            if arrive < earliest - TIME_TOL:
                bad("ARRIVAL_TIME_MISMATCH", k, v, f"planned {arrive:.2f} < earliest possible {earliest:.2f}")
                arrive = earliest
            if battery < -tol:
                bad("BATTERY_NEGATIVE", k, v, f"battery {battery:.4f} kWh on arrival")

            if v in customers:
                served[v] += 1
                a, b = inst.customer_window[v]
                if late_minutes(arrive, (a, b)) > TIME_TOL:
                    bad("TIME_WINDOW_LATE", k, v, f"arrive {arrive:.2f} > b={b}")
                ready = max(arrive, a) + inst.service_time[v]
            elif v in station_ids and pending and pending[0]["station_id"] == v:
                cs = pending.pop(0)
                p, kwh = cs["plug_type_used"], cs["energy_requested_kwh"]
                start = cs.get("planned_charge_start", arrive)
                if abs(cs["planned_arrival_time"] - arrive) > TIME_TOL or start < arrive - TIME_TOL:
                    bad("ARRIVAL_TIME_MISMATCH", k, v, f"charging stop times {cs['planned_arrival_time']}/{start} vs arrival {arrive:.2f}")
                    start = max(start, arrive)
                if not inst.compatible(k, p):
                    bad("INCOMPATIBLE_PLUG", k, v, f"{inst.vehicle(k)['vehicle_type']} cannot use {p}")
                battery += kwh
                if battery > q + tol:
                    bad("BATTERY_OVER_CAPACITY", k, v, f"battery {battery:.4f} > {q} kWh after charging")
                end = start + 60.0 * kwh / inst.rate(v, p)
                intervals.setdefault((v, p), []).append((start, end, k))
                ready = end
            else:
                ready = arrive  # depot, or station passed through without charging
        if pending:
            bad("MALFORMED_ROUTE", k, pending[0]["station_id"], "charging stop not matched to a station visit")
        if ready > inst.horizon_min + TIME_TOL:
            bad("HORIZON_EXCEEDED", k, inst.depot_node, f"back at {ready:.2f} > horizon {inst.horizon_min}")

    unserved = set(plan.get("unserved_customers", []))
    for c in inst.customers:
        if served[c] == 0 and c not in unserved:
            bad("MISSING_CUSTOMER", None, c, "customer neither served nor listed as unserved")
        if served[c] > 1:
            bad("DUPLICATE_CUSTOMER", None, c, f"served {served[c]} times")

    # Per-type capacity: sweep line. Ends sort before starts at the same instant
    # (back-to-back is fine) and are pulled TIME_TOL earlier to absorb rounding.
    max_load = {}
    for (sid, p), ivs in intervals.items():
        events = sorted([(s, 1, k) for s, _, k in ivs] + [(e - TIME_TOL, -1, k) for _, e, k in ivs], key=lambda ev: (ev[0], ev[1]))
        load = peak = 0
        for t, delta, k in events:
            load += delta
            peak = max(peak, load)
            if delta == 1 and load > inst.plugs(sid, p):
                bad("CAPACITY_EXCEEDED", k, sid, f"{load} vehicles on {p} at t={t:.2f}, only {inst.plugs(sid, p)} plugs")
        max_load[f"{sid}/{p}"] = peak

    return {
        "feasible": not violations,
        "violations": violations,
        "summary": {
            "n_routes": len(plan["routes"]),
            "total_km": total_km,
            "n_served": sum(1 for c in inst.customers if served[c]),
            "n_unserved": len(unserved),
            "max_concurrent_charging": max_load,
        },
    }
