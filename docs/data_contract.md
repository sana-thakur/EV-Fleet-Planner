# Data Contract

This document defines the exact data structures that pass between every module in the project. **Every AI agent used to write `solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, and `solver/simulator.py` must be given this document as context.** If these field names or shapes drift between modules, integration will fail silently or crash outright.

---

## 1. `fleet_config.json`

Defines the heterogeneous fleet — vehicle types, battery capacities, and plug compatibility.

```json
[
  {
    "vehicle_id": "V_001",
    "vehicle_type": "e-2W",
    "battery_capacity_kwh": 3.0,
    "energy_consumption_per_km": 0.025,
    "compatible_plugs": ["LEV"]
  },
  {
    "vehicle_id": "V_004",
    "vehicle_type": "e-4W",
    "battery_capacity_kwh": 30.0,
    "energy_consumption_per_km": 0.15,
    "compatible_plugs": ["CCS2", "Type2"]
  }
]
```

## 2. `stations_config.json`

Places charging infrastructure on the real-world road network. `node_id` must match a node ID from `thane_benchmark.json`. Also defines each plug type's charging rate, needed by the time-window constraint in `model_formulation.md`.

```json
[
  {
    "station_id": "S_01",
    "node_id": 45392011,
    "plugs": { "LEV": 2, "CCS2": 1, "Type2": 0 },
    "charge_rate_kwh_per_hour": { "LEV": 3.3, "CCS2": 30.0, "Type2": 22.0 }
  },
  {
    "station_id": "S_02",
    "node_id": 88392033,
    "plugs": { "LEV": 4, "CCS2": 2, "Type2": 1 },
    "charge_rate_kwh_per_hour": { "LEV": 3.3, "CCS2": 30.0, "Type2": 22.0 }
  }
]
```

**Source for charge rates** (used as the default across all stations unless your team decides to vary them per station):
- **LEV — 3.3 kW**: Bharat AC-001 standard under IS:17017 (230V, 15A, 3.3 kW), India's standard for light EV (e-2W/e-3W) AC charging. [Wikipedia — Plug-in electric vehicles in India](https://en.wikipedia.org/wiki/Plug-in_electric_vehicles_in_India)
- **CCS2 — 30 kW**: Representative entry-tier rating for Indian public DC fast-charging rollouts (Tata Power's early CCS2 stations were specified at 30–50 kW). [EVreporter — A Guide to EV Charging and EV Standards in India](https://evreporter.com/guide-to-ev-charging-and-standards-in-india/)
- **Type2 — 22 kW**: Standard AC Level 2/3 rating under IEC 62196 Type 2 (≥22 kW), adopted in India for higher-power AC charging. [Wikipedia — IEC 62196](https://en.wikipedia.org/wiki/IEC_62196)

These are reasonable defaults for a benchmark model — real CCS2 installations in India range roughly 30–60 kW depending on the operator, so this is a conservative, defensible midpoint rather than an outlier figure.

## 3. Route Plan — Solver Output / Simulator Input

This is not a static file — it's the exact structure every solver (MILP, heuristic, baselines) must produce, and the exact structure the simulator consumes and *annotates*.

**Two states of this object matter:**
- **Planned** — produced directly by a solver, before simulation. `actual_arrival_time`, `wait_time_minutes`, and `unserved_customers` are not yet known.
- **Simulated** — the same structure, after being run through the Reality Engine. The simulator fills in the "actual" fields based on real FIFO queueing.

```json
[
  {
    "vehicle_id": "V_001",
    "stop_sequence": [0, 45, 12, "S_01", 33, 0],
    "planned_arrival_times": [0.0, 15.2, 30.5, 45.0, 80.1, 110.0],
    "actual_arrival_times": [0.0, 15.2, 30.5, 52.0, 87.0, 117.0],
    "charging_stops": [
      {
        "station_id": "S_01",
        "plug_type_used": "LEV",
        "planned_arrival_time": 45.0,
        "actual_arrival_time": 52.0,
        "wait_time_minutes": 7.0,
        "energy_requested_kwh": 2.5
      }
    ]
  }
],
"unserved_customers": []
```

**Field notes:**
- `stop_sequence`: node IDs in visiting order; station stops use their `station_id` string instead of a numeric node ID.
- `planned_arrival_times`: written by the solver (MILP/heuristic/baseline) — always present.
- `actual_arrival_times`: written by the simulator. Before simulation, agents should default this to equal `planned_arrival_times` (i.e., assume zero queue wait) so `calculate_route_cost()` can still run on a plan that hasn't been simulated yet.
- `wait_time_minutes`: `actual_arrival_time − planned_arrival_time` at that charging stop. Written by the simulator; defaults to 0 pre-simulation.
- `unserved_customers`: a **route-plan-level** (not per-vehicle) list of customer node IDs that were never reached — e.g., a vehicle stranded with a dead battery, or a route abandoned because the simulator determined it was infeasible. Always empty for solver output that hasn't been simulated yet; only the simulator populates this.

This structure is what makes the "Price of Ignoring Reality" experiment work: run the *same* planned route through the simulator, compare `planned_arrival_times` vs. `actual_arrival_times`, and feed both versions into `calculate_route_cost()` to get the "looks fine on paper" score vs. the "what actually happened" score.
