# Data Contract

This document defines the exact data structures that pass between every module in the project. **Every module (`solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, and `solver/simulator.py`) must conform to this schema.** If these field names or shapes drift between modules, integration will fail silently or crash outright.

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

**Source for charge rates** (used as the default across all stations):
- **LEV — 3.3 kW**: Bharat AC-001 standard under IS:17017 (230V, 15A, 3.3 kW), India's standard for light EV (e-2W/e-3W) AC charging. [Wikipedia — Plug-in electric vehicles in India](https://en.wikipedia.org/wiki/Plug-in_electric_vehicles_in_India)
- **CCS2 — 30 kW**: Representative entry-tier rating for Indian public DC fast-charging rollouts (Tata Power's early CCS2 stations were specified at 30–50 kW). [EVreporter — A Guide to EV Charging and EV Standards in India](https://evreporter.com/guide-to-ev-charging-and-standards-in-india/)
- **Type2 — 22 kW**: Standard AC Level 2/3 rating under IEC 62196 Type 2 (≥22 kW), adopted in India for higher-power AC charging. [Wikipedia — IEC 62196](https://en.wikipedia.org/wiki/IEC_62196)

These are reasonable defaults — real CCS2 installations in India range roughly 30–60 kW depending on the operator, so this is a conservative, defensible midpoint.

## 3. Route Plan — Solver Output / Simulator Input

This is not a static file — it is the exact structure every solver (MILP, heuristic, baselines) must produce, and the exact structure the simulator consumes and *annotates*.

**Two states of this object matter:**
- **Planned** — produced directly by a solver, before simulation. `actual_arrival_times`, `actual_charge_start`, `actual_charge_end`, and `wait_time_minutes` are not yet set (or default to 0 / equal to planned values).
- **Simulated** — the same structure, after being run through the Reality Engine. The simulator fills in all `actual_*` fields based on real FIFO queueing and hard plug capacity enforcement.

```json
{
  "routes": [
    {
      "vehicle_id": "V_001",
      "stop_sequence": [0, 45, 12, "S_01", 33, 0],
      "planned_arrival_times": [0.0, 15.2, 30.5, 45.0, 80.1, 110.0],
      "actual_arrival_times":  [0.0, 15.2, 30.5, 52.0, 87.0, 117.0],
      "charging_stops": [
        {
          "station_id": "S_01",
          "plug_type_used": "LEV",
          "energy_requested_kwh": 2.5,
          "planned_arrival_time": 45.0,
          "planned_charge_start": 45.0,
          "actual_arrival_time": 52.0,
          "wait_time_minutes": 7.0,
          "actual_charge_start": 52.0,
          "actual_charge_end": 70.5
        }
      ],
      "stranded": false,
      "stranding_reason": null
    }
  ],
  "unserved_customers": [],
  "meta": {
    "customers_file": "data/customers_thane_25.json",
    "solver": "heuristic",
    "simulated": false
  }
}
```

**Field notes — route level:**
- `stop_sequence`: node IDs in visiting order; station stops use their `station_id` string (e.g. `"S_01"`) rather than a numeric node ID. The first and last entry are always the depot node ID.
- `planned_arrival_times`: written by the solver — always present. Length = `len(stop_sequence)`.
- `actual_arrival_times`: written by the simulator. **Before simulation, this must equal `planned_arrival_times`** so `calculate_route_cost()` can run on unsimuated plans without error.
- `stranded`: `true` if the Reality Engine determined the vehicle ran out of battery before completing its route.
- `stranding_reason`: human-readable string describing why the vehicle was stranded, or `null`.

**Field notes — `charging_stops` entries:**
- `planned_arrival_time`: when the solver planned the vehicle to arrive at the station (= `planned_charge_start` — plans never contain deliberate queueing).
- `planned_charge_start`: equals `planned_arrival_time`. Vehicles absorb any slack by leaving the *previous* stop later, so they arrive exactly when their plug slot opens.
- `energy_requested_kwh`: how much energy the solver requested be loaded. May be less than a full charge.
- `actual_arrival_time`: written by the simulator — when the vehicle actually arrived at the station.
- `wait_time_minutes`: `actual_charge_start − actual_arrival_time`. Written by the simulator; defaults to `0.0` pre-simulation.
- `actual_charge_start`: when charging actually began (= `actual_arrival_time + wait_time_minutes`). Written by the simulator.
- `actual_charge_end`: when charging actually finished (`= actual_charge_start + 60 × energy_requested_kwh / rate_kWh_per_hour`). Written by the simulator.

**Field notes — `unserved_customers`:**
- Route-plan-level list of customer node IDs that were never reached — e.g. a vehicle stranded with a dead battery, or a customer that could not be feasibly inserted. Written by both solvers (when a customer cannot be routed at all) and the simulator (when a vehicle strands mid-route). Always `[]` for a plan that has not yet been simulated.

**Field notes — `meta`:**
- Optional block used by `app.py` (Streamlit demo) and `experiments/run_experiments.py` to identify which instance a result belongs to.
- `customers_file`: relative path to the customers JSON used to generate this plan (required by `app.py`).
- `solver`: which solver produced this plan (`"milp"`, `"heuristic"`, `"B1 (Greedy FCFS)"`, etc.).
- `simulated`: `true` if the plan has been run through `simulate_plan()`.

## 4. Units Convention

| Quantity | Unit |
|---|---|
| Time (all timestamps and durations) | **minutes** from midnight |
| Distance | **km** |
| Energy | **kWh** |
| Charging duration | `60 × kWh / rate_kWh_per_hour` minutes |

## 5. The "Price of Ignoring Reality" Experiment Schema

The central empirical contribution works as follows:

1. A solver (MILP, heuristic, or a naive baseline) produces a **planned** route plan.
2. `solver/objective.py`'s `calculate_route_cost()` scores the planned plan → the *"looks fine on paper"* score.
3. `solver/simulator.py`'s `simulate_plan()` replays the same plan under real FIFO queueing and hard plug capacity enforcement, filling `actual_arrival_times`, `wait_time_minutes`, `actual_charge_start`, `actual_charge_end`, and `unserved_customers`.
4. `calculate_route_cost()` scores the simulated plan again → the *"what actually happened"* score.
5. The gap between step 2 and step 4 is the **Price of Ignoring Reality** for that solver/baseline.

Because steps 2 and 4 use the **identical evaluation function**, any difference in the two scores is attributable solely to real-world queueing and constraint violations — not scoring methodology.
