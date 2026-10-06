"""
solver/milp.py

Exact MILP for EVRPTW-HCC (docs/model_formulation.md) plus the approved additions:
  * start/end depot split (o, e) so the return leg has its own arrival time;
  * station copies (max_station_visits per station);
  * linearized charging duration h (D2);
  * exact per-type plug capacity via plug units + pairwise ordering (D3).

Timing semantics: tau at a customer = service start, tau at a station = charge start.
Any slack is spent waiting at the PREVIOUS stop (the vehicle departs late), so the
recorded planned arrival time equals tau: no early arrivals at customers, and no
planned queueing at chargers (planned_charge_start == planned_arrival_time).
"""

from __future__ import annotations

import itertools
import time

import pulp

from solver.instance import Instance

O, E = ("o",), ("e",)


def _solver(time_limit_s: int, msg: bool):
    if "HiGHS" in pulp.listSolvers(onlyAvailable=True):
        return pulp.HiGHS(msg=msg, timeLimit=time_limit_s)
    return pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit_s)


def solve_milp(instance: Instance, time_limit_s: int = 300, max_station_visits: int = 1, msg: bool = False) -> tuple[dict, dict]:
    """Solve EVRPTW-HCC exactly. Returns (route_plan, info)."""
    inst = instance
    t_start = time.perf_counter()

    cust = [("c", c) for c in inst.customers]
    stat = [("s", s["station_id"], m) for s in inst.stations for m in range(max_station_visits)]
    name = {n: f"n{i}" for i, n in enumerate([O, E] + cust + stat)}

    def loc(n):
        return inst.depot_node if n in (O, E) else n[1]

    def a(n):  # earliest tau
        return inst.customer_window[n[1]][0] if n[0] == "c" else 0.0

    def b(n):  # latest tau
        return inst.customer_window[n[1]][1] if n[0] == "c" else inst.horizon_min

    def svc(n):
        return inst.service_time[n[1]] if n[0] == "c" else 0.0

    K = [v["vehicle_id"] for v in inst.vehicles]
    Q = {k: inst.vehicle(k)["battery_capacity_kwh"] for k in K}
    usable = {(k, n): inst.usable_plugs(k, n[1]) for k in K for n in stat}
    S_k = {k: [n for n in stat if usable[k, n]] for k in K}  # pre-prune: no usable plug -> no copy
    # Longest possible charge of vehicle k at station copy n: empty -> full on the slowest usable plug.
    Hmax = {(k, n): 60.0 * Q[k] / min(inst.rate(n[1], p) for p in usable[k, n]) for k in K for n in S_k[k]}

    prob = pulp.LpProblem("EVRPTW_HCC", pulp.LpMinimize)
    x, tau, B, c, h, y = {}, {}, {}, {}, {}, {}
    out_, in_ = {}, {}

    for ki, k in enumerate(K):
        N = [O] + cust + S_k[k] + [E]
        for n in N:
            tau[k, n] = prob.add_variable(f"tau_{ki}_{name[n]}", lowBound=a(n), upBound=b(n))
            B[k, n] = prob.add_variable(f"B_{ki}_{name[n]}", 0, Q[k])
            out_[k, n], in_[k, n] = [], []
        for n in S_k[k]:
            c[k, n] = prob.add_variable(f"c_{ki}_{name[n]}", 0, Q[k])
            h[k, n] = prob.add_variable(f"h_{ki}_{name[n]}", 0, Hmax[k, n])
            for p in usable[k, n]:
                y[k, n, p] = prob.add_variable(f"y_{ki}_{name[n]}_{p}", cat="Binary")
        for i, j in itertools.product(N, N):
            if i == j or j == O or i == E:
                continue
            if i[0] == j[0] == "s" and i[1] == j[1]:
                continue  # two copies of the same station back to back is pointless
            if inst.energy(k, loc(i), loc(j)) > Q[k]:
                continue  # leg longer than a full battery
            if a(i) + svc(i) + inst.time(loc(i), loc(j)) > b(j):
                continue  # can never arrive in time
            x[k, i, j] = prob.add_variable(f"x_{ki}_{name[i]}_{name[j]}", cat="Binary")
            out_[k, i].append(x[k, i, j])
            in_[k, j].append(x[k, i, j])

    # Objective: total km + tiny tie-breaker preferring earlier finish times.
    # eps * sum(tau_e) <= 1e-3 km in total, so it never outweighs a real distance difference.
    eps = 1e-3 / (len(K) * inst.horizon_min)
    prob += (pulp.lpSum(inst.dist(loc(i), loc(j)) * v for (k, i, j), v in x.items())
             + eps * pulp.lpSum(tau[k, E] for k in K))

    # (A) Routing & flow
    for n in cust:
        arcs = [v for k in K for v in in_[k, n]]
        if not arcs:
            return _empty(inst, t_start, "Infeasible", prob)
        prob += pulp.lpSum(arcs) == 1, f"serve_{name[n]}"
    for k in K:
        prob += pulp.lpSum(out_[k, O]) == 1  # o->e means "unused"
        prob += pulp.lpSum(in_[k, E]) == 1
        for n in cust + S_k[k]:
            prob += pulp.lpSum(in_[k, n]) == pulp.lpSum(out_[k, n])
        for n in S_k[k]:
            prob += pulp.lpSum(in_[k, n]) <= 1
            if n[2] > 0:  # symmetry: use copy m only if copy m-1 is used
                prob += pulp.lpSum(in_[k, n]) <= pulp.lpSum(in_[k, ("s", n[1], n[2] - 1)])

    # (B) Time + (C) Battery along arcs
    for (k, i, j), v in x.items():
        t_ij = inst.time(loc(i), loc(j))
        e_ij = inst.energy(k, loc(i), loc(j))
        h_i = h[k, i] if i[0] == "s" else 0
        c_i = c[k, i] if i[0] == "s" else 0
        # M_t: the largest value tau_i + s_i + h_i + t_ij - tau_j can take when x = 0.
        m_t = b(i) + svc(i) + (Hmax[k, i] if i[0] == "s" else 0) + t_ij - a(j)
        prob += tau[k, j] >= tau[k, i] + svc(i) + h_i + t_ij - m_t * (1 - v)
        # Battery is tracked exactly (two-sided) so c <= Q - B uses the true level.
        # Upper side: worst case B_j = Q, B_i + c_i = 0 -> M = Q + e_ij.
        prob += B[k, j] <= B[k, i] + c_i - e_ij + (Q[k] + e_ij) * (1 - v)
        # Lower side: worst case B_j = 0, B_i + c_i = Q -> M = Q - e_ij.
        prob += B[k, j] >= B[k, i] + c_i - e_ij - (Q[k] - e_ij) * (1 - v)
    for k in K:
        prob += tau[k, O] == 0
        prob += B[k, O] == inst.initial_battery(k)  # vehicle starts at initial_soc / initial_battery

    # (C) charging limits, (D1) compatibility, (D2) charging duration
    for k in K:
        for n in S_k[k]:
            ys = [y[k, n, p] for p in usable[k, n]]  # y only exists where compatible: that IS D1
            prob += c[k, n] <= Q[k] - B[k, n]
            prob += c[k, n] <= Q[k] * pulp.lpSum(ys)  # M = Q: can never charge more than a full battery
            prob += h[k, n] <= Hmax[k, n] * pulp.lpSum(ys)
            prob += pulp.lpSum(ys) <= pulp.lpSum(in_[k, n])  # also gives sum_p y <= 1
            for p in usable[k, n]:
                # M = Hmax >= 60*c/r_p for any c <= Q, so the constraint is slack when y = 0.
                prob += h[k, n] >= 60.0 * c[k, n] / inst.rate(n[1], p) - Hmax[k, n] * (1 - y[k, n, p])

    # (D3) exact per-type capacity: vehicles on the same physical plug unit never overlap.
    n_units_constraints = 0
    for s in inst.stations:
        sid = s["station_id"]
        for p in inst.plug_types:
            users = [(k, n) for (k, n, pp) in y if pp == p and n[1] == sid]
            n_units = inst.plugs(sid, p)
            if len({k for k, _ in users}) <= n_units:
                continue  # never more users than plugs: capacity can't bind
            z = {(k, n, u): prob.add_variable(f"z_{K.index(k)}_{name[n]}_{p}_{u}", cat="Binary")
                 for k, n in users for u in range(n_units)}
            for k, n in users:
                prob += pulp.lpSum(z[k, n, u] for u in range(n_units)) == y[k, n, p]
            for (k, n), (l, m) in itertools.combinations(users, 2):
                if k == l:
                    continue
                for u in range(n_units):
                    o = prob.add_variable(f"o_{K.index(k)}_{name[n]}_{K.index(l)}_{name[m]}_{p}_{u}", cat="Binary")
                    zk, zl = z[k, n, u], z[l, m, u]
                    # M = horizon + Hmax: bounds tau_k + h_k - tau_l since both tau lie in [0, horizon].
                    prob += tau[l, m] >= tau[k, n] + h[k, n] - (inst.horizon_min + Hmax[k, n]) * (3 - zk - zl - o)
                    prob += tau[k, n] >= tau[l, m] + h[l, m] - (inst.horizon_min + Hmax[l, m]) * (2 - zk - zl + o)
                    n_units_constraints += 2
    # ponytail: no unit symmetry breaking (u+1 only if u used); add if many-plug instances get slow.

    prob.solve(_solver(time_limit_s, msg))
    status, gap = _status(prob)
    if x and next(iter(x.values())).varValue is None or status in ("Infeasible", "NotSolved"):
        return _empty(inst, t_start, status, prob)

    val = lambda var: var.varValue or 0.0
    routes = []
    for k in K:
        seq, n = [O], O
        while n != E:
            n = next(j for (kk, i, j), v in x.items() if kk == k and i == n and val(v) > 0.5)
            seq.append(n)
        if len(seq) == 2:
            continue  # o -> e: vehicle not dispatched
        routes.append(_route(inst, k, seq, loc, a, svc, tau, c, y, usable, val))

    objective_km = sum(inst.dist(loc(i), loc(j)) for (k, i, j), v in x.items() if val(v) > 0.5)
    return {"routes": routes, "unserved_customers": []}, {
        "status": status,
        "objective_km": objective_km,
        "runtime_s": time.perf_counter() - t_start,
        "mip_gap": gap,
        "n_vars": len(prob.variables()),
        "n_constraints": len(prob.constraints()),
        "solver_name": type(prob.solver).__name__ if getattr(prob, "solver", None) else None,
    }


