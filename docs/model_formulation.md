# Model Formulation: EVRPTW-HCC

**Electric Vehicle Routing Problem with Time Windows and Heterogeneous Compatibility-Constrained Charging**

This is the locked mathematical specification for the project. Every module (`solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, `solver/simulator.py`) must be built against this exact formulation. If the math changes, all four modules must be revisited together.

---

## 1. Sets and Indices

- **V**: Set of all nodes, where V = {o} ∪ {e} ∪ C ∪ S̃ (o = depot start copy, e = depot end copy). The depot is split internally into a *start* node o and an *end* node e so the return-leg arrival time has its own variable. The output plan still shows `0 → … → 0`.
- **C**: Set of customer delivery nodes.
- **S**: Set of physical charging stations.
- **S̃**: Expanded set of station visit copies — each station s is duplicated up to `max_station_visits` times (default 1) so a vehicle may charge more than once at the same station.
- **K**: Set of all vehicles in the heterogeneous fleet (e.g., e-2W, e-3W, e-4W).
- **P**: Set of all charging plug types (e.g., LEV, CCS2, Type2).
- **U(s,p)**: Set of physical plug units of type p at station s — `|U(s,p)| = N_{s,p}`. Each unit u ∈ U(s,p) is a bookable resource; two vehicles assigned to the same unit must not overlap in time (D3).

## 2. Parameters (Data Inputs)

- **d_ij**: Distance (km) from node i to node j.
- **t_ij**: Travel time (min) from node i to node j.
- **e_ij^k**: Energy consumed (kWh) by vehicle k traveling from i to j. `e_ij^k = d_ij × consumption_per_km^k`.
- **Q^k**: Maximum battery capacity (kWh) of vehicle k.
- **[a_i, b_i]**: Permitted arrival time window at node i (minutes from midnight).
- **s_i**: Service time at node i (minutes; 0 for stations and depot).
- **N_{s,p}**: Total number of physical plugs of type p at station s.
- **comp_{k,p}**: Binary compatibility matrix — 1 if vehicle k can physically use plug p, 0 otherwise.
- **r_{s,p}**: Charging rate of plug type p at station s (kWh/hour).
- **M_{ij}**: Per-arc Big-M — computed from the data (never a blanket 1e6). Each Big-M has a comment in `solver/milp.py` explaining how it was derived.
- **T_horizon**: Planning horizon in minutes (latest time window close + 120 min buffer).

## 3. Decision Variables

- **x_ij^k ∈ {0,1}**: 1 if vehicle k travels directly from node i to node j, 0 otherwise.
- **y_{s,p}^k ∈ {0,1}**: 1 if vehicle k charges at station s using plug type p, 0 otherwise.
- **c_i^k ≥ 0**: Amount of energy (kWh) vehicle k charges at node i. Fixed to 0 for all i ∉ S̃.
- **h_{s,p}^k ≥ 0**: Charging duration (min) for vehicle k at station s on plug type p. Linearised from c / r to avoid a nonlinear product (see §5-B).
- **τ_i^k ≥ 0**: Arrival time (min) of vehicle k at node i. For customers, τ equals service start; for stations, τ equals charge start. Any slack is absorbed by departing the *previous* stop later — so planned_arrival_time at a customer equals τ (no early arrivals) and planned_arrival_time at a station equals planned_charge_start (no planned queueing).
- **B_i^k ≥ 0**: Battery state-of-charge (kWh) of vehicle k upon arrival at node i.
- **δ_{u,k1,k2} ∈ {0,1}**: Ordering binary for D3 — 1 if vehicle k1 finishes charging on unit u before vehicle k2 starts. One binary per ordered pair (k1, k2) of distinct vehicles that both use unit u.

## 4. Objective Function

Minimise total routing distance across the fleet, with a small tie-breaker (≤ 0.001 km total weight) that prefers plans where vehicles finish earlier:

```
min  Σ_k∈K Σ_{i,j}∈V  d_ij · x_ij^k  +  ε · Σ_k∈K τ_e^k
```

where ε is chosen so the tie-breaker can never outweigh a 1 km route difference.

> **Consistency note:** This internal MILP objective (pure distance + tiny tie-breaker) need not match the heuristic's internal search objective. What must be identical across all methods is the *shared post-simulation evaluation* — `solver/objective.py`'s `calculate_route_cost()` — applied uniformly after the Reality Engine simulator has annotated actual arrival times.

## 5. Core Constraints

### A. Routing & Flow Conservation

Every customer must be visited exactly once:
```
Σ_k∈K Σ_{i∈V, i≠j}  x_ij^k = 1     ∀j ∈ C
```

Flow conservation — if a vehicle arrives at a node, it must leave:
```
Σ_{i∈V} x_ij^k − Σ_{i∈V} x_ji^k = 0     ∀j ∈ C ∪ S̃, ∀k ∈ K
```

Depot constraints — each vehicle departs at most once from o, and returns to e iff it departed:
```
Σ_{j∈C∪S̃}  x_{o,j}^k ≤ 1                              ∀k ∈ K
Σ_{i∈C∪S̃}  x_{i,e}^k  =  Σ_{j∈C∪S̃}  x_{o,j}^k        ∀k ∈ K
```

### B. Time Windows, Scheduling & Linearised Charging Duration (D2)

Charging duration h is linearised to avoid a nonlinear c/r product:

```
h_{s,p}^k = (60 / r_{s,p}) · c_s^k                      ∀s ∈ S̃, ∀p ∈ P, ∀k ∈ K
```

Since r_{s,p} is a constant, this is a linear equality. The charging-time term in the arrival propagation uses h rather than c/r directly:

```
τ_i^k + s_i + h_{i,p}^k + t_ij − M_{ij}(1 − x_ij^k)  ≤  τ_j^k     ∀i,j ∈ V, ∀k ∈ K, ∀p ∈ P
```

*(h is 0 for any non-station arc, since c_i^k = 0 there.)*

Time window enforcement:
```
a_i ≤ τ_i^k ≤ b_i     ∀i ∈ V, ∀k ∈ K
```

### C. Battery & Energy Limits

Battery evolves based on travel consumption and charging received:
```
B_j^k ≤ B_i^k + c_i^k − e_ij^k + M(1 − x_ij^k)     ∀i,j ∈ V, ∀k ∈ K
```

Battery cannot exceed capacity or drop below zero:
```
0 ≤ B_i^k ≤ Q^k     ∀i ∈ V, ∀k ∈ K
```

Vehicles start full at the depot:
```
B_o^k = Q^k     ∀k ∈ K
```

Charging amount cannot push battery past capacity, and is non-zero only at stations where a compatible plug is used:
```
c_i^k ≤ Q^k − B_i^k                                    ∀i ∈ V, ∀k ∈ K
c_i^k = 0                                               ∀i ∉ S̃, ∀k ∈ K
c_i^k ≤ M · Σ_{p∈P} y_{i,p}^k                         ∀i ∈ S̃, ∀k ∈ K
```

### D. HCC Constraints (This Paper's Novelty)

**D1 — Plug Compatibility:** A vehicle can only use a plug type it is physically compatible with:
```
y_{s,p}^k ≤ comp_{k,p}     ∀s ∈ S̃, ∀p ∈ P, ∀k ∈ K
```

**D2 — Visit Linkage:** A vehicle can only use a plug if it actually visits that station:
```
Σ_{p∈P}  y_{s,p}^k  ≤  Σ_{i∈V}  x_{i,s}^k     ∀s ∈ S̃, ∀k ∈ K
```

**D3 — Exact Per-Type Plug Capacity (pairwise ordering):** Each physical plug unit u ∈ U(s,p) can serve at most one vehicle at a time. For every pair of vehicles (k1, k2) both assigned to unit u:

```
τ_{s}^{k1} + h_{s,p}^{k1} ≤ τ_{s}^{k2} + M_{u}(1 − δ_{u,k1,k2})       (k1 finishes before k2 starts)
τ_{s}^{k2} + h_{s,p}^{k2} ≤ τ_{s}^{k1} + M_{u} · δ_{u,k1,k2}           (k2 finishes before k1 starts)
δ_{u,k1,k2} + δ_{u,k2,k1} = 1                                            (exactly one ordering holds)
```

This replaces the earlier "Strategic Note" that allowed approximate capacity — D3 enforces exact, hard, per-slot capacity directly in the MILP. No vehicle pair can share a plug unit at the same time. The Reality Engine simulator enforces the same constraint at runtime via FIFO queues, making both the solver and the simulator consistent.

## 6. Decisions — Locked

- [x] **Depot split (o, e):** Internally implemented in `solver/milp.py`. The output plan shows `0 → … → 0`.
- [x] **Partial charging enabled:** Vehicles may request less than a full charge (c_i^k is a continuous variable).
- [x] **Unused vehicles permitted:** Not every vehicle in K must be dispatched (depot departure constraint uses ≤ 1).
- [x] **Linearised charging time h (D2):** Avoids a nonlinear c/r term in arrival propagation.
- [x] **Exact plug-unit capacity enforced (D3):** Pairwise ordering binaries prevent simultaneous sharing of a physical plug unit.
- [x] **Charging rates r_{s,p}** sourced from real Indian EV standards (see `docs/data_contract.md` for full citations):
  - LEV: 3.3 kW/hour (Bharat AC-001, IS:17017)
  - CCS2: 30 kW/hour (representative Indian public DC fast-charging rate)
  - Type2: 22 kW/hour (IEC 62196 Type 2 standard)

This contract is now fully locked. Any further change to these values or constraints must be re-synced across `solver/milp.py`, `solver/heuristic.py`, `solver/baselines.py`, and `solver/simulator.py` together.
