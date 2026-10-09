import copy

import pytest

from solver.instance import make_toy_instance
from solver.plan_checker import check_plan

LEV_1KWH = 60.0 / 3.3  # minutes to charge 1 kWh on LEV


def _route(vid, seq, times, charges=()):
    return {"vehicle_id": vid, "stop_sequence": seq, "planned_arrival_times": times,
            "actual_arrival_times": list(times), "charging_stops": [
                {"station_id": "S_01", "plug_type_used": p, "planned_arrival_time": t, "actual_arrival_time": t,
                 "wait_time_minutes": 0.0, "energy_requested_kwh": kwh, "planned_charge_start": t}
                for p, t, kwh in charges]}


def base_plan():
    """The toy's intended optimum, written by hand."""
    return {"routes": [
        _route("V_2W_B", [0, "S_01", 1, 0], [0.0, 80.0, 160 + LEV_1KWH, 325 + LEV_1KWH], [("LEV", 80.0, 1.0)]),
        _route("V_2W_A", [0, 2, "S_01", 0], [0.0, 160.0, 245.0, 325 + LEV_1KWH], [("LEV", 245.0, 1.0)]),
        _route("V_4W", [0, 3, 4, 0], [0.0, 130.0, 155.0, 310.0]),
    ], "unserved_customers": []}


def _set(plan, vid, **kw):
    r = next(r for r in plan["routes"] if r["vehicle_id"] == vid)
    for key, val in kw.items():
        if key == "charge":
            r["charging_stops"][0].update(val)
        else:
            r[key] = val


def m_missing(p):
    _set(p, "V_4W", stop_sequence=[0, 3, 0], planned_arrival_times=[0.0, 130.0, 265.0])


def m_duplicate(p):
    _set(p, "V_4W", stop_sequence=[0, 3, 4, 4, 0], planned_arrival_times=[0.0, 130.0, 155.0, 160.0, 315.0])


def m_incompatible(p):
    _set(p, "V_2W_B", charge={"plug_type_used": "CCS2"})


def m_battery_negative(p):
    _set(p, "V_2W_A", charge={"energy_requested_kwh": 0.5})


def m_over_capacity(p):
    _set(p, "V_2W_A", charge={"energy_requested_kwh": 3.5},
         planned_arrival_times=[0.0, 160.0, 245.0, 245 + 3.5 * LEV_1KWH + 80])


def m_late(p):
    _set(p, "V_4W", planned_arrival_times=[0.0, 130.0, 176.0, 331.0])


def m_capacity(p):
    _set(p, "V_2W_A", stop_sequence=[0, "S_01", 2, 0], planned_arrival_times=[0.0, 80.0, 160 + LEV_1KWH, 325 + LEV_1KWH],
         charge={"planned_arrival_time": 80.0, "actual_arrival_time": 80.0, "planned_charge_start": 80.0})


def m_arrival(p):
    _set(p, "V_4W", planned_arrival_times=[0.0, 120.0, 155.0, 310.0])


def test_base_plan_feasible():
    res = check_plan(base_plan(), make_toy_instance())
    assert res["feasible"], res["violations"]
    assert res["summary"]["total_km"] == pytest.approx(470.0)
    assert res["summary"]["max_concurrent_charging"] == {"S_01/LEV": 1}


@pytest.mark.parametrize("mutate, expected", [
    (m_missing, "MISSING_CUSTOMER"),
    (m_duplicate, "DUPLICATE_CUSTOMER"),
    (m_incompatible, "INCOMPATIBLE_PLUG"),
    (m_battery_negative, "BATTERY_NEGATIVE"),
    (m_over_capacity, "BATTERY_OVER_CAPACITY"),
    (m_late, "TIME_WINDOW_LATE"),
    (m_capacity, "CAPACITY_EXCEEDED"),
    (m_arrival, "ARRIVAL_TIME_MISMATCH"),
])
def test_single_violation(mutate, expected):
    plan = base_plan()
    mutate(plan)
    res = check_plan(plan, make_toy_instance())
    assert [v["type"] for v in res["violations"]] == [expected], res["violations"]


def test_declared_unserved_is_not_missing():
    plan = base_plan()
    m_missing(plan)
    plan["unserved_customers"] = [4]
    assert check_plan(plan, make_toy_instance())["feasible"]


def test_waiting_at_previous_stop_is_allowed():
    plan = base_plan()
    _set(plan, "V_4W", planned_arrival_times=[0.0, 140.0, 165.0, 320.0])  # departs 10 min late
    assert check_plan(plan, make_toy_instance())["feasible"]


def test_early_arrival_is_waiting_not_a_violation():
    """E9: one time-window rule (lateness only) in objective.py and plan_checker."""
    from solver.objective import calculate_route_cost, late_minutes

    assert late_minutes(100.0, (120, 180)) == 0.0 and late_minutes(190.0, (120, 180)) == 10.0
    inst = make_toy_instance()
    plan = base_plan()
    _set(plan, "V_4W", planned_arrival_times=[0.0, 130.0, 155.0, 310.0])
    plan["routes"][2]["actual_arrival_times"] = [0.0, 100.0, 140.0, 310.0]  # early at both customers
    windows = {str(c): list(w) for c, w in inst.customer_window.items()}
    cost = calculate_route_cost(plan["routes"], inst.dist_km, windows)
    assert cost["raw_total_tw_violation_minutes"] == 0.0
    plan["routes"][2]["actual_arrival_times"] = [0.0, 150.0, 180.0, 330.0]  # 5 min late at each
    assert calculate_route_cost(plan["routes"], inst.dist_km, windows)["raw_total_tw_violation_minutes"] == 10.0


def test_leaving_before_depot_opens_is_flagged():
    """E10: depot opening time."""
    import dataclasses

    inst = dataclasses.replace(make_toy_instance(), depot_open_min=10.0)
    res = check_plan(base_plan(), inst)  # base plan leaves at 0.0
    # one "leaves depot before it opens" per route (later stops then cascade as impossible times)
    early = [v for v in res["violations"] if "before it opens" in v["detail"]]
    assert sorted(v["vehicle_id"] for v in early) == ["V_2W_A", "V_2W_B", "V_4W"] and not res["feasible"]