def _route(inst, k, seq, loc, a, svc, tau, c, y, usable, val) -> dict:
    """Rebuild one vehicle's plan. Customers are served as early as possible (>= a_i);
    stations keep the MILP's charge start (capacity-feasible). Pushing customers earlier
    never delays later stops, so the schedule stays feasible."""
    stops, times, charging = [inst.depot_node], [0.0], []
    ready = 0.0
    for prev, n in zip(seq, seq[1:]):
        arrive = ready + inst.time(loc(prev), loc(n))
        if n[0] == "c":
            arrive = max(arrive, a(n))
            ready = arrive + svc(n)
        elif n[0] == "s":
            arrive = max(arrive, val(tau[k, n]))
            kwh = round(val(c[k, n]), 4)
            plug = next(p for p in usable[k, n] if val(y[k, n, p]) > 0.5) if kwh > 0 else None
            if plug is None:  # visited but not charged: pass-through, no charging stop
                ready = arrive
            else:
                charging.append({
                    "station_id": n[1], "plug_type_used": plug,
                    "planned_arrival_time": round(arrive, 4), "actual_arrival_time": round(arrive, 4),
                    "wait_time_minutes": 0.0, "energy_requested_kwh": kwh,
                    "planned_charge_start": round(arrive, 4),
                })
                ready = arrive + inst.charge_minutes(n[1], plug, kwh)
        stops.append(loc(n))
        times.append(round(arrive, 4))
    return {"vehicle_id": k, "stop_sequence": stops, "planned_arrival_times": times,
            "actual_arrival_times": list(times), "charging_stops": charging}


