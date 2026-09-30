# Workstream A: Optimization Core, Progress Report

**Status:** all 5 prompts from the Workstream A pack are built and tested (37 tests passing). E1 (MILP vs heuristic) runs end to end.
**Owner files only.** Nothing in `docs/`, `objective.py`, `simulator.py`, `baselines.py`, `app.py` or `data_pipeline/` was touched.

---

## 1. What was built

| File | What it does |
|---|---|
| `solver/instance.py` | Loads and validates an instance (fleet + stations + customers + distance/time matrices). Also has a hand-checkable **toy instance** and a seeded **random instance** generator. |
| `solver/milp.py` | **Exact MILP** (PuLP + HiGHS). Enforces plug compatibility **and exact per-plug-type capacity**. Also has `explain_solution()` for hand verification. |
| `solver/plan_checker.py` | **Independent checker.** Recomputes every route from scratch and lists every rule a plan breaks. Shares no code with the solvers. |
| `solver/heuristic.py` | **Timeline-Aware Greedy Insertion heuristic.** Pure Python and deterministic. Supports "break a charger" overrides. |
| `experiments/validate_heuristic.py` | E1 script: MILP vs heuristic on 13 instances, writes `results/e1_optimality_gap.csv`. |
| `tests/` | 37 tests: `test_instance.py`, `test_milp.py`, `test_plan_checker.py`, `test_heuristic.py`. |

---

## 2. How to run

```bash
python -m venv venv && source venv/bin/activate
pip install pulp highspy pytest          # needs PuLP >= 4 (see Section 6)

python -m pytest tests -q                # all tests, ~6 s
python -m solver.milp                    # solve the toy with the MILP, print per-leg breakdown
python -m solver.heuristic               # same with the heuristic
python experiments/validate_heuristic.py # E1 -> results/e1_optimality_gap.csv (~15 s)
```

Every solver returns the same thing:

```python
plan, info = solve_milp(instance)        # or solve_heuristic(instance, station_overrides={"S_01": {"LEV": 0}})
plan = {"routes": [ ...per-vehicle dicts exactly as in data_contract.md section 3... ],
        "unserved_customers": [...]}
```

---

## 3. Key results

### Toy instance: the "novelty in one picture"

There is 1 station with **1 LEV plug + 1 CCS2 plug**, two e-2Ws (LEV only) and one e-4W (CCS2/Type2).

- Each e-2W **must** charge 1 kWh to serve its customer.
- Only **one** of them can charge on the way out and still arrive within its time window.
- A capacity-blind plan would charge both on the way out at the same time. The second vehicle would then really arrive late.

Both our MILP and our heuristic find the optimum:

```
V_2W_B  charges LEV [80.0, 98.2]   on the way OUT  -> customer at 178.2 (window 160-180)
V_2W_A  charges LEV [245.0, 263.2] on the way BACK
V_4W    serves the south cluster, never charges -> CCS2 plug stays idle (2Ws can't use it)
Total 470 km, no overlap on the single LEV plug, no queue waiting.
```

We also built an instance where the capacity constraint is the **only** thing that matters. With 1 LEV plug the MILP correctly reports *Infeasible*; with 2 LEV plugs it is *Optimal*, with both vehicles charging in parallel. This proves the capacity constraint is actually doing work.

### E1: heuristic vs exact MILP

| | |
|---|---|
| Instances | toy + 12 random (5-10 customers, 2-4 vehicles, 3 seeds each) |
| MILP status | all proven **Optimal** (0.05 s to 9 s) |
| Heuristic matches the optimum | **11 / 13** |
| Mean / max gap | **1.09% / 8.07%** |
| Heuristic runtime | 5-110 ms (30 customers: ~1.5 s) |
| Plans that fail the checker | **0** (MILP and heuristic) |

Full table: `results/e1_optimality_gap.csv`.

---

## 4. How the models work (short version)

### MILP (`solver/milp.py`)
- Follows `docs/model_formulation.md`, plus the approved fixes from the prompt pack:
  - The depot is split into a **start** and an **end** node internally, so the return-leg time constraint works. The output still shows `0 ... 0`.
  - Stations can be duplicated (`max_station_visits`) so a vehicle can charge more than once.
  - **Linearised charging time** `h`: the charging duration depends on which plug is used, so it is linearised with Big-M.
  - **Exact per-type capacity (D3):** each physical plug is a "unit". Two vehicles on the same unit are forced **not to overlap in time** (pairwise ordering binaries).
- Every Big-M is computed from the data (never `1e6`), and each one has a comment explaining it.
- Objective = total km plus a tiny tie-breaker (≤ 0.001 km in total) that prefers finishing earlier.

