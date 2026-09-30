"""
solver/objective.py

Shared evaluation function used to score EVERY route plan — MILP output,
heuristic output, and all naive baselines — identically. This is what
makes the final results table (E1 optimality gap, E3 Price of Ignoring
Reality) a valid, apples-to-apples comparison.

Call this function on a route plan AFTER it has been run through the
Reality Engine simulator, so `actual_arrival_times` and `wait_time_minutes`
reflect real queueing behavior rather than the solver's own assumptions.
It can also be called on a plan before simulation (where actual == planned
and wait_time == 0) to get the "on paper" score for comparison.
"""

from typing import List, Dict, Any, Optional


DEFAULT_WEIGHTS: Dict[str, float] = {
    "distance": 1.0,             # Base routing cost per unit distance
    "wait_time": 0.5,            # Penalty per minute idling at a charger
    "time_window_penalty": 1000.0,   # Penalty per minute late/early outside [a_i, b_i]
    "unserved_customer": 5000.0,     # Penalty per customer never reached
}


def calculate_route_cost(
    route_plan: List[Dict[str, Any]],
    distance_matrix: Dict[str, Dict[str, float]],
    customer_windows: Dict[str, List[float]],
    unserved_customers: Optional[List[str]] = None,
    cost_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Computes the standard objective/evaluation score for a completed route plan.

    Args:
        route_plan: List of per-vehicle route dicts, following the exact
            schema defined in docs/data_contract.md (Section 3).
        distance_matrix: Lookup table distance_matrix[node_i][node_j] -> distance.
        customer_windows: Lookup table customer_windows[node_id] -> [a_i, b_i],
            the permitted arrival time window for that customer node.
        unserved_customers: List of customer node IDs never reached by any
            vehicle in this plan. Pass the route-plan-level field from the
            data contract. Defaults to an empty list if not provided (i.e.,
            for a plan that hasn't been through the simulator yet).
        cost_weights: Optional override for the default penalty weights.

    Returns:
        A dictionary with the total objective score and its components,
        so callers can extract individual metrics for plots/tables.
    """
    if cost_weights is None:
        cost_weights = DEFAULT_WEIGHTS
    if unserved_customers is None:
        unserved_customers = []

    total_distance = 0.0
    total_wait_time = 0.0
    total_tw_violation_minutes = 0.0

    for vehicle_route in route_plan:
        stops = vehicle_route["stop_sequence"]
        arrival_times = vehicle_route.get(
            "actual_arrival_times", vehicle_route.get("planned_arrival_times")
        )

        # 1. Sum travel distance along this vehicle's stop sequence.
        for i in range(len(stops) - 1):
            node_a, node_b = str(stops[i]), str(stops[i + 1])
            total_distance += distance_matrix.get(node_a, {}).get(node_b, 0.0)

        # 2. Compare arrival times against each customer's time window.
        for node_id, arrival_time in zip(stops, arrival_times):
            window = customer_windows.get(str(node_id))
            if window is None:
                continue  # not a customer node (depot or station) — no window to check
            earliest, latest = window
            if arrival_time < earliest:
                total_tw_violation_minutes += (earliest - arrival_time)
            elif arrival_time > latest:
                total_tw_violation_minutes += (arrival_time - latest)

        # 3. Sum queue wait time recorded at each charging stop.
        for stop in vehicle_route.get("charging_stops", []):
            total_wait_time += stop.get("wait_time_minutes", 0.0)

    total_unserved = len(unserved_customers)

    objective_score = (
        (total_distance * cost_weights["distance"])
        + (total_wait_time * cost_weights["wait_time"])
        + (total_tw_violation_minutes * cost_weights["time_window_penalty"])
        + (total_unserved * cost_weights["unserved_customer"])
    )

    return {
        "total_score": objective_score,
        "distance_cost": total_distance,
        "wait_cost": total_wait_time * cost_weights["wait_time"],
        "time_window_penalty_cost": total_tw_violation_minutes * cost_weights["time_window_penalty"],
        "unserved_customer_penalty_cost": total_unserved * cost_weights["unserved_customer"],
        "raw_total_wait_minutes": total_wait_time,
        "raw_total_tw_violation_minutes": total_tw_violation_minutes,
        "raw_unserved_count": total_unserved,
    }
