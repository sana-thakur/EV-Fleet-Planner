# EV Fleet Routing & Charging Scheduling (EVRPTW-HCC)

**Electric Vehicle Routing Problem with Time Windows and Heterogeneous, Compatibility-Constrained Charging**

[![Status](https://img.shields.io/badge/status-in--progress-333333?style=flat-square)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-333333?style=flat-square)]()
[![Conference](https://img.shields.io/badge/target-ICCI--2026-333333?style=flat-square)]()
---

## 📖 Overview

Urban logistics fleets are increasingly electric — but real-world electric vehicle (EV) fleets are rarely uniform. A typical fleet mixes e-2-wheelers, e-3-wheelers, and e-4-wheelers, each with different battery capacities and different physical charging plugs (e.g., LEV vs. CCS2). These vehicles must share a limited number of public charging stations, each with a limited number of plugs *per type*. An e-scooter cannot use a CCS2 fast charger, and a station with two LEV plugs can only serve two LEV-compatible vehicles at once, regardless of how many CCS2 plugs sit idle beside them.

Most published Electric Vehicle Routing Problem (EVRP) research either assumes a **uniform fleet** or **uncapacitated charging stations** — simplifications that make the math tractable but produce routing plans that look optimal on paper and then fail in real-world deployment, as vehicles queue for incompatible or fully occupied chargers.

This project formulates and solves **EVRPTW-HCC** — the Electric Vehicle Routing Problem with Time Windows and Heterogeneous, Compatibility-Constrained charging — a Mixed-Integer Linear Programming (MILP) model that:

- Routes a heterogeneous EV fleet to serve customers within time windows,
- Enforces **hard, type-specific charging plug capacity constraints**,
- Jointly minimizes total travel time, charging wait time, and energy cost.

We validate a fast heuristic against the exact solver on small instances, and — most importantly — use a discrete-event **"Reality Engine" simulator** to measure the **Price of Ignoring Reality**: how badly naive routing plans (that ignore charger capacity or plug type) degrade once replayed under real FIFO queueing and plug constraints, compared to our proposed model.

This repository contains the full mathematical formulation, solver and heuristic implementations, the simulator, experiment scripts, an interactive demo, and the accompanying SPRINGER conference manuscript.

---

## 🎯 Research Contribution

1. A MILP formulation of EVRPTW-HCC enforcing vehicle–charger compatibility and per-type charger capacity.
2. A **Timeline-Aware Greedy Insertion Heuristic** for instances too large for exact solving, validated against the MILP.
3. A real-world benchmark built from the **Thane/Mumbai road network** via OSMnx, rather than synthetic Euclidean points.
4. A discrete-event **Reality Engine simulator** that quantifies the gap between planned and actual fleet performance when charger capacity/type constraints are ignored — the paper's central empirical finding.

---

## 🚀 Key Features

- **Exact MILP Solver** — formal optimization model solved via `PuLP` + `HiGHS` for small benchmark instances (ground-truth baseline).
- **Timeline-Aware Heuristic** — fast, deterministic method for larger fleets that explicitly tracks per-slot charger occupancy.
- **Heterogeneous Fleet Modeling** — multiple EV types with distinct battery capacities and plug-compatibility matrices.
- **Type-Specific Charging Constraints** — enforces per-plug-type capacity limits (e.g., LEV vs. CCS2) at every station, for every time slot.
- **Naive Baselines for Comparison** — Greedy FCFS, Capacity-Blind, and Type-Blind planners, used to demonstrate the cost of ignoring real constraints.
- **Reality Engine Simulator** — discrete-event simulation with strict FIFO queues per (station, plug type), measuring actual arrival times, wait times, and time-window violations.
- **Real-World Network Benchmark** — road network, node coordinates, and distance/time matrices extracted from Thane/Mumbai via OSMnx.
- **Interactive Demo** — Streamlit app with a Folium route map, a Plotly Gantt chart of charger occupancy, and a "break a charger" control to trigger dynamic replanning.

---

## 🛠️ Technology Stack

| Component | Tool | Purpose |
|---|---|---|
| Language | Python 3.10+ | All modeling, solving, and analysis |
| Exact Solver | `PuLP` + `HiGHS` | Solves the MILP exactly on small instances |
| Heuristic | Custom (no external library) | Timeline-Aware Greedy Insertion for larger instances |
| Simulation | Custom (no external library) | Discrete-event Reality Engine (FIFO queues, plug-type checks) |
| Network Data | `osmnx` | Extracts real road network from OpenStreetMap |
| Data Handling | `pandas`, `numpy` | Distance matrices, results processing |
| Demo App | `streamlit` | Single-file interactive web app |
| Map Visualization | `folium` | Route rendering on real map |
| Interactive Charts | `plotly` | Gantt chart of charger occupancy |
| Static Figures | `matplotlib` | Paper-ready result plots |
| Manuscript | LaTeX (IEEE template) | Final conference paper |

No database is used — all data and results are stored as JSON/CSV files, which is sufficient for this project's scale and keeps setup minimal.

---

## 📋 Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Git

---

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sana-thakur/ev-fleet-planner.git
   cd ev-fleet-planner
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Data Setup

Before running any solver or experiment, the benchmark data must be generated once.

1. **Generate the road network benchmark:**
   ```bash
   python data_pipeline/generate_thane_network.py
   ```
   Pulls the Thane/Mumbai road network via OSMnx and saves node coordinates plus the distance/time matrix to `data/thane_benchmark.json`. This only needs to be run once — everything else reads from the saved file.

2. **Review/edit the fleet and station configuration:**
   - `data/fleet_config.json` — vehicle types, battery capacities, and the vehicle–plug compatibility matrix.
   - `data/stations_config.json` — station locations and plug counts per type.

   Edit these files directly to change fleet composition, fleet size, or station layout for different experiments.

---

## 🚀 Running Experiments

Run every solver (exact MILP, heuristic, all baselines) and the Reality Engine simulator across the configured instances:

```bash
python experiments/run_experiments.py
```

This produces:

- `results/e1_optimality_gap.csv` — exact MILP vs. heuristic solution quality on small instances.
- `results/e3_price_of_reality.csv` — planned vs. simulated performance (duration, queue wait, time-window violations, infeasible-route rate) for each baseline against the proposed model.
- Static figures in `results/figures/`, ready to drop into the paper.

---

## 🖥️ Running the Demo

```bash
streamlit run app.py
```

Launches an interactive local web app showing:
- A Folium map of the solved vehicle routes and charging stops.
- A Plotly Gantt chart of charger occupancy over time.
- A "break a charger" button that disables a station mid-plan and triggers dynamic replanning via the heuristic.

---

## 📁 Project Structure

```
ev-fleet-planner/
│
├── data/                            # Benchmark network, fleet, and station configs
│   ├── thane_benchmark.json         # OSMnx output (nodes, distances) — generated once
│   ├── fleet_config.json            # Vehicle types, battery capacities, compatibility matrix
│   └── stations_config.json         # Station locations and plug counts per type
│
├── data_pipeline/
│   └── generate_thane_network.py    # OSMnx extraction script (run once)
│
├── solver/
│   ├── __init__.py
│   ├── milp.py                      # Exact MILP formulation (PuLP + HiGHS)
│   ├── heuristic.py                 # Timeline-Aware Greedy Insertion (proposed method)
│   ├── baselines.py                 # B1 (FCFS), B2 (Capacity-blind), B3 (Type-blind)
│   ├── simulator.py                 # Reality Engine — FIFO queues + plug-type enforcement
│   └── objective.py                 # Shared cost function (travel + wait + energy)
│
├── experiments/
│   └── run_experiments.py           # Runs all models, produces results/*.csv
│
├── results/
│   ├── e1_optimality_gap.csv        # Exact vs. heuristic comparison
│   ├── e3_price_of_reality.csv      # Core empirical results table
│   └── figures/                     # Matplotlib figures for the paper
│
├── app.py                           # Streamlit demo (map + Gantt chart + replanning)
│
├── paper/
│   ├── manuscript.tex               # IEEE conference paper
│   ├── references.bib               # Bibliography
│   └── figures/                     # Final figures used in the manuscript
│
├── docs/
│   └── model_formulation.md         # Full MILP math — sets, variables, objective, constraints
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🧪 Experimental Design

**Models compared:**
- **Proposed Model** — EVRPTW-HCC, timeline-aware, respects charger type and capacity.
- **B1 (Greedy FCFS)** — routes to the nearest compatible charger, queues linearly.
- **B2 (Capacity-Blind)** — solves assuming unlimited plugs at every station.
- **B3 (Type-Blind)** — solves assuming all plugs at a station are interchangeable, ignoring type mismatch.

**Key experiment — "Price of Ignoring Reality":** Routes planned under B2 and B3 are passed through the Reality Engine simulator, which enforces true FIFO queues and plug-type restrictions. The gap between each baseline's *planned* duration and its *simulated* (actual) duration — along with resulting time-window violations and infeasible routes — is the paper's central evidence that ignoring these constraints produces plans that fail in deployment.
