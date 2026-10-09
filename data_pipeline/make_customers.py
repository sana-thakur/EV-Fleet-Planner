"""
data_pipeline/make_customers.py

Writes Thane customer instances data/customers_thane_<n>.json, drawn from the benchmark's
seeded customer pool. Shape (temporary, until added to docs/data_contract.md):
    {"depot_node": id, "customers": [{"node_id", "time_window": [a, b], "service_time_min"}]}

Time is minutes from midnight. Windows follow the team decision: the 9am-5pm working day
(540-1020), with ~30% priority deliveries in a tighter 30-60 min window.

    python data_pipeline/make_customers.py
"""

import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = [8, 25, 60]  # 8: small enough for the MILP; 25: default daily load; 60: stresses charging
SEED = 7
PRIORITY_SHARE = 0.3
SERVICE_MIN = 5
DEPOT_OPEN_MIN = 480  # 08:00: vehicles leave the depot no earlier than this


def make(pool, depot, n, seed):
    rng = random.Random(seed)
    customers = []
    for node in sorted(rng.sample(pool, n)):
        if rng.random() < PRIORITY_SHARE:
            a = rng.randrange(540, 960, 10)
            window = [a, a + rng.choice([30, 60])]
        else:
            window = [540, 1020]
        customers.append({"node_id": node, "time_window": window, "service_time_min": SERVICE_MIN})
    return {"depot_node": depot, "depot_open_min": DEPOT_OPEN_MIN, "customers": customers}


def main():
    with open(os.path.join(ROOT, "data", "thane_benchmark.json")) as f:
        meta = json.load(f)["metadata"]
    for n in SIZES:
        path = os.path.join(ROOT, "data", f"customers_thane_{n}.json")
        with open(path, "w") as f:
            json.dump(make(meta["customer_pool"], meta["depot_node"], n, SEED + n), f, indent=1)
        print(f"wrote {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
