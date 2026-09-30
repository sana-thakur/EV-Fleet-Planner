"""
solver/instance.py

Instance loader + hand-verifiable toy instance + small random instances.
Shared by milp.py, heuristic.py and plan_checker.py.

Units everywhere: time in MINUTES, distance in KM, energy in kWh.
Distance/time matrices are keyed by STRING node ids; each station_id
(e.g. "S_01") is also a key, aliased to that station's node row/column.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any

NodeId = Any  # int for OSM/customer/depot nodes, str for station_id


@dataclass(frozen=True)
class Instance:
    depot_node: NodeId
    customers: list
    customer_window: dict  # {node: (a, b)}
    service_time: dict  # {node: minutes}
    stations: list  # stations_config.json dicts
    vehicles: list  # fleet_config.json dicts
    plug_types: list  # sorted
    dist_km: dict  # dist_km[str(u)][str(v)]
    time_min: dict  # time_min[str(u)][str(v)]
    horizon_min: float
    _station: dict = field(init=False, repr=False, compare=False)
    _vehicle: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_station", {s["station_id"]: s for s in self.stations})
        object.__setattr__(self, "_vehicle", {v["vehicle_id"]: v for v in self.vehicles})

    def vehicle(self, vehicle_id: str) -> dict:
        return self._vehicle[vehicle_id]

    def station(self, station_id: str) -> dict:
        return self._station[station_id]

    def compatible(self, vehicle_id: str, plug: str) -> bool:
        return plug in self._vehicle[vehicle_id]["compatible_plugs"]

    def plugs(self, station_id: str, plug: str) -> int:
        return int(self._station[station_id]["plugs"].get(plug, 0))

    def rate(self, station_id: str, plug: str) -> float:
        """Charge rate in kWh per hour."""
        return float(self._station[station_id]["charge_rate_kwh_per_hour"][plug])

    def dist(self, u: NodeId, v: NodeId) -> float:
        return self.dist_km[str(u)][str(v)]

    def time(self, u: NodeId, v: NodeId) -> float:
        return self.time_min[str(u)][str(v)]

    def energy(self, vehicle_id: str, u: NodeId, v: NodeId) -> float:
        return self.dist(u, v) * self._vehicle[vehicle_id]["energy_consumption_per_km"]

    def charge_minutes(self, station_id: str, plug: str, kwh: float) -> float:
        return 60.0 * kwh / self.rate(station_id, plug)

    def usable_plugs(self, vehicle_id: str, station_id: str) -> list:
        """Plug types at this station the vehicle can use (compatible and plugs > 0)."""
        return [p for p in self.plug_types if self.compatible(vehicle_id, p) and self.plugs(station_id, p) > 0]


def _alias_stations(matrix: dict, stations: list) -> dict:
    """Copy the matrix and add station_id rows/columns aliased to the station's node."""
    m = {u: dict(row) for u, row in matrix.items()}
    alias = {s["station_id"]: str(s["node_id"]) for s in stations}
    for row in m.values():
        for sid, node in alias.items():
            row[sid] = row[node]
    for sid, node in alias.items():
        m[sid] = dict(m[node])
    return m


def build_instance(
    depot_node: NodeId,
    customers: list[dict],
    stations: list,
    vehicles: list,
    dist_km: dict,
    time_min: dict,
    horizon_min: float | None = None,
) -> Instance:
    """Validate raw data and build an Instance. `customers` use the temporary customers-file shape."""
    nodes = set(dist_km)
    errors = []
    if str(depot_node) not in nodes:
        errors.append(f"depot node {depot_node} not in distance matrix")
    for c in customers:
        if str(c["node_id"]) not in nodes:
            errors.append(f"customer node {c['node_id']} not in distance matrix")
        a, b = c["time_window"]
        if a > b:
            errors.append(f"customer {c['node_id']}: time window a={a} > b={b}")
    for s in stations:
        if str(s["node_id"]) not in nodes:
            errors.append(f"station {s['station_id']} node {s['node_id']} not in distance matrix")
    available = {p for s in stations for p, n in s["plugs"].items() if n > 0}
    for v in vehicles:
        if not set(v["compatible_plugs"]) & available:
            errors.append(f"vehicle {v['vehicle_id']} has no compatible plug type available anywhere")
    if set(time_min) != nodes:
        errors.append("time matrix and distance matrix have different node sets")
    if errors:
        raise ValueError("Invalid instance:\n  " + "\n  ".join(errors))

    windows = {c["node_id"]: tuple(c["time_window"]) for c in customers}
    return Instance(
        depot_node=depot_node,
        customers=[c["node_id"] for c in customers],
        customer_window=windows,
        service_time={c["node_id"]: c.get("service_time_min", 5) for c in customers},
        stations=stations,
        vehicles=vehicles,
        plug_types=sorted({p for s in stations for p in s["plugs"]} | {p for v in vehicles for p in v["compatible_plugs"]}),
        dist_km=_alias_stations(dist_km, stations),
        time_min=_alias_stations(time_min, stations),
        horizon_min=horizon_min if horizon_min is not None else max((b for _, b in windows.values()), default=0) + 120,
    )