def _status(prob) -> tuple[str, float | None]:
    model = getattr(prob, "solverModel", None)
    if model is not None and hasattr(model, "getModelStatus"):  # HiGHS via highspy
        s = model.modelStatusToString(model.getModelStatus())
        gap = model.getInfo().mip_gap
        return {"Optimal": "Optimal", "Infeasible": "Infeasible"}.get(s, s), gap
    return pulp.LpStatus[prob.status], None


def _empty(inst, t_start, status, prob) -> tuple[dict, dict]:
    return {"routes": [], "unserved_customers": list(inst.customers)}, {
        "status": status, "objective_km": None, "runtime_s": time.perf_counter() - t_start,
        "mip_gap": None, "n_vars": len(prob.variables()), "n_constraints": len(prob.constraints()),
        "solver_name": None,
    }


def _assign_units(intervals: list, n_units: int) -> list:
    """Greedy interval colouring: sorted by start, put each on the first free unit.
    Optimal for interval graphs, so it succeeds iff capacity is never exceeded."""
    free_at = [float("-inf")] * max(n_units, 1)
    units = []
    for start, end in intervals:
        u = next((u for u in range(len(free_at)) if free_at[u] <= start + 0.01), None)
        units.append(u)
        if u is not None:
            free_at[u] = end
    return units


