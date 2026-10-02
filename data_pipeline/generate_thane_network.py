"""
data_pipeline/generate_thane_network.py

One-time extraction of the Thane road network (OSMnx) -> data/thane_benchmark.json.

    python data_pipeline/generate_thane_network.py            # skips if the benchmark exists
    python data_pipeline/generate_thane_network.py --force    # rebuild (e.g. after adding stations)
    python data_pipeline/generate_thane_network.py --nearest 19.19 72.97   # nearest OSM node to a lat/lon

Output keys:
  nodes            {node_id: {"lat", "lon"}}               full drive graph (for drawing real roads)
  edges            {u: {v: {"distance_km", "time_min"}}}   full drive graph
  distance_matrix  {str(u): {str(v): km}}                   KEY NODES ONLY (see below)
  time_matrix      {str(u): {str(v): min}}                  KEY NODES ONLY, 30 km/h
  metadata         bbox, crs, date, counts, depot_node, customer_pool, station_nodes, speed

An all-pairs matrix over the whole graph (~10^4 nodes -> ~10^8 entries) would be gigabytes,
so shortest paths are computed only between key nodes: the depot, a seeded pool of candidate
customer nodes, and every station node_id in data/stations_config.json (if present).
Edge "length" from OSMnx is already geodesic metres, so no UTM projection is needed.
"""

import argparse
import json
import math
import os
import random
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "thane_benchmark.json")
STATIONS = os.path.join(ROOT, "data", "stations_config.json")

# Thane city: Thane West, Ghodbunder Rd, Kalwa, Mumbra, Diva. (The pack's 72.80-73.00 E box was
# mostly Mumbai's western suburbs + Sanjay Gandhi National Park, so it was moved east.)
NORTH, SOUTH, EAST, WEST = 19.300, 19.150, 73.080, 72.940
DEPOT_LATLON = (19.200, 72.970)  # Thane West (Teen Hath Naka / Wagle Estate); snapped to nearest node
# raw OSM graph cache (gitignored); bbox in the name so a boundary change never reuses a stale graph
GRAPH_CACHE = os.path.join(ROOT, "data", f"thane_drive_{NORTH}_{SOUTH}_{EAST}_{WEST}.graphml")
SPEED_KMH = 30.0
CUSTOMER_POOL_SIZE = 100  # candidate customer nodes; instances sample from this pool
SEED = 42


def load_graph():
    import osmnx as ox

    if os.path.exists(GRAPH_CACHE):
        print(f"Loading cached graph {os.path.relpath(GRAPH_CACHE, ROOT)} ...", flush=True)
        return ox.load_graphml(GRAPH_CACHE)
    print("Fetching Thane network from OpenStreetMap (can take several minutes) ...", flush=True)
    try:
        G = ox.graph_from_bbox((WEST, SOUTH, EAST, NORTH), network_type="drive", simplify=True)
    except Exception as exc:
        sys.exit(f"Could not fetch OSM data. Check your internet connection and the bounding box coordinates. ({exc})")
    # keep only the largest strongly connected component so every key pair has a route both ways
    G = ox.truncate.largest_component(G, strongly=True)
    if G.number_of_nodes() == 0:
        raise ValueError("Empty graph; check bbox.")
    ox.save_graphml(G, GRAPH_CACHE)
    return G


def nearest_node(G, lat, lon):
    """Nearest graph node by great-circle distance (stdlib only; avoids osmnx's scikit-learn dependency)."""
    def hav(n):
        d = G.nodes[n]
        p1, p2 = math.radians(lat), math.radians(d["y"])
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d["x"] - lon) / 2) ** 2
        return a
    return min(G.nodes, key=hav)


def station_nodes(G):
    if not os.path.exists(STATIONS) or os.path.getsize(STATIONS) == 0:
        return []
    with open(STATIONS) as f:
        stations = json.load(f)
    missing = [s["station_id"] for s in stations if s["node_id"] not in G]
    if missing:
        raise ValueError(f"Stations not on the drive graph: {missing}. Use --nearest LAT LON to find node ids.")
    return [s["node_id"] for s in stations]


def build(G):
    import networkx as nx

    print(f"done. {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.", flush=True)
    depot = nearest_node(G, *DEPOT_LATLON)
    stations = station_nodes(G)
    pool_candidates = sorted(n for n in G.nodes if n != depot and n not in stations)
    pool = sorted(random.Random(SEED).sample(pool_candidates, CUSTOMER_POOL_SIZE))
    key = [depot] + stations + pool

    print(f"Computing shortest paths between {len(key)} key nodes ...", flush=True)
    dist = {}
    for u in key:
        lengths = nx.single_source_dijkstra_path_length(G, u, weight="length")
        dist[str(u)] = {str(v): round(lengths[v] / 1000.0, 3) for v in key}
    km_per_min = SPEED_KMH / 60.0
    time = {u: {v: round(d / km_per_min, 3) for v, d in row.items()} for u, row in dist.items()}

    edges = {}
    for u, v, data in G.edges(data=True):
        km = data["length"] / 1000.0
        row = edges.setdefault(str(u), {})
        if str(v) not in row or km < row[str(v)]["distance_km"]:  # parallel edges: keep shortest
            row[str(v)] = {"distance_km": round(km, 4), "time_min": round(km / km_per_min, 4)}

    return {
        "nodes": {str(n): {"lat": d["y"], "lon": d["x"]} for n, d in G.nodes(data=True)},
        "edges": edges,
        "distance_matrix": dist,
        "time_matrix": time,
        "metadata": {
            "bbox": [NORTH, SOUTH, EAST, WEST],
            "crs": "EPSG:4326",
            "date_generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
            "network_type": "drive",
            "speed_kmh": SPEED_KMH,
            "depot_node": depot,
            "station_nodes": stations,
            "customer_pool": pool,
            "seed": SEED,
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--force", action="store_true", help="rebuild even if the benchmark exists")
    ap.add_argument("--nearest", nargs=2, type=float, metavar=("LAT", "LON"), help="print nearest OSM node id")
    args = ap.parse_args()

    if args.nearest:
        G = load_graph()
        n = nearest_node(G, *args.nearest)
        print(f"nearest node {n} at ({G.nodes[n]['y']:.6f}, {G.nodes[n]['x']:.6f})")
        return

    if os.path.exists(OUT) and os.path.getsize(OUT) > 0 and not args.force:
        print("Thane benchmark already exists. Skipping extraction. (Delete the file or use --force to re-run.)")
        return

    bench = build(load_graph())
    print(f"done. Saving to {os.path.relpath(OUT, ROOT)} ...", flush=True)
    with open(OUT, "w") as f:
        json.dump(bench, f, separators=(",", ":"))
    print(f"done. {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
