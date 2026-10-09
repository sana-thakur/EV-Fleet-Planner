"""
experiments/solve_thane.py

Solves the Thane customer instances with MILP, Timeline Heuristic, and Reality Engine simulator,
writing pre-computed route plans to results/thane_*.json for the Streamlit demo app.

    python experiments/solve_thane.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from solver.heuristic import solve_heuristic
from solver.instance import load_instance
from solver.milp import solve_milp
from solver.plan_checker import check_plan
from solver.simulator import simulate_plan

RUNS = [
    (8, "heuristic"),
    (8, "milp"),
    (25, "heuristic"),
    (60, "heuristic"),
]
MILP_TIME_LIMIT_S = 300  # 30 s left non-optimal routes with pointless station detours


def main():
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    
    for n, solver in RUNS:
        customers_file = f"data/customers_thane_{n}.json"
        bench_path = os.path.join(ROOT, "data", "thane_benchmark.json")
        fleet_path = os.path.join(ROOT, "data", "fleet_config.json")
        stations_path = os.path.join(ROOT, "data", "stations_config.json")
        cust_path = os.path.join(ROOT, customers_file)

        inst = load_instance(bench_path, fleet_path, stations_path, cust_path)
        print(f"Solving Thane (N={n}) using {solver} ...", flush=True)

        if solver == "milp":
            plan, info = solve_milp(inst, time_limit_s=MILP_TIME_LIMIT_S)
        else:
            plan, info = solve_heuristic(inst)

        check = check_plan(plan, inst)

        # Save planned version
        plan["meta"] = {
            "customers_file": customers_file,
            "solver": solver,
            "simulated": False,
            "info": info,
            "checker_feasible": check["feasible"],
        }
        plan_path = os.path.join(ROOT, "results", f"thane_{n}_{solver}.json")
        with open(plan_path, "w") as f:
            json.dump(plan, f, indent=2, default=str)

        print(f"  -> {os.path.relpath(plan_path, ROOT)} | Feasible={check['feasible']} | Dist={check['summary']['total_km']:.1f} km")

        # Pass through simulator and save simulated version
        sim_plan, sim_stats = simulate_plan(plan, inst)
        sim_plan["meta"] = {
            "customers_file": customers_file,
            "solver": f"{solver} (simulated)",
            "simulated": True,
            "sim_stats": sim_stats,
            "checker_feasible": check["feasible"],
        }
        sim_path = os.path.join(ROOT, "results", f"thane_{n}_{solver}_simulated.json")
        with open(sim_path, "w") as f:
            json.dump(sim_plan, f, indent=2, default=str)

        print(f"  -> {os.path.relpath(sim_path, ROOT)} | Simulated Wait={sim_stats['total_wait_time_minutes']:.1f}m | Stranded={sim_stats['n_stranded_vehicles']}")

    print("\nThane benchmark route plans generated successfully!")


if __name__ == "__main__":
    main()
