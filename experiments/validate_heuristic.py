"""
experiments/validate_heuristic.py

E1: exact MILP vs Timeline-Aware heuristic on small instances.
Both plans are checked with plan_checker and scored with the shared
solver.objective.calculate_route_cost (on-paper score: actual == planned).

Run from the repo root:  python experiments/validate_heuristic.py
Writes results/e1_optimality_gap.csv
"""

import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from solver.heuristic import solve_heuristic  # noqa: E402
from solver.instance import make_random_instance, make_toy_instance  # noqa: E402
from solver.milp import solve_milp  # noqa: E402
from solver.objective import calculate_route_cost  # noqa: E402
from solver.plan_checker import check_plan  # noqa: E402

SIZES = [(5, 2), (6, 3), (8, 3), (10, 4)]
SEEDS = [1, 2, 3]
MILP_TIME_LIMIT_S = 300
OUT = os.path.join(ROOT, "results", "e1_optimality_gap.csv")
COLUMNS = ["instance", "n_customers", "n_vehicles", "seed", "milp_status", "milp_score", "milp_runtime_s",
           "milp_mip_gap", "heur_score", "heur_runtime_s", "gap_pct", "milp_feasible", "heur_feasible"]


def score(plan, inst):
    # dist_km already has string keys and station_id aliases, as objective.py expects.
    windows = {str(c): list(w) for c, w in inst.customer_window.items()}
    return calculate_route_cost(plan["routes"], inst.dist_km, windows, plan["unserved_customers"])["total_score"]


def feasible(name, label, plan, inst):
    res = check_plan(plan, inst)
    if not res["feasible"]:
        print(f"  [{name}] {label} plan violations:")
        for v in res["violations"]:
            print(f"    {v}")
    return res["feasible"]


def run(name, inst, n_c, n_v, seed):
    print(f"{name} ...", flush=True)
    m_plan, m_info = solve_milp(inst, time_limit_s=MILP_TIME_LIMIT_S)
    h_plan, h_info = solve_heuristic(inst)
    m_ok = m_info["status"] != "Infeasible" and feasible(name, "MILP", m_plan, inst)
    h_ok = feasible(name, "heuristic", h_plan, inst)
    m_score = score(m_plan, inst) if m_plan["routes"] else None
    h_score = score(h_plan, inst)
    gap = round(100 * (h_score - m_score) / m_score, 4) + 0.0 if m_info["status"] == "Optimal" and m_score else None
    return {
        "instance": name, "n_customers": n_c, "n_vehicles": n_v, "seed": seed,
        "milp_status": m_info["status"], "milp_score": m_score, "milp_runtime_s": round(m_info["runtime_s"], 3),
        "milp_mip_gap": m_info["mip_gap"], "heur_score": h_score, "heur_runtime_s": round(h_info["runtime_s"], 3),
        "gap_pct": gap, "milp_feasible": m_ok, "heur_feasible": h_ok,
    }


def fmt(v):
    if v is None:
        return "-"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def main():
    toy = make_toy_instance()
    rows = [run("toy", toy, len(toy.customers), len(toy.vehicles), "-")]
    for n_c, n_v in SIZES:
        for seed in SEEDS:
            rows.append(run(f"rand_c{n_c}_v{n_v}_s{seed}", make_random_instance(n_c, n_v, seed), n_c, n_v, seed))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    shown = ["instance", "milp_status", "milp_score", "heur_score", "gap_pct", "milp_runtime_s", "heur_runtime_s"]
    widths = [max(len(c), *(len(fmt(r[c])) for r in rows)) for c in shown]
    print("\n" + "  ".join(c.ljust(w) for c, w in zip(shown, widths)))
    for r in rows:
        print("  ".join(fmt(r[c]).ljust(w) for c, w in zip(shown, widths)))
    gaps = [r["gap_pct"] for r in rows if r["gap_pct"] is not None]
    if gaps:
        print(f"\nmean gap {sum(gaps) / len(gaps):.2f}%  max gap {max(gaps):.2f}%  "
              f"optimal-matched {sum(g <= 1e-6 for g in gaps)}/{len(gaps)}")
    print(f"infeasible plans: MILP {sum(not r['milp_feasible'] for r in rows)}, heuristic {sum(not r['heur_feasible'] for r in rows)}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
