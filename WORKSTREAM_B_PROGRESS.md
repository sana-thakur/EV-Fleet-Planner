# Workstream B: Reality Engine Simulator & Baselines, Progress Report

**Status:** All components built, tested (49 unit tests passing), and executed end-to-end in the experiment pipeline `experiments/run_experiments.py`.

---

## 1. What was built

| File | Description |
|---|---|
| `solver/simulator.py` | **Discrete-Event Reality Engine Simulator.** Replays route plans under physical plug constraints, enforcing per-plug-type FIFO queues, battery depletion tracking, and time-window delay propagation. |
| `solver/baselines.py` | **Naive Baseline Solvers.** Implements **B1** (Greedy FCFS), **B2** (Capacity-Blind EVRP), and **B3** (Type-Blind EVRP). |
| `experiments/run_experiments.py` | **Full Experiment Suite Orchestrator.** Executes E1 (optimality gap), E2 (scalability benchmark), and E3 ("Price of Ignoring Reality" empirical evaluation), saving results to CSV and generating paper figures. |
| `tests/test_simulator.py` | 5 unit tests for discrete-event simulation, FIFO queueing, plug type isolation, and battery stranding. |
| `tests/test_baselines.py` | 3 unit tests for baseline plan generation compliance. |
| `results/` | Updated CSV benchmark tables (`e1_optimality_gap.csv`, `e2_scalability.csv`, `e3_price_of_reality.csv`) and figures (`fig1_wait_time_comparison.png`, `fig2_time_window_violations.png`, `fig3_price_of_reality_gap.png`). |

---

## 2. Key Empirical Findings (E3: "Price of Ignoring Reality")

- **Toy Instance Bottleneck Test**:
  - **Proposed Model**: Planned 470.0 km $\rightarrow$ Simulated 470.0 km (Wait time: **0.0 min**).
  - **Baselines (B1 / B2 / B3)**: Planned 470.0 km $\rightarrow$ Simulated 479.5 km (Wait time: **19.1 min**).
- **Core Insight**: Solvers that ignore charger plug capacity or plug type generate plans that suffer immediate queueing bottlenecks and schedule degradation when replayed under real-world FIFO queueing.

---

## 3. How to Run

```bash
# Run full test suite (49 passing tests)
python -m pytest tests -q

# Run full experiment suite (E1, E2, E3 + Figure generation)
python experiments/run_experiments.py
```
