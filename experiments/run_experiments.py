"""
experiments/run_experiments.py

Full Experiment Orchestrator for EVRPTW-HCC:
  - E1: MILP vs Heuristic Optimality Gap (writes results/e1_optimality_gap.csv)
  - E2: Heuristic Scalability Benchmark (writes results/e2_scalability.csv)
  - E3: "Price of Ignoring Reality" Empirical Comparison (writes results/e3_price_of_reality.csv)
  - Figure Generation: Publishes paper plots to results/figures/
"""

import csv
import os
import sys
import time
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from solver.instance import make_toy_instance, make_random_instance, load_instance
from solver.milp import solve_milp
from solver.heuristic import solve_heuristic
from solver.baselines import solve_b1_greedy, solve_b2_capacity_blind, solve_b3_type_blind
from solver.simulator import simulate_plan
from solver.objective import calculate_route_cost

RESULTS_DIR = os.path.join(ROOT, "results")
FIGURES_DIR = os.path.join(RESULTS_DIR, "figures")

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(FIGURES_DIR, exist_ok=True)


def run_e1_optimality_gap():
    print("--- Running E1: MILP vs Heuristic Optimality Gap ---")
    instances = [("toy", make_toy_instance())]
    for n in (5, 8, 10):
        for seed in (1, 2, 3, 4):
            instances.append((f"rand_n{n}_s{seed}", make_random_instance(n, n_vehicles=3, seed=seed)))

    rows = []
    for name, inst in instances:
        t0 = time.perf_counter()
        plan_m, info_m = solve_milp(inst, time_limit_s=60)
        t_milp = time.perf_counter() - t0

        t0 = time.perf_counter()
        plan_h, info_h = solve_heuristic(inst)
        t_heur = time.perf_counter() - t0

        cost_m = calculate_route_cost(plan_m["routes"], inst.dist_km,
                                       {str(c): list(w) for c, w in inst.customer_window.items()},
                                       plan_m.get("unserved_customers", []))["total_score"]
        cost_h = calculate_route_cost(plan_h["routes"], inst.dist_km,
                                       {str(c): list(w) for c, w in inst.customer_window.items()},
                                       plan_h.get("unserved_customers", []))["total_score"]

        gap = 100.0 * (cost_h - cost_m) / max(1e-6, cost_m) if cost_m > 0 else 0.0

        rows.append({
            "instance": name,
            "n_customers": len(inst.customers),
            "milp_cost": round(cost_m, 2),
            "milp_time_sec": round(t_milp, 3),
            "heur_cost": round(cost_h, 2),
            "heur_time_sec": round(t_heur, 3),
            "optimality_gap_pct": round(gap, 2),
        })
        print(f"  {name:15s} | MILP: {cost_m:6.1f} ({t_milp:4.2f}s) | Heur: {cost_h:6.1f} ({t_heur:4.3f}s) | Gap: {gap:4.2f}%")

    out_csv = os.path.join(RESULTS_DIR, "e1_optimality_gap.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved E1 results to {out_csv}\n")


