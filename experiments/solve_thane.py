"""
experiments/solve_thane.py

Solves the Thane customer instances with Workstream A's solvers and writes the route plans to
results/thane_<n>_<solver>.json for the Streamlit demo. Plans are pre-simulation
(actual == planned) until Workstream B's simulator exists.

    python experiments/solve_thane.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from solver.heuristic import solve_heuristic  # noqa: E402
from solver.instance import load_instance  # noqa: E402
from solver.milp import solve_milp  # noqa: E402
from solver.plan_checker import check_plan  # noqa: E402

RUNS = [(8, "milp"), (8, "heuristic"), (25, "heuristic"), (60, "heuristic")]
MILP_TIME_LIMIT_S = 300


def main():
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    for n, solver in RUNS:
        customers_file = f"data/customers_thane_{n}.json"
        inst = load_instance(*(os.path.join(ROOT, p) for p in (
            "data/thane_benchmark.json", "data/fleet_config.json", "data/stations_config.json", customers_file)))
        print(f"thane_{n} {solver} ...", flush=True)
        plan, info = solve_milp(inst, time_limit_s=MILP_TIME_LIMIT_S) if solver == "milp" else solve_heuristic(inst)
        check = check_plan(plan, inst)
        # "meta" is extra to the contract's {"routes", "unserved_customers"}: it tells the demo which instance to load
        plan["meta"] = {"customers_file": customers_file, "solver": solver, "simulated": False,
                        "info": info, "checker_feasible": check["feasible"]}
        path = os.path.join(ROOT, "results", f"thane_{n}_{solver}.json")
        with open(path, "w") as f:
            json.dump(plan, f, indent=1, default=str)
        print(f"  -> {os.path.relpath(path, ROOT)}  feasible={check['feasible']}  "
              f"km={check['summary']['total_km']:.1f}  {info.get('status', '')}")


if __name__ == "__main__":
    main()