def explain_solution(plan: dict, instance: Instance) -> str:
    """Human-readable per-leg breakdown + charging intervals per (station, plug, unit)."""
    inst = instance
    lines, intervals = [], {}
    for r in plan["routes"]:
        k = r["vehicle_id"]
        q = inst.vehicle(k)["battery_capacity_kwh"]
        lines.append(f"\n=== {k} ({inst.vehicle(k)['vehicle_type']}, {q} kWh, plugs {inst.vehicle(k)['compatible_plugs']})")
        charges = iter(r["charging_stops"])
        battery, total_km = q, 0.0
        seq, times = r["stop_sequence"], r["planned_arrival_times"]
        for idx in range(1, len(seq)):
            u, v = seq[idx - 1], seq[idx]
            km, kwh = inst.dist(u, v), inst.energy(k, u, v)
            battery -= kwh
            total_km += km
            tw = inst.customer_window.get(v)
            line = (f"  {u!s:>5} -> {v!s:<5} {km:6.1f} km {inst.time(u, v):6.1f} min {kwh:7.3f} kWh"
                    f" | arrive {times[idx]:7.2f} battery {battery:7.3f}" + (f" window {list(tw)}" if tw else ""))
            if isinstance(v, str):
                cs = next(charges)
                dur = inst.charge_minutes(v, cs["plug_type_used"], cs["energy_requested_kwh"])
                start = cs["planned_charge_start"]
                battery += cs["energy_requested_kwh"]
                line += f"\n        charge {cs['energy_requested_kwh']} kWh on {cs['plug_type_used']} [{start:.2f}, {start + dur:.2f}] -> battery {battery:.3f}"
                intervals.setdefault((v, cs["plug_type_used"]), []).append((start, start + dur, k))
            lines.append(line)
        lines.append(f"  total {total_km:.1f} km")
    lines.append("\n=== Charging intervals per (station, plug, unit)")
    for (sid, p), ivs in sorted(intervals.items()):
        ivs.sort()
        units = _assign_units([(s, e) for s, e, _ in ivs], inst.plugs(sid, p))
        for (s, e, k), u in zip(ivs, units):
            lines.append(f"  {sid} {p} unit {u if u is not None else 'OVERBOOKED'}: [{s:.2f}, {e:.2f}] {k}")
    return "\n".join(lines)


if __name__ == "__main__":
    from solver.instance import make_toy_instance

    toy = make_toy_instance()
    plan, info = solve_milp(toy, time_limit_s=60)
    print(info)
    print(explain_solution(plan, toy))