def run_e2_scalability():
    print("--- Running E2: Heuristic Scalability ---")
    rows = []
    for n in (10, 25, 50, 100, 200):
        inst = make_random_instance(n, n_vehicles=max(2, n // 5), seed=42)
        t0 = time.perf_counter()
        plan, info = solve_heuristic(inst)
        t_sec = time.perf_counter() - t0

        rows.append({
            "n_customers": n,
            "n_vehicles": max(2, n // 5),
            "runtime_sec": round(t_sec, 4),
            "unserved": len(plan.get("unserved_customers", [])),
        })
        print(f"  N={n:3d} customers | Runtime: {t_sec:6.4f}s")

    out_csv = os.path.join(RESULTS_DIR, "e2_scalability.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved E2 results to {out_csv}\n")


def run_e3_price_of_reality():
    print("--- Running E3: Price of Ignoring Reality ---")
    # Test instances including high-charging contention setups
    instances = [
        ("toy", make_toy_instance()),
    ]
    for seed in (10, 20, 30):
        instances.append((f"bench_rand_s{seed}", make_random_instance(n_customers=10, n_vehicles=4, seed=seed)))

    solvers = [
        ("Proposed", solve_heuristic),
        ("B1 (Greedy FCFS)", solve_b1_greedy),
        ("B2 (Capacity-Blind)", solve_b2_capacity_blind),
        ("B3 (Type-Blind)", solve_b3_type_blind),
    ]

    rows = []
    for inst_name, inst in instances:
        windows = {str(c): list(w) for c, w in inst.customer_window.items()}

        for model_name, solver_fn in solvers:
            planned_plan, _ = solver_fn(inst)
            planned_cost = calculate_route_cost(planned_plan["routes"], inst.dist_km, windows,
                                                planned_plan.get("unserved_customers", []))["total_score"]

            sim_plan, sim_stats = simulate_plan(planned_plan, inst)
            sim_cost = calculate_route_cost(sim_plan["routes"], inst.dist_km, windows,
                                            sim_plan.get("unserved_customers", []))["total_score"]

            degradation_ratio = (sim_cost / max(1.0, planned_cost)) if planned_cost > 0 else 1.0

            rows.append({
                "instance": inst_name,
                "model": model_name,
                "planned_cost": round(planned_cost, 2),
                "simulated_cost": round(sim_cost, 2),
                "wait_time_min": sim_stats["total_wait_time_minutes"],
                "tw_violations": sim_stats["n_time_window_violations"],
                "total_late_min": sim_stats["total_late_minutes"],
                "stranded_vehicles": sim_stats["n_stranded_vehicles"],
                "degradation_ratio": round(degradation_ratio, 2),
            })
            print(f"  [{inst_name:14s}] {model_name:20s} | Planned: {planned_cost:6.1f} | Sim: {sim_cost:6.1f} | Wait: {sim_stats['total_wait_time_minutes']:5.1f}m | Stranded: {sim_stats['n_stranded_vehicles']}")

    out_csv = os.path.join(RESULTS_DIR, "e3_price_of_reality.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved E3 results to {out_csv}\n")

    generate_figures(rows)


def generate_figures(rows: list[dict]):
    print("--- Generating Publication Figures ---")
    df = pd.DataFrame(rows)

    # Figure 1: Wait Time Comparison across Models
    plt.figure(figsize=(7, 4.5))
    df_avg = df.groupby("model")["wait_time_min"].mean().reset_index()
    plt.bar(df_avg["model"], df_avg["wait_time_min"], color=["#16a34a", "#2563eb", "#ea580c", "#dc2626"])
    plt.title("Mean Charging Queue Wait Time (Simulated)")
    plt.ylabel("Wait Time (minutes)")
    plt.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    fig1_path = os.path.join(FIGURES_DIR, "fig1_wait_time_comparison.png")
    plt.savefig(fig1_path, dpi=300)
    plt.close()
    print(f"  Saved {fig1_path}")

    # Figure 2: Time Window Violations
    plt.figure(figsize=(7, 4.5))
    df_tw = df.groupby("model")["tw_violations"].sum().reset_index()
    plt.bar(df_tw["model"], df_tw["tw_violations"], color=["#16a34a", "#2563eb", "#ea580c", "#dc2626"])
    plt.title("Total Time-Window Violations under Reality Engine")
    plt.ylabel("Violation Count")
    plt.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    fig2_path = os.path.join(FIGURES_DIR, "fig2_time_window_violations.png")
    plt.savefig(fig2_path, dpi=300)
    plt.close()
    print(f"  Saved {fig2_path}")

    # Figure 3: Planned vs Simulated Degradation Ratio
    plt.figure(figsize=(7, 4.5))
    df_deg = df.groupby("model")["degradation_ratio"].mean().reset_index()
    plt.bar(df_deg["model"], df_deg["degradation_ratio"], color=["#16a34a", "#2563eb", "#ea580c", "#dc2626"])
    plt.axhline(1.0, color="black", linestyle="--", label="Ideal (No degradation)")
    plt.title("Price of Ignoring Reality (Simulated / Planned Cost Ratio)")
    plt.ylabel("Cost Ratio (Simulated / Planned)")
    plt.legend()
    plt.grid(axis="y", linestyle="--", alpha=0.7)
    plt.tight_layout()
    fig3_path = os.path.join(FIGURES_DIR, "fig3_price_of_reality_gap.png")
    plt.savefig(fig3_path, dpi=300)
    plt.close()
    print(f"  Saved {fig3_path}\n")


if __name__ == "__main__":
    run_e1_optimality_gap()
    run_e2_scalability()
    run_e3_price_of_reality()