### Heuristic (`solver/heuristic.py`)
- **PlugTimeline:** one booking calendar per physical plug unit, for each (station, plug type).
- **Route evaluation:** drives the route forward from a full battery. When the battery can't safely reach the next stop, it inserts a charging stop at the station with the best `detour_km + 0.5 × queue_wait`, on the earliest free compatible plug.
- **Two charging policies per route:**
  - *lazy*: charge only when forced;
  - *eager*: charge at the first chance, to grab a free plug before others queue.

  The cheaper of the two is kept. This is what lets the heuristic find the toy optimum.
- **Construction + improvement:**
  - Greedy cheapest insertion, run from **4 deterministic customer orderings**.
  - Local search with relocate, 2-opt, swap and 2-opt* (tail exchange).
  - The best result is kept.
- Customers that can't be served go to `unserved_customers`; nothing crashes.
- `station_overrides={"S_01": {"LEV": 0}}` = "break a charger" for the demo.

### Plan checker (`solver/plan_checker.py`)
- Uses only the plan + instance data.
- Violation types:
  - `MISSING_CUSTOMER`, `DUPLICATE_CUSTOMER`
  - `INCOMPATIBLE_PLUG`, `CAPACITY_EXCEEDED` (found with a sweep-line check)
  - `BATTERY_NEGATIVE`, `BATTERY_OVER_CAPACITY`
  - `TIME_WINDOW_LATE`, `ARRIVAL_TIME_MISMATCH`
  - `HORIZON_EXCEEDED`, `MALFORMED_ROUTE`
- It is **not** the simulator: it checks that a plan follows the model's rules, not what happens under FIFO queueing.

---

## 5. Conventions we adopted (please read, they affect B and C)

1. **Units:** minutes, km, kWh. Charging minutes = `60 × kWh / rate_kWh_per_hour`.
2. **Every vehicle starts full** at the depot, at time 0.
3. **Plan format:** `{"routes": [...], "unserved_customers": [...]}`. Only dispatched vehicles appear. Before simulation, `actual_* = planned_*` and `wait_time_minutes = 0`.
4. **Stations** appear in `stop_sequence` as their `station_id` (`"S_01"`). The distance/time matrices inside `Instance` also accept `station_id` as a key, so `objective.py` counts station legs correctly.
5. **Timing: "wait at the previous stop".** A vehicle absorbs any slack by leaving the previous stop later. So:
   - `planned_arrival_time` at a customer = service start (never before the window opens). This avoids `objective.py`'s early-arrival penalty.
   - At a station, `planned_arrival_time` = `planned_charge_start` = the booked charge start. Plans never contain deliberate queueing at a charger.
6. Charging stops carry one extra optional key: **`planned_charge_start`** (minutes).
7. Energy per leg: `distance_km × energy_consumption_per_km`.

---

## 6. Action items for other workstreams

| # | For | What's needed |
|---|---|---|
| 1 | **C (data)** | Define the **`thane_benchmark.json`** schema. We assumed `{"distance_matrix": {node: {node: km}}, "time_matrix": {node: {node: min}}}` keyed by string node ids. |
| 2 | **C (data)** | Add a **customers file** to the data contract. Temporary shape we use: `{"depot_node": id, "customers": [{"node_id", "time_window": [a, b], "service_time_min"}]}` |
| 3 | **C / docs owner** | Update `docs/data_contract.md`: the route-plan example isn't valid JSON (use the `{"routes", "unserved_customers"}` wrapper), and add units + `planned_charge_start`. |
| 4 | **Docs owner** | Update `docs/model_formulation.md`: start/end depot split, linearised charging time `h`, and **exact plug-unit capacity (D3)**. The current "Strategic Note" says capacity can be approximate, but we now enforce it exactly. |
| 5 | **B (simulator)** | Please note convention 5 above: planned arrival = charge start, so vehicles are planned to arrive exactly when their plug slot opens. |
| 6 | **Whoever owns `requirements.txt`** | Pin **`pulp>=4`**. The code uses the PuLP 4 API (`prob.add_variable`) and breaks on PuLP 2.x. |
| 7 | **Team decision** | `unserved_customers`: the contract says only the simulator fills it, but the heuristic also uses it when a customer can't be inserted. OK? |
| 8 | **Team decision** | The README says we minimise "travel time + wait + energy", but the locked formulation is **distance only**. The paper should say one thing. |

---

## 7. Known limitations / next steps

- **Random instances rarely need charging.** With realistic batteries and a distance-only objective, it's cheaper to spread customers across vehicles than to charge. So E1 mostly measures routing quality. If we want E1 to show charger contention, we should shrink batteries or reduce the fleet in `make_random_instance`. Team call.
- **Heuristic worst-case gap is 8%** on 2 of 13 instances. It could be improved further with more local-search moves, but it's already a solid result for the paper.
- **MILP scaling:** 10 customers / 4 vehicles solves in ≤ 9 s. Larger instances will get slow quickly; that's expected, and it's what the heuristic is for.
- **Not committed yet.** The code is on the local `main` branch as uncommitted changes.
