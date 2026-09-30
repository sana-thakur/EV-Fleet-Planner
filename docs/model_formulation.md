# Model Formulation: EVRPTW-HCC

**Electric Vehicle Routing Problem with Time Windows and Heterogeneous Compatibility-Constrained Charging**

This is the locked mathematical specification for the project. Every module (`solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, `solver/simulator.py`) must be built against this exact formulation. If the math changes, all four modules must be revisited together.

---

## 1. Sets and Indices

- **V**: Set of all nodes, where V = {0} ∪ C ∪ S (0 = depot).
- **C**: Set of customer delivery nodes.
- **S**: Set of charging station nodes.
- **K**: Set of all vehicles in the heterogeneous fleet (e.g., e-2W, e-3W, e-4W).
- **P**: Set of all charging plug types (e.g., LEV, CCS2, Type2).

## 2. Parameters (Data Inputs)

- **d_ij**: Distance from node i to node j.
- **t_ij**: Travel time from node i to node j.
- **e_ij^k**: Energy consumed by vehicle k traveling from i to j.
- **Q^k**: Maximum battery capacity of vehicle k.
- **[a_i, b_i]**: Permitted arrival time window at node i.
- **s_i**: Service time at node i (time to drop off a package).
- **N_s,p**: Total number of plugs of type p available at station s.
- **comp_k,p**: Binary compatibility matrix — 1 if vehicle k can physically use plug p, 0 otherwise.
- **r_p**: Charging rate of plug type p (kWh per unit time).
- **M**: A sufficiently large positive number (Big-M), used for linearizing constraints.

## 3. Decision Variables

- **x_ij^k ∈ {0,1}**: 1 if vehicle k travels directly from node i to node j, 0 otherwise.
- **y_s,p^k ∈ {0,1}**: 1 if vehicle k charges at station s using plug p, 0 otherwise.
- **c_i^k ≥ 0**: Amount of energy (kWh) vehicle k charges at node i. Fixed to 0 for all i ∉ S.
- **τ_i^k ≥ 0**: Continuous variable tracking the arrival time of vehicle k at node i.
- **B_i^k ≥ 0**: Continuous variable tracking the state of charge (battery level) of vehicle k upon arrival at node i.

## 4. Objective Function

Minimize total routing distance across the fleet:

```
min  Σ_k∈K Σ_i∈V Σ_j∈V  d_ij · x_ij^k
```

**Note on objective consistency:** This is the *internal* objective the exact MILP optimizes while searching for a feasible, optimal plan. It intentionally stays simple (pure distance) to keep the model linear and solvable within a reasonable time. This does **not** need to match the heuristic's internal search objective. What must be identical across every method (MILP, heuristic, all baselines) is the **shared evaluation function** — `solver/objective.py`'s `calculate_route_cost()` — which is applied uniformly, *after* a plan has been run through the Reality Engine simulator, to produce the final comparable score for every method in the results tables. Consistency lives in the shared evaluation step, not in each solver's internal search objective.

## 5. Core Constraints

### A. Routing & Flow Conservation

Every customer must be visited exactly once:
```
Σ_k∈K Σ_i∈V,i≠j  x_ij^k = 1     ∀j ∈ C
```

Flow conservation — if a vehicle arrives at a node, it must leave that node:
```
Σ_i∈V x_ij^k − Σ_i∈V x_ji^k = 0     ∀j ∈ C ∪ S, ∀k ∈ K
```

**Depot constraints** — each vehicle departs the depot at most once, and returns if and only if it departed:
```
Σ_j∈C∪S  x_0j^k ≤ 1                              ∀k ∈ K
Σ_i∈C∪S  x_i0^k  =  Σ_j∈C∪S  x_0j^k              ∀k ∈ K
```

### B. Time Windows & Scheduling

Arrival time tracking (accounts for travel and service time at i, and any charging time if i is a station):
```
τ_i^k + s_i + (c_i^k / r_p) + t_ij − M(1 − x_ij^k)  ≤  τ_j^k     ∀i,j ∈ V, ∀k ∈ K
```
*(the charging-time term `c_i^k / r_p` is 0 for any non-station node, since c_i^k is fixed to 0 there)*

Time window enforcement:
```
a_i ≤ τ_i^k ≤ b_i     ∀i ∈ V, ∀k ∈ K
```

### C. Battery & Energy Limits

Battery evolves based on travel consumption and any charging received at the current node:
```
B_j^k ≤ B_i^k + c_i^k − e_ij^k + M(1 − x_ij^k)     ∀i,j ∈ V, ∀k ∈ K
```

Battery cannot exceed capacity or drop below zero:
```
0 ≤ B_i^k ≤ Q^k     ∀i ∈ V, ∀k ∈ K
```

Charging amount cannot push battery past capacity, and can only happen at stations:
```
c_i^k ≤ Q^k − B_i^k     ∀i ∈ V, ∀k ∈ K
c_i^k = 0               ∀i ∉ S, ∀k ∈ K
c_i^k ≤ M · Σ_p∈P y_i,p^k     ∀i ∈ S, ∀k ∈ K   (charging amount only nonzero if a plug is actually used)
```

*(This replaces a "full recharge only" assumption — vehicles may request a partial charge, matching the `energy_requested_kwh` field in the route plan schema.)*

### D. The HCC Constraints (This Paper's Novelty)

A vehicle can only be assigned a plug type it is physically compatible with:
```
y_s,p^k ≤ comp_k,p     ∀s ∈ S, ∀p ∈ P, ∀k ∈ K
```

A vehicle can only use a plug if it actually visits that charging station:
```
Σ_p∈P  y_s,p^k  ≤  Σ_i∈V  x_is^k     ∀s ∈ S, ∀k ∈ K
```

## Strategic Note on Station Capacity in the MILP

Modeling strict, continuous-time FIFO queueing (e.g., preventing more than N_s,p vehicles from charging at the exact same moment) linearly in a MILP is notoriously difficult and computationally heavy. For a baseline MILP solving only 5–8 vehicles, it is acceptable to use a simplified upper-bound capacity constraint (or discretized time blocks) rather than exact queueing — **because the discrete-event simulator ("Reality Engine") is where true, strict FIFO capacity enforcement happens.** The MILP only needs to produce a *plausible* plan; the simulator is what proves whether that plan survives real-world queueing.

## Decisions — Locked

- [x] **Partial charging is enabled** (vehicles may request less than a full charge, per the `c_i^k` variable above).
- [x] **Unused vehicles are permitted** — not every vehicle in the fleet must be dispatched (depot constraint uses `≤ 1`).
- [x] **Charging rates `r_p` are set as follows**, sourced from real Indian EV charging standards (see `docs/data_contract.md` for full citations):
  - LEV: 3.3 kW/hour (Bharat AC-001, IS:17017)
  - CCS2: 30 kW/hour (representative Indian public DC fast-charging rate)
  - Type2: 22 kW/hour (IEC 62196 Type 2 standard)

This contract is now fully locked. Any further change to these values or constraints must be re-synced across `solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, and `solver/simulator.py` together.
