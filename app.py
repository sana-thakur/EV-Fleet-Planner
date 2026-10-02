"""
app.py: Streamlit demo for EVRPTW-HCC route plans on the Thane benchmark.

    streamlit run app.py

Visualises route plans saved in results/*.json (it does not plan anything itself, except the optional
"break a charger" re-plan, which calls Workstream A's heuristic with a plug override).
"""

import glob
import json
import os

import folium
import networkx as nx
import plotly.graph_objects as go
import streamlit as st

from solver.instance import load_instance
from solver.objective import calculate_route_cost
from solver.plan_checker import check_plan

ROOT = os.path.dirname(os.path.abspath(__file__))
BENCHMARK = os.path.join(ROOT, "data", "thane_benchmark.json")
THANE_CENTER = (19.2, 72.99)
COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#db2777", "#65a30d", "#7c3aed", "#ca8a04"]

st.set_page_config(page_title="EV Fleet Planner: Thane", layout="wide")


@st.cache_resource
def road_graph():
    with open(BENCHMARK) as f:
        bench = json.load(f)
    G = nx.DiGraph()
    for u, row in bench["edges"].items():
        for v, e in row.items():
            G.add_edge(u, v, km=e["distance_km"])
    return G, bench["nodes"]


@st.cache_resource
def instance(customers_file):
    return load_instance(BENCHMARK, os.path.join(ROOT, "data", "fleet_config.json"),
                         os.path.join(ROOT, "data", "stations_config.json"), os.path.join(ROOT, customers_file))


def node_of(inst, stop):
    return inst.station(stop)["node_id"] if isinstance(stop, str) else stop


def road_path(u, v):
    """Lat/lon points along the shortest road path (falls back to a straight line)."""
    G, nodes = road_graph()
    try:
        path = nx.shortest_path(G, str(u), str(v), weight="km")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        path = [str(u), str(v)]
    return [(nodes[n]["lat"], nodes[n]["lon"]) for n in path if n in nodes]


def charging_intervals(plan, inst):
    """(vehicle, station, plug, start, end) for every charging stop. Start = actual arrival + planned queue gap."""
    out = []
    for r in plan["routes"]:
        for cs in r.get("charging_stops", []):
            planned_gap = cs.get("planned_charge_start", cs["planned_arrival_time"]) - cs["planned_arrival_time"]
            start = cs.get("actual_arrival_time", cs["planned_arrival_time"]) + planned_gap + cs.get("wait_time_minutes", 0.0)
            dur = inst.charge_minutes(cs["station_id"], cs["plug_type_used"], cs["energy_requested_kwh"])
            out.append((r["vehicle_id"], cs["station_id"], cs["plug_type_used"], start, start + dur))
    return out


def vehicle_rows(plan, inst):
    rows = []
    for r in plan["routes"]:
        seq = r["stop_sequence"]
        times = r.get("actual_arrival_times", r["planned_arrival_times"])
        depart = times[1] - inst.time(seq[0], seq[1])  # vehicles leave just in time for their first stop
        rows.append({
            "Vehicle": r["vehicle_id"],
            "Type": inst.vehicle(r["vehicle_id"])["vehicle_type"],
            "Customers": sum(1 for s in seq if s in inst.customer_window),
            "Distance (km)": round(sum(inst.dist(u, v) for u, v in zip(seq, seq[1:])), 1),
            "Time (min)": round(times[-1] - depart, 1),
            "Charges": len(r.get("charging_stops", [])),
            "Queue wait (min)": round(sum(cs.get("wait_time_minutes", 0.0) for cs in r.get("charging_stops", [])), 1),
        })
    return rows


def hhmm(minutes):
    return f"{int(minutes // 60):02d}:{int(minutes % 60):02d}"


def draw_map(plan, inst, focus):
    m = folium.Map(location=THANE_CENTER, zoom_start=12)
    _, nodes = road_graph()
    ll = lambda n: (nodes[str(n)]["lat"], nodes[str(n)]["lon"])

    folium.Marker(ll(inst.depot_node), tooltip="Depot", icon=folium.Icon(color="blue", icon="home", prefix="fa")).add_to(m)
    for c in inst.customers:
        a, b = inst.customer_window[c]
        folium.CircleMarker(ll(c), radius=5, color="#15803d", fill=True, fill_opacity=0.9,
                            tooltip=f"Customer {c} · window {hhmm(a)}-{hhmm(b)}").add_to(m)
    for s in inst.stations:
        plugs = ", ".join(f"{p}×{n}" for p, n in s["plugs"].items() if n > 0) or "no plugs"
        folium.Marker(ll(s["node_id"]), tooltip=f"{s['station_id']} · {plugs}",
                      icon=folium.Icon(color="orange", icon="bolt", prefix="fa")).add_to(m)

    bounds = []
    for i, r in enumerate(plan["routes"]):
        stops = [node_of(inst, s) for s in r["stop_sequence"]]
        pts = [p for u, v in zip(stops, stops[1:]) for p in road_path(u, v)]
        faded = focus not in ("All vehicles", r["vehicle_id"])
        folium.PolyLine(pts, color=COLORS[i % len(COLORS)], weight=2 if faded else 4, opacity=0.25 if faded else 0.85,
                        tooltip=r["vehicle_id"]).add_to(m)
        if focus == r["vehicle_id"]:
            bounds = pts
    if bounds:
        m.fit_bounds(bounds)
    st.iframe(m.get_root().render(), height=560)  # folium HTML we generate ourselves


