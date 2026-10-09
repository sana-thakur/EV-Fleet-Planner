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
import pandas as pd

from solver.instance import load_instance
from solver.objective import calculate_route_cost
from solver.plan_checker import check_plan
from solver.simulator import simulate_plan

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
def instance(customers_file, code_version):
    """code_version is part of the cache key: editing solver/instance.py invalidates cached Instances
    (otherwise a running app keeps objects built by the old class)."""
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
    """(vehicle, station, plug, start, end) for every charging stop. Simulated plans carry the simulator's
    actual_charge_start/end; planned ones use planned_charge_start + charging duration."""
    out = []
    for r in plan["routes"]:
        for cs in r.get("charging_stops", []):
            if cs.get("actual_charge_start") is not None and cs.get("actual_charge_end") is not None:
                start, end = cs["actual_charge_start"], cs["actual_charge_end"]
            elif plan.get("meta", {}).get("simulated"):
                continue  # simulated, but this charge never happened (vehicle stranded / plug rejected)
            else:
                start = cs.get("planned_charge_start", cs["planned_arrival_time"])
                end = start + inst.charge_minutes(cs["station_id"], cs["plug_type_used"], cs["energy_requested_kwh"])
            out.append((r["vehicle_id"], cs["station_id"], cs["plug_type_used"], start, end))
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
            "Stranded": r.get("stranding_reason") or "",
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

instances = ["thane_8", "thane_25", "thane_60"]
selected_instance = st.sidebar.selectbox("Instance", instances, index=instances.index("thane_60"))

algo_options = ["Heuristic", "B1 Greedy", "B2 Capacity-Blind", "B3 Type-Blind"]
if selected_instance == "thane_8":
    algo_options.append("MILP (Exact)")

selected_algo = st.sidebar.selectbox("Algorithm", algo_options, index=0)

algo_map = {
    "Heuristic": "heuristic",
    "B1 Greedy": "b1_greedy",
    "B2 Capacity-Blind": "b2_capacity_blind",
    "B3 Type-Blind": "b3_type_blind",
    "MILP (Exact)": "milp",
}

slug = algo_map[selected_algo]
sim_file = f"{selected_instance}_{slug}_simulated.json"
raw_file = f"{selected_instance}_{slug}.json"

if sim_file in plans:
    name = sim_file
elif raw_file in plans:
    name = raw_file
else:
    st.sidebar.error(f"Plan file not found: {sim_file} or {raw_file}")
    st.stop()

plan = plans[name]
inst = instance(plan["meta"]["customers_file"], os.path.getmtime(os.path.join(ROOT, "solver", "instance.py")))

# ---------------------------------------------------------------- optional: break a charger
def simulated(p, i, plan_key=None):
    """The plan as replayed by the Reality Engine.
    If already simulated, returned as is.
    If plan_key has a matching pre-computed *_simulated.json in plans, load that.
    Otherwise, simulate on the fly."""
    if p.get("meta", {}).get("simulated"):
        return p, p.get("meta", {}).get("sim_stats", {})
    if plan_key and not plan_key.endswith("_simulated.json"):
        sim_name = plan_key.replace(".json", "_simulated.json")
        if sim_name in plans:
            sim_p = plans[sim_name]
            return sim_p, sim_p.get("meta", {}).get("sim_stats", {})
    sim, stats = simulate_plan(p, i)
    sim["meta"] = {**p.get("meta", {}), "simulated": True, "sim_stats": stats}
    return sim, stats


uses = {}  # (station, plug) -> vehicles that charge there in the loaded plan
for r in plan["routes"]:
    for cs in r.get("charging_stops", []):
        uses.setdefault((cs["station_id"], cs["plug_type_used"]), []).append(r["vehicle_id"])

with st.sidebar.expander("Break a charger (re-plan)"):
    used_sids = {s for s, _ in uses}
    sid = st.selectbox("Station", [s["station_id"] for s in inst.stations],
                       format_func=lambda s: f"{s}  ⚡ used" if s in used_sids else s)
    plugs = {p: n for p, n in inst.station(sid)["plugs"].items() if n > 0}
    plug = st.selectbox("Plug type", list(plugs) or ["-"],
                        format_func=lambda p: f"{p} ×{plugs[p]}" + (f"  (used by {', '.join(uses[sid, p])})" if (sid, p) in uses else "  (unused)")
                        if p in plugs else p)
    new_n = st.number_input("New plug count", 0, max(plugs.get(plug, 1) - 1, 0), 0) if plug in plugs else 0
    if plug in plugs and (sid, plug) not in uses:
        st.caption("No vehicle in this plan charges here, so breaking it will not change anything. Pick a ⚡ station.")
    if st.button("Break charger and re-plan", disabled=plug not in plugs):
        from solver.heuristic import apply_overrides, solve_heuristic
        overrides = {sid: {plug: int(new_n)}}
        broken = apply_overrides(inst, overrides)
        with st.spinner("Re-planning with the heuristic and simulating both plans ..."):
            orig_broken, _ = simulated({**plan, "meta": {**plan.get("meta", {}), "simulated": False}}, broken)
            new_plan, _ = solve_heuristic(inst, station_overrides=overrides)
            new_plan["meta"] = {"solver": "heuristic re-plan", "simulated": False}
            replanned, _ = simulated(new_plan, broken)
        orig_broken["meta"]["solver"] = f"{plan.get('meta', {}).get('solver', '')} (not re-planned)"
        st.session_state["replan"] = (name, f"{sid} {plug}: {plugs[plug]} → {int(new_n)}", broken, orig_broken, replanned)

