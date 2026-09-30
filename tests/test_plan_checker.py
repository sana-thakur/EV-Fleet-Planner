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