def load_instance(benchmark_path: str, fleet_path: str, stations_path: str, customers_path: str) -> Instance:
    """
    Load an Instance from JSON files.

    ASSUMED benchmark shape (thane_benchmark.json has no contract yet — confirm with Workstream C):
        {"distance_matrix": {"<node>": {"<node>": km}}, "time_matrix": {"<node>": {"<node>": minutes}}}
    TEMPORARY customers shape (until added to docs/data_contract.md):
        {"depot_node": <node_id>, "customers": [{"node_id": ..., "time_window": [a, b], "service_time_min": 5}]}
    """
    def read(path):
        with open(path) as f:
            return json.load(f)

    bench, cust = read(benchmark_path), read(customers_path)
    return build_instance(
        depot_node=cust["depot_node"],
        customers=cust["customers"],
        stations=read(stations_path),
        vehicles=read(fleet_path),
        dist_km=bench["distance_matrix"],
        time_min=bench["time_matrix"],
    )


# ---------------------------------------------------------------------------
# TOY INSTANCE — intended optimal solution (verify by hand):
#
# Manhattan grid (km), speed 30 km/h so time_min = 2 * dist_km.
#   D=0 (0,0)   S_01=5 (0,40)   C1=1 (-10,70)   C2=2 (10,70)   C3=3 (0,-65)   C4=4 (10,-65)
#
# * South cluster (C3, C4): D->C3->C4->D = 65+10+75 = 150 km. A 2W needs 3.75 kWh
#   (> 3.0) and no station is reachable in the south, so ONLY the e-4W can serve it
#   (150 * 0.15 = 22.5 kWh < 30, no charge needed -> the CCS2 plug stays idle).
# * North (C1, C2): both windows are [160, 180]; C1-C2 is 20 km = 40 min apart, so no
#   vehicle can serve both, and the 4W is busy in the south at the same time. So each
#   2W serves one north customer: D->C->D = 160 km = 4.0 kWh > 3.0, so each MUST charge
#   >= 1.0 kWh at S_01 (S_01 lies on a shortest path, so no detour km).
#   1 kWh on LEV takes 60 * 1.0 / 3.3 = 18.18 min.
# * The single LEV plug is the bottleneck. Outbound, both reach S_01 at 80 min:
#   first charges 80-98.2 and reaches its customer at 178.2 (ok); the second would
#   charge 98.2-116.4 and arrive at 196.4 > 180 (late). A capacity-blind plan charges
#   both outbound in parallel -- that is the trap.
# * Intended optimum: 2W #1 charges OUTBOUND (LEV 80-98.2), 2W #2 charges on the
#   RETURN leg (customer 160, service 5, back at S_01 at 245, LEV 245-263.2).
#   No overlap, no waiting; both finish at 343.2. (Charging both on the return also
#   costs 470 km, but the 2nd must wait until 263.2 -> the finish-time tie-breaker
#   prefers the split.) Neither 2W may touch the idle CCS2 plug.
# * Optimal total distance = 160 + 160 + 150 = 470 km.
# ---------------------------------------------------------------------------
def make_toy_instance() -> Instance:
    coords = {0: (0, 0), 1: (-10, 70), 2: (10, 70), 3: (0, -65), 4: (10, -65), 5: (0, 40)}
    dist = {str(u): {str(v): float(abs(pu[0] - pv[0]) + abs(pu[1] - pv[1])) for v, pv in coords.items()} for u, pu in coords.items()}
    time = {u: {v: 2.0 * d for v, d in row.items()} for u, row in dist.items()}
    customers = [
        {"node_id": 1, "time_window": [160, 180], "service_time_min": 5},
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
    return build_instance(0, customers, stations, vehicles, dist, time, horizon_min=480)


def make_random_instance(n_customers: int, n_vehicles: int, seed: int) -> Instance:
    """Small synthetic Euclidean instance on a 70x70 km square, depot at the centre, speed 30 km/h.
    Sized so real fleet ranges (2W 120 km, 3W ~117 km, 4W 140 km) make charging matter."""
    rng = random.Random(seed)
    n_stations = 2
    coords = {0: (35.0, 35.0)}
    for i in range(1, n_customers + n_stations + 1):
        coords[i] = (rng.uniform(0, 70), rng.uniform(0, 70))
    dist = {str(u): {str(v): round(math.dist(pu, pv), 1) for v, pv in coords.items()} for u, pu in coords.items()}
    time = {u: {v: 2.0 * d for v, d in row.items()} for u, row in dist.items()}

    customers = []
    for i in range(1, n_customers + 1):
        a = rng.randrange(60, 360, 10)
        customers.append({"node_id": i, "time_window": [a, a + rng.choice([60, 90, 120])], "service_time_min": 5})
    rates = {"LEV": 3.3, "CCS2": 30.0, "Type2": 22.0}
    stations = [
        {"station_id": f"S_{j:02d}", "node_id": n_customers + j,
         "plugs": {"LEV": 1, "CCS2": 1, "Type2": j - 1}, "charge_rate_kwh_per_hour": rates}
        for j in range(1, n_stations + 1)
    ]
    types = [
        ("e-2W", 3.0, 0.025, ["LEV"]),
        ("e-3W", 7.0, 0.06, ["LEV", "Type2"]),
        ("e-4W", 21.0, 0.15, ["CCS2", "Type2"]),
    ]
    vehicles = []
    for k in range(n_vehicles):
        vt, q, e, plugs = types[k % 3]
        vehicles.append({"vehicle_id": f"V_{k + 1:03d}", "vehicle_type": vt, "battery_capacity_kwh": q,
                         "energy_consumption_per_km": e, "compatible_plugs": plugs})
    return build_instance(0, customers, stations, vehicles, dist, time)
