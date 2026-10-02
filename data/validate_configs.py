"""
data/validate_configs.py

Fail-fast checks for data/fleet_config.json and data/stations_config.json against
docs/data_contract.md (+ the thane benchmark, if present).

    python data/validate_configs.py              # exit code 1 on any error

From code:  from data.validate_configs import validate;  errors, warnings = validate(fleet, stations, bench)
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUG_TYPES = {"LEV", "CCS2", "Type2"}
VEHICLE_TYPES = {"e-2W", "e-3W", "e-4W"}
# Plausible ranges for Indian commercial EVs (battery kWh, consumption kWh/km). Outside -> warning only.
REALISTIC = {"e-2W": ((1.5, 6.0), (0.015, 0.05)),
             "e-3W": ((4.0, 15.0), (0.04, 0.12)),
             "e-4W": ((15.0, 60.0), (0.10, 0.25))}
FLEET_KEYS = {"vehicle_id": str, "vehicle_type": str, "battery_capacity_kwh": (int, float),
              "energy_consumption_per_km": (int, float), "compatible_plugs": list}
STATION_KEYS = {"station_id": str, "node_id": int, "plugs": dict, "charge_rate_kwh_per_hour": dict}


def _schema(items, keys, label, errors):
    if not isinstance(items, list) or not items:
        errors.append(f"{label}: must be a non-empty JSON list")
        return False
    for i, item in enumerate(items):
        for key, typ in keys.items():
            if key not in item:
                errors.append(f"{label}[{i}]: missing '{key}'")
            elif not isinstance(item[key], typ) or isinstance(item[key], bool):
                errors.append(f"{label}[{i}].{key}: wrong type {type(item[key]).__name__}")
        extra = set(item) - set(keys)
        if extra:
            errors.append(f"{label}[{i}]: unknown fields {sorted(extra)} (not in data_contract.md)")
    return not errors


def validate(fleet, stations, bench=None):
    errors, warnings = [], []
    if not (_schema(fleet, FLEET_KEYS, "fleet", errors) & _schema(stations, STATION_KEYS, "stations", errors)):
        return errors, warnings

    for label, items, key in (("vehicle_id", fleet, "vehicle_id"), ("station_id", stations, "station_id")):
        ids = [x[key] for x in items]
        dups = sorted({i for i in ids if ids.count(i) > 1})
        if dups:
            errors.append(f"duplicate {label}s: {dups}")

    for s in stations:
        sid = s["station_id"]
        for p, n in s["plugs"].items():
            if p not in PLUG_TYPES:
                errors.append(f"{sid}: unknown plug type '{p}'")
            if not isinstance(n, int) or n < 0:
                errors.append(f"{sid}: plug count for {p} must be an integer >= 0")
            if n > 0 and not s["charge_rate_kwh_per_hour"].get(p, 0) > 0:
                errors.append(f"{sid}: {p} has plugs but no positive charge rate")
        if sum(s["plugs"].values()) == 0:
            warnings.append(f"{sid}: has no plugs at all")

    available = {p for s in stations for p, n in s["plugs"].items() if n > 0}
    for v in fleet:
        vid, vt = v["vehicle_id"], v["vehicle_type"]
        if vt not in VEHICLE_TYPES:
            errors.append(f"{vid}: unknown vehicle_type '{vt}'")
        bad = set(v["compatible_plugs"]) - PLUG_TYPES
        if bad:
            errors.append(f"{vid}: unknown plug types {sorted(bad)}")
        if not set(v["compatible_plugs"]) & available:
            errors.append(f"{vid}: no compatible plug exists at any station (instance would be unsolvable)")
        q, e = v["battery_capacity_kwh"], v["energy_consumption_per_km"]
        if q <= 0 or e <= 0:
            errors.append(f"{vid}: battery and consumption must be > 0")
        elif vt in REALISTIC:
            (qlo, qhi), (elo, ehi) = REALISTIC[vt]
            if not qlo <= q <= qhi:
                warnings.append(f"{vid}: battery {q} kWh unusual for {vt} (expected {qlo}-{qhi})")
            if not elo <= e <= ehi:
                warnings.append(f"{vid}: consumption {e} kWh/km unusual for {vt} (expected {elo}-{ehi})")

    if bench is not None:
        nodes, matrix = bench["nodes"], bench["distance_matrix"]
        for s in stations:
            if str(s["node_id"]) not in nodes:
                errors.append(f"{s['station_id']}: node {s['node_id']} not on the Thane road graph")
            elif str(s["node_id"]) not in matrix:
                errors.append(f"{s['station_id']}: node {s['node_id']} not in distance_matrix "
                              f"(re-run: python data_pipeline/generate_thane_network.py --force)")
    return errors, warnings


def main():
    def load(name):
        path = os.path.join(HERE, name)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        with open(path) as f:
            return json.load(f)

    fleet, stations, bench = load("fleet_config.json"), load("stations_config.json"), load("thane_benchmark.json")
    if fleet is None or stations is None:
        sys.exit("fleet_config.json / stations_config.json missing or empty")
    errors, warnings = validate(fleet, stations, bench)
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        sys.exit(1)
    print(f"OK: {len(fleet)} vehicles, {len(stations)} stations" + ("" if bench else " (benchmark not checked)"))


if __name__ == "__main__":
    main()