def draw_gantt(plan, inst):
    ivs = charging_intervals(plan, inst)
    if not ivs:
        st.info("No vehicle charges in this plan, so there is no charger occupancy to show.")
        return
    fig = go.Figure()
    for vid in sorted({v for v, *_ in ivs}):
        mine = [iv for iv in ivs if iv[0] == vid]
        fig.add_bar(name=vid, orientation="h", y=[f"{s} · {p}" for _, s, p, _, _ in mine],
                    base=[a for *_, a, _ in mine], x=[b - a for *_, a, b in mine],
                    hovertemplate=[f"{vid}<br>{hhmm(a)}-{hhmm(b)}<extra></extra>" for *_, a, b in mine])
    fig.update_layout(barmode="overlay", height=120 + 40 * len({(s, p) for _, s, p, _, _ in ivs}),
                      xaxis_title="Minutes from midnight", margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------- sidebar: choose a plan
plans = {}
for path in sorted(glob.glob(os.path.join(ROOT, "results", "*.json"))):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "routes" in data and "customers_file" in data.get("meta", {}):
        plans[os.path.basename(path)] = data

st.title("EV Fleet Planner: Thane")
if not plans:
    st.warning("No results found. Run experiments first: python experiments/run_experiments.py "
               "(or python experiments/solve_thane.py for the demo plans).")
    st.stop()

name = st.sidebar.selectbox("Route plan", list(plans))
plan = plans[name]
inst = instance(plan["meta"]["customers_file"])

# ---------------------------------------------------------------- optional: break a charger
with st.sidebar.expander("Break a charger (re-plan)"):
    sid = st.selectbox("Station", [s["station_id"] for s in inst.stations])
    plug = st.selectbox("Plug type", [p for p, n in inst.station(sid)["plugs"].items() if n > 0] or ["-"])
    if st.button("Set to 0 plugs and re-plan", disabled=plug == "-"):
        from solver.heuristic import apply_overrides, solve_heuristic
        overrides = {sid: {plug: 0}}
        with st.spinner("Re-planning with the heuristic ..."):
            new_plan, _ = solve_heuristic(inst, station_overrides=overrides)
        st.session_state["replan"] = (name, overrides, new_plan, apply_overrides(inst, overrides))

replan = st.session_state.get("replan")
if replan and replan[0] == name:
    _, overrides, new_plan, broken_inst = replan
    view = st.sidebar.radio("Show", ["Loaded plan", f"Re-planned ({', '.join(f'{s} {p}=0' for s, d in overrides.items() for p in d)})"])
    if view != "Loaded plan":
        plan, inst = new_plan, broken_inst

# ---------------------------------------------------------------- stats
windows = {str(c): list(w) for c, w in inst.customer_window.items()}
cost = calculate_route_cost(plan["routes"], inst.dist_km, windows, plan.get("unserved_customers", []))
check = check_plan(plan, inst)
n_charges = sum(len(r.get("charging_stops", [])) for r in plan["routes"])
meta = plan.get("meta", {})

st.sidebar.subheader("Plan summary")
st.sidebar.metric("Total cost (objective.py)", f"{cost['total_score']:.1f}")
st.sidebar.metric("Distance", f"{cost['distance_cost']:.1f} km")
st.sidebar.metric("Avg queue wait / charge", f"{cost['raw_total_wait_minutes'] / n_charges:.1f} min" if n_charges else "no charging")
st.sidebar.metric("Unserved customers", cost["raw_unserved_count"])
st.sidebar.metric("Plan checker", "feasible" if check["feasible"] else f"{len(check['violations'])} violations")
st.sidebar.caption(f"Solver: {meta.get('solver', 'heuristic re-plan')} · "
                   f"{'simulated' if meta.get('simulated') else 'planned (not yet simulated)'}")

# ---------------------------------------------------------------- main area
rows = vehicle_rows(plan, inst)
focus = st.selectbox("Zoom to vehicle", ["All vehicles"] + [r["Vehicle"] for r in rows])
st.caption(f"{len(inst.customers)} customers · {len(plan['routes'])} of {len(inst.vehicles)} vehicles dispatched · "
           f"{len(inst.stations)} stations")
draw_map(plan, inst, focus)

st.subheader("Vehicles")
st.dataframe(rows, width="stretch", hide_index=True)
st.subheader("Charger occupancy")
draw_gantt(plan, inst)
if not check["feasible"]:
    with st.expander("Plan checker violations"):
        st.dataframe(check["violations"], width="stretch")