replan = st.session_state.get("replan")
compare = None
if replan and replan[0] == name:
    _, label, broken_inst, orig_broken, replanned = replan
    views = {"Loaded plan": (plan, inst),
             f"Charger broken, original plan ({label})": (orig_broken, broken_inst),
             f"Charger broken, re-planned ({label})": (replanned, broken_inst)}
    view = st.sidebar.radio("Show", list(views))
    compare = views
    plan, inst = views[view]

# ---------------------------------------------------------------- stats
windows = {str(c): list(w) for c, w in inst.customer_window.items()}


def summary(p, i, plan_key=None):
    sim, stats = simulated(p, i, plan_key)
    c = calculate_route_cost(sim["routes"], i.dist_km, windows, sim.get("unserved_customers", []))
    n = stats.get("n_charging_stops")
    if n is None:
        n = sum(1 for r in sim["routes"] for cs in r.get("charging_stops", []) if cs.get("actual_charge_start") is not None)
    return sim, c, n, stats


sim_plan, cost, n_charged, sim_stats = summary(plan, inst, name)
check = check_plan(plan, inst)
meta = plan.get("meta", {})

# Read wait time and charge count directly from sim_stats (from pre-computed or on-the-fly simulation)
total_wait = sim_stats.get("total_wait_time_minutes", cost.get("raw_total_wait_minutes", 0.0))
n_charges = sim_stats.get("n_charging_stops", n_charged)
unserved_count = sim_stats.get("unserved_customer_count", cost.get("raw_unserved_count", 0))
stranded_count = sim_stats.get("n_stranded_vehicles", 0)

st.sidebar.subheader("Plan summary (simulated)")
st.sidebar.metric("Total cost (objective.py)", f"{cost['total_score']:.1f}")
st.sidebar.metric("Distance", f"{cost['distance_cost']:.1f} km")

if n_charges > 0:
    avg_wait = total_wait / n_charges
    wait_display = f"{avg_wait:.1f} min"
else:
    wait_display = "0 charges / 0 min wait"

st.sidebar.metric("Avg queue wait / charge",
                  wait_display,
                  help="From the Reality Engine (FIFO queues per station and plug type). "
                       "0 min means no vehicle found its plug busy.")
st.sidebar.metric("Unserved customers", unserved_count)
st.sidebar.metric("Stranded vehicles", stranded_count)
st.sidebar.metric("Plan checker (as planned)", "feasible" if check["feasible"] else f"{len(check['violations'])} violations")
st.sidebar.caption(f"Solver: {meta.get('solver', '?')} · stats from the Reality Engine simulator")

# ---------------------------------------------------------------- main area
if compare:
    st.subheader("Break-a-charger comparison (all simulated)")
    table = []
    for label_, (p_, i_) in compare.items():
        _, c_, n_, s_ = summary(p_, i_)
        table.append({"Plan": label_, "Cost": round(c_["total_score"], 1), "km": round(c_["distance_cost"], 1),
                      "Unserved": s_.get("unserved_customer_count", c_["raw_unserved_count"]),
                      "Stranded": s_.get("n_stranded_vehicles", 0),
                      "Queue wait (min)": round(s_.get("total_wait_time_minutes", c_["raw_total_wait_minutes"]), 1)})
    df_compare = pd.DataFrame(table)
    st.dataframe(df_compare, width="stretch", hide_index=True)

plan = sim_plan
rows = vehicle_rows(plan, inst)
focus = st.selectbox("Zoom to vehicle", ["All vehicles"] + [r["Vehicle"] for r in rows])
st.caption(f"{len(inst.customers)} customers · {len(plan['routes'])} of {len(inst.vehicles)} vehicles dispatched · "
           f"{len(inst.stations)} stations")
draw_map(plan, inst, focus)

st.subheader("Vehicles")
df_rows = pd.DataFrame(rows)
st.dataframe(df_rows, width="stretch", hide_index=True)
st.subheader("Charger occupancy")
draw_gantt(plan, inst)
if not check["feasible"]:
    with st.expander("Plan checker violations"):
        v_df = pd.DataFrame(check["violations"])
        for col in ["node", "vehicle_id", "type", "detail"]:
            if col in v_df.columns:
                v_df[col] = v_df[col].astype(str)
        st.dataframe(v_df, width="stretch")
