"""
solver/heuristic.py

Timeline-Aware Greedy Insertion Heuristic for EVRPTW-HCC. Deterministic, pure Python.

Each (station, plug type) has a PlugTimeline: one booking list per physical plug unit.
Routes are evaluated by forward simulation; when the battery can't safely reach the next
stop, a charging stop is inserted at the station minimising detour_km + wait_weight * queue
wait, on the earliest free slot of a compatible plug that respects other vehicles' bookings.

Timing matches milp.py: slack is spent at the previous stop, so the planned arrival at a
customer is max(earliest, a_i) and at a station equals the booked charge start.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import time
from dataclasses import dataclass, field

from solver.instance import Instance

EPS = 1e-9
RESERVE = 1.05  # charge 5% more than the remaining route needs


class PlugTimeline:
    """Bookings of one (station, plug type): units[u] = sorted [(start, end, vehicle_id)]."""

    def __init__(self, n_units: int):
        self.units = [[] for _ in range(n_units)]

    def earliest_slot(self, ready_time: float, duration: float, exclude: str | None = None) -> tuple[int, float]:
        """Earliest start >= ready_time with a free gap of `duration` on any unit (lowest unit wins ties).
        Bookings of `exclude` are ignored (used while re-planning that vehicle)."""
        best = None
        for u, bookings in enumerate(self.units):
            start = ready_time
            for s, e, vid in bookings:
                if vid == exclude or e <= start + EPS:
                    continue
                if s >= start + duration - EPS:
                    break
                start = e
            if best is None or start < best[1] - EPS:
                best = (u, start)
        return best

    def reserve(self, unit: int, start: float, end: float, vehicle_id: str) -> None:
        self.units[unit].append((start, end, vehicle_id))
        self.units[unit].sort()

    def release_vehicle(self, vehicle_id: str) -> None:
        self.units = [[b for b in bookings if b[2] != vehicle_id] for bookings in self.units]


@dataclass
class RouteResult:
    stops: list = field(default_factory=list)  # [(stop id, planned arrival)] excluding the start depot
    charges: list = field(default_factory=list)  # [(station_id, plug, unit, start, duration, kwh)]
    km: float = 0.0
    wait: float = 0.0  # total queue wait at chargers (minutes)


def apply_overrides(instance: Instance, station_overrides: dict | None) -> Instance:
    """Copy of the instance with plug counts overridden, e.g. {"S_01": {"LEV": 0}} (break a charger)."""
    if not station_overrides:
        return instance
    stations = copy.deepcopy(instance.stations)
    for s in stations:
        s["plugs"].update(station_overrides.get(s["station_id"], {}))
    return dataclasses.replace(instance, stations=stations)


def make_timelines(inst: Instance) -> dict:
    return {(s["station_id"], p): PlugTimeline(n) for s in inst.stations for p, n in s["plugs"].items() if n > 0}


def evaluate_route(inst: Instance, vehicle_id: str, customers: list, timelines: dict,
                   wait_weight: float = 0.5) -> RouteResult | None:
    """Forward-simulate `customers` from a full battery at the depot, inserting charging stops.
    Tries two charging policies and keeps the cheaper (km + wait_weight * queue wait):
      lazy  - charge only when the next leg would otherwise be unsafe;
      eager - also charge at the first opportunity once the rest of the route needs more
              energy than is on board (grabs a free plug before others queue for it).
    Other vehicles' bookings are respected; this vehicle's own bookings are ignored. None if infeasible."""
    lazy = _simulate(inst, vehicle_id, customers, timelines, wait_weight, eager=False)
    if lazy is not None and not lazy.charges:
        return lazy  # route never needs a charge, so eager would do the same
    eager = _simulate(inst, vehicle_id, customers, timelines, wait_weight, eager=True)
    options = [r for r in (lazy, eager) if r is not None]
    return min(options, key=lambda r: r.km + wait_weight * r.wait) if options else None  # lazy wins ties


def _simulate(inst: Instance, vehicle_id: str, customers: list, timelines: dict,
              wait_weight: float, eager: bool) -> RouteResult | None:
    q = inst.vehicle(vehicle_id)["battery_capacity_kwh"]
    e = lambda u, v: inst.energy(vehicle_id, u, v)
    stations = [s["station_id"] for s in inst.stations if inst.usable_plugs(vehicle_id, s["station_id"])]
    safe_points = stations + [inst.depot_node]
    targets = list(customers) + [inst.depot_node]
    # after_kwh[i] = energy of the fixed legs targets[i] -> ... -> depot
    after_kwh = [0.0] * len(targets)
    for i in range(len(targets) - 2, -1, -1):
        after_kwh[i] = after_kwh[i + 1] + e(targets[i], targets[i + 1])

    res = RouteResult()
    cur, ready, battery = inst.depot_node, inst.depot_open_min, inst.initial_battery(vehicle_id)
    for idx, target in enumerate(targets):
        is_last = idx == len(targets) - 1
        # look-ahead: after reaching target we must still reach a station or the depot
        reserve = 0.0 if is_last else min(e(target, p) for p in safe_points)
        for attempt in range(3):  # at most 3 charging stops per leg
            forced = battery - e(cur, target) < reserve - EPS
            need_later = e(cur, target) + after_kwh[idx]
            early = eager and attempt == 0 and cur not in stations and need_later > battery + EPS
            if not (forced or early):
                break
            best = None
            for sid in stations:
                if sid == cur or e(cur, sid) > battery + EPS:
                    continue
                b_s = battery - e(cur, sid)
                remaining = e(sid, target) + after_kwh[idx]
                kwh = round(min(q - b_s, max(0.0, remaining * RESERVE - b_s)), 4)
                if kwh <= EPS or b_s + kwh < e(sid, target) + reserve - 1e-4:
                    continue
                arrive = ready + inst.time(cur, sid)
                slots = []
                for p in inst.usable_plugs(vehicle_id, sid):
                    dur = inst.charge_minutes(sid, p, kwh)
                    unit, start = timelines[sid, p].earliest_slot(arrive, dur, exclude=vehicle_id)
                    slots.append((start + dur, p, unit, start, dur))
                finish, p, unit, start, dur = min(slots)
                detour = inst.dist(cur, sid) + inst.dist(sid, target) - inst.dist(cur, target)
                score = detour + wait_weight * (start - arrive)
                if best is None or (score, sid) < best[0]:
                    best = ((score, sid), sid, p, unit, start, dur, kwh, b_s, start - arrive)
            if best is None:
                if forced:
                    return None  # stranded
                break
            _, sid, p, unit, start, dur, kwh, b_s, wait = best
            res.km += inst.dist(cur, sid)
            res.stops.append((sid, start))
            res.charges.append((sid, p, unit, start, dur, kwh))
            res.wait += wait
            cur, ready, battery = sid, start + dur, b_s + kwh
        if battery - e(cur, target) < reserve - 1e-4:
            return None

        res.km += inst.dist(cur, target)
        battery -= e(cur, target)
        arrive = ready + inst.time(cur, target)
        if is_last:
            if arrive > inst.horizon_min + EPS:
                return None
        else:
            a, b = inst.customer_window[target]
            arrive = max(arrive, a)
            if arrive > b + EPS:
                return None
            ready = arrive + inst.service_time[target]
        res.stops.append((target, arrive))
        cur = target
    return res


class _State:
    """Current routes + committed plug bookings."""

    def __init__(self, inst: Instance, wait_weight: float):
        self.inst, self.w = inst, wait_weight
        self.timelines = make_timelines(inst)
        self.routes = {v["vehicle_id"]: [] for v in inst.vehicles}
        self.results = {k: RouteResult() for k in self.routes}

    def cost(self, r: RouteResult) -> float:
        return r.km + self.w * r.wait

    def total(self) -> float:
        return sum(self.cost(r) for r in self.results.values())

    def commit(self, k: str, customers: list, result: RouteResult) -> None:
        for tl in self.timelines.values():
            tl.release_vehicle(k)
        for sid, p, unit, start, dur, _ in result.charges:
            self.timelines[sid, p].reserve(unit, start, start + dur, k)
        self.routes[k], self.results[k] = customers, result

    def snapshot(self):
        return {key: [list(u) for u in tl.units] for key, tl in self.timelines.items()}, dict(self.routes), dict(self.results)

    def restore(self, snap) -> None:
        units, self.routes, self.results = snap
        for key, tl in self.timelines.items():
            tl.units = [list(u) for u in units[key]]

    def attempt(self, changes: list) -> bool:
        """Apply [(vehicle, new customer sequence)] in order; keep only if all feasible and total cost drops."""
        before, snap = self.total(), self.snapshot()
        for k, seq in changes:
            r = evaluate_route(self.inst, k, seq, self.timelines, self.w)
            if r is None:
                self.restore(snap)
                return False
            self.commit(k, seq, r)
        if self.total() < before - 1e-6:
            return True
        self.restore(snap)
        return False

    def best_insertion(self, c):
        """Cheapest (cost, vehicle, position, route, result) for customer c, or None."""
        best = None
        for k in self.routes:  # vehicle order = fleet order -> deterministic ties
            seq = self.routes[k]
            base = self.cost(self.results[k])
            for pos in range(len(seq) + 1):
                new = seq[:pos] + [c] + seq[pos:]
                r = evaluate_route(self.inst, k, new, self.timelines, self.w)
                if r is not None and (best is None or self.cost(r) - base < best[0] - EPS):
                    best = (self.cost(r) - base, k, pos, new, r)
        return best


def _orderings(inst: Instance) -> list:
    """Deterministic customer orders for multi-start construction (first = most urgent first)."""
    w, d = inst.customer_window, lambda c: inst.dist(inst.depot_node, c)
    keys = [
        lambda c: (w[c][1], w[c][0]),  # latest deadline first
        lambda c: (w[c][0], w[c][1]),  # earliest opening first
        lambda c: (w[c][1] - w[c][0], w[c][1]),  # tightest window first
        lambda c: (-d(c), w[c][1]),  # farthest from depot first
    ]
    return [sorted(inst.customers, key=lambda c, key=key: (*key(c), str(c))) for key in keys]


def _build(inst: Instance, wait_weight: float, order: list) -> tuple[_State, list]:
    st = _State(inst, wait_weight)
    unserved = []

    # 1-4. Greedy insertion in the given order.
    for c in order:
        best = st.best_insertion(c)
        if best is None:
            unserved.append(c)
        else:
            st.commit(best[1], best[3], best[4])

    # 5. Local search until no move improves (max 10 passes): relocate, 2-opt, swap.
    for _ in range(10):
        improved = False
        for k in list(st.routes):
            # relocate: take c out of k, reinsert at its cheapest position anywhere
            for c in list(st.routes[k]):
                if c not in st.routes[k]:
                    continue
                before, snap = st.total(), st.snapshot()
                rest = [x for x in st.routes[k] if x != c]
                r = evaluate_route(inst, k, rest, st.timelines, wait_weight)
                if r is None:
                    continue
                st.commit(k, rest, r)
                best = st.best_insertion(c)
                if best is not None:
                    st.commit(best[1], best[3], best[4])
                if best is not None and st.total() < before - 1e-6:
                    improved = True
                else:
                    st.restore(snap)
            # 2-opt: reverse a segment of k's route
            n = len(st.routes[k])
            for i in range(n - 1):
                for j in range(i + 1, n):
                    seq = st.routes[k]
                    improved |= st.attempt([(k, seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:])])
        for k, l in itertools.combinations(list(st.routes), 2):
            # swap: exchange one customer between two routes
            for c in list(st.routes[k]):
                for d in list(st.routes[l]):
                    if c not in st.routes[k] or d not in st.routes[l]:
                        continue
                    new_k = [d if x == c else x for x in st.routes[k]]
                    new_l = [c if x == d else x for x in st.routes[l]]
                    improved |= st.attempt([(k, new_k), (l, new_l)])
            # 2-opt*: exchange the tails of two routes
            for i in range(len(st.routes[k]) + 1):
                for j in range(len(st.routes[l]) + 1):
                    rk, rl = st.routes[k], st.routes[l]
                    if i > len(rk) or j > len(rl):
                        continue
                    improved |= st.attempt([(k, rk[:i] + rl[j:]), (l, rl[:j] + rk[i:])])
        if not improved:
            break
    return st, unserved


def _routes_to_plan(inst: Instance, routes: dict, results: dict, unserved: list) -> dict:
    """{vehicle: customer sequence} + {vehicle: RouteResult} -> the shared route-plan format."""
    out = []
    for v in inst.vehicles:
        k = v["vehicle_id"]
        if not routes.get(k):
            continue
        res = results[k]
        stops = [inst.depot_node] + [s for s, _ in res.stops]
        times = [inst.depot_open_min] + [round(t, 4) for _, t in res.stops]
        charging = [{
            "station_id": sid, "plug_type_used": p,
            "planned_arrival_time": round(start, 4), "actual_arrival_time": round(start, 4),
            "wait_time_minutes": 0.0, "energy_requested_kwh": kwh,
            "planned_charge_start": round(start, 4),
        } for sid, p, _, start, _, kwh in res.charges]
        out.append({"vehicle_id": k, "stop_sequence": stops, "planned_arrival_times": times,
                    "actual_arrival_times": list(times), "charging_stops": charging})
    return {"routes": out, "unserved_customers": list(unserved)}


def solve_heuristic(instance: Instance, station_overrides: dict | None = None,
                    wait_weight: float = 0.5) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    inst = apply_overrides(instance, station_overrides)
    # Multi-start: keep the best (fewest unserved, then lowest cost; first ordering wins ties).
    runs = [_build(inst, wait_weight, order) for order in _orderings(inst)]
    st, unserved = min(runs, key=lambda run: (len(run[1]), run[0].total()))

    return _routes_to_plan(inst, st.routes, st.results, unserved), {
        "runtime_s": time.perf_counter() - t0,
        "n_unserved": len(unserved),
        "internal_cost": st.total(),
    }


if __name__ == "__main__":
    from solver.instance import make_toy_instance
    from solver.milp import explain_solution

    toy = make_toy_instance()
    plan, info = solve_heuristic(toy)
    print(info)
    print(explain_solution(plan, toy))
