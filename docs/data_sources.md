# Data Sources: Thane Benchmark, Fleet and Stations

This page records where every number in `data/` comes from, and which values are **assumptions**. It covers `thane_benchmark.json`, `fleet_config.json` and `stations_config.json`. Check them with `python data/validate_configs.py`.

---

## 1. Road network: `data/thane_benchmark.json`

| Item | Value | Source / method |
|---|---|---|
| Network | OpenStreetMap drive network (all drivable roads), simplified, largest strongly connected component | OSMnx 2.1 `graph_from_bbox`, `network_type="drive"` |
| Area | 19.15–19.30°N, 72.94–73.08°E (Thane West, Ghodbunder Rd, Kalwa, Mumbra, Diva) | Team decision. The initial 72.80–73.00°E box was mostly Mumbai's western suburbs + Sanjay Gandhi National Park, so it was moved east. |
| Size | 12,882 nodes, 29,289 edges | OSM data © OpenStreetMap contributors, ODbL |
| Distances | Shortest road path (km), on the directed graph, so one-way streets make it asymmetric | NetworkX Dijkstra on OSM edge `length` (geodesic metres) |
| Travel time | distance at a uniform 30 km/h | Simplifying assumption: no congestion / time-of-day effects |
| Depot | Thane West (Teen Hath Naka / Wagle Estate area), OSM node 13418006658 at (19.2003, 72.9705) | Assumed central warehouse; snapped to the nearest road node |
| Customer pool | 100 road nodes sampled uniformly at random (seed 42) | Synthetic; instances draw customers from this pool |
| Matrix scope | Depot + stations + customer pool only (107 nodes) | A full 12,882² matrix would be ~166 M entries |

Sanity checks:
- Road distance ÷ straight-line distance: median 1.38, which is typical for urban networks.
- Median depot → customer distance: 7.4 km.
- Median one-way asymmetry: 2%.

## 2. Fleet: `data/fleet_config.json` (5 e-2W + 3 e-3W + 2 e-4W)

`energy_consumption_per_km = battery_kWh / range_km`. Where only a **certified** range is published, we apply a **0.8 real-world derating** (an assumption; certified Indian test cycles are optimistic for loaded urban delivery).

| Type | Model it represents | Battery (kWh) | Range used | kWh/km | Plugs | Sources |
|---|---|---|---|---|---|---|
| e-2W ×5 | TVS iQube 3.4 kWh | 3.4 | 100 km (manufacturer's stated real-world range, Eco mode) | 0.034 | LEV | [TVS iQube variants](https://tvsmotor.com/iqube/tvs-iqube-variant-details), [TVS iQube](https://tvsmotor.com/iqube) |
| e-3W ×3 | Mahindra Treo Zor (cargo) | 7.37 | 125 km certified × 0.8 = 100 km | 0.074 | LEV, Type2 | [Rushlane](https://www.rushlane.com/mahindra-treo-zor-electric-cargo-12381277.html), [EVreporter](https://evreporter.com/mahindra-electric-launches-treo-zor/) |
| e-4W ×2 | Tata Ace EV (cargo mini-truck) | 21.3 | 154 km certified × 0.8 = 123 km | 0.173 | CCS2, Type2 | [Rushlane](https://www.rushlane.com/new-tata-ace-electric-detailed-in-first-official-tvc-12435254.html), [91trucks](https://91trucks.com/trucks/tata/ace-ev), [TrucksBuses](https://www.trucksbuses.com/blog/tata-ace-ev-electric-tata-mini-truck-launched) |

Why these models:
- They are commercial / last-mile vehicles that are widely sold in India.
- The Ace EV supports CCS2 DC fast charging.

Assumptions:
- The plug compatibility per type follows the project contract (e-2W → LEV; e-3W → LEV or Type2; e-4W → CCS2 or Type2).
- In reality, the Treo Zor and the Ace EV's AC charging use a 15 A socket rather than a Type2 connector. The contract maps that to "LEV" / "Type2" as an abstraction.
- Nominal battery capacity is used; usable capacity is typically a few % lower.
- Vehicles within a type are identical.

## 3. Charging stations: `data/stations_config.json`

Locations of S_01–S_05 are **real public charging sites** listed by operators / aggregators. They were geocoded with OpenStreetMap Nominatim (locality level, ~100–500 m precision) and snapped to the nearest road node. S_06 is **synthetic**: there is no listed site there, and it was added for coverage of Mumbra/Diva east of the creek.

| station_id | Real site | Location used | Node | Sources |
|---|---|---|---|---|
| S_01_Panchpakhadi | ChargeZone, Modi House, Louis Wadi / Panch Pakhdi, Eastern Express Hwy, Thane West | Panchpakhadi (19.1954, 72.9647) | 2230881295 | [ChargeZone](https://ev-stations.chargezone.co.in/near-me/thane/panch-pakhdi/chargezone-charging-station-in-panch-pakhdi-thane--6kNTLZ/home) |
| S_02_Majiwada | HPCL – Lokhandwala Automobiles, Agra Road, Majiwada | Majiwada (19.2130, 72.9785) | 4367762038 | [91trucks Thane list](https://www.91trucks.com/electric/charging-stations/thane) |
| S_03_Manpada | Fortum EV Charger (OSM node 9215039103, `capacity=1`) | exact OSM point (19.2330, 72.9761) | 4213259528 | [OSM node 9215039103](https://www.openstreetmap.org/node/9215039103) |
| S_04_Kalwa | CABE Kalwa Naka, Budhani Nagar, Kalwa | Kalwa Naka (19.1963, 72.9874) | 2299204488 | [91trucks Thane list](https://www.91trucks.com/electric/charging-stations/thane) |
| S_05_Kasarvadavali | Powerbank – Thane G G, SH 42 next to Hypercity, Anand Nagar (Statiq listing, 1× CCS2) | Kasarvadavali (19.2754, 72.9689) | 2245095150 | [Statiq](https://statiq.in/Powerbank--Thane-G-G-Charging-Station-ev-charging-station-id-3123) |
| S_06_Mumbra_SYN | **Synthetic** | Mumbra (19.1899, 73.0231) | 10943525899 | coverage of the eastern part of the area |

**Plug counts are assumptions.** No public source we found publishes reliable per-connector counts for these sites:
- Open Charge Map's API now requires a key.
- Operator pages list at most 1–2 DC connectors, and some are marked faulted.
- OSM has only one tagged charger in the area.

We therefore use small, realistic counts (0–2 per type, 2–4 plugs per site). They were chosen so that:
- every plug type exists somewhere;
- the 8 LEV-capable vehicles share only **7 LEV plugs** across 5 sites, so LEV capacity can bind.

Where a listing names a connector, we kept it: S_03 has a single charger (OSM `capacity=1`), and S_05 has 1× CCS2. The LEV / Type2 counts at real sites are assumed.

| station_id | LEV | CCS2 | Type2 |
|---|---|---|---|
| S_01_Panchpakhadi | 1 | 2 | 1 |
| S_02_Majiwada | 1 | 1 | 0 |
| S_03_Manpada | 0 | 1 | 0 |
| S_04_Kalwa | 2 | 0 | 1 |
| S_05_Kasarvadavali | 1 | 1 | 0 |
| S_06_Mumbra_SYN | 2 | 1 | 1 |

**Charge rates** are uniform across stations: LEV 3.3 kW (Bharat AC-001), CCS2 30 kW, Type2 22 kW. These are the locked values from `docs/model_formulation.md`, with citations in `docs/data_contract.md`. Real CCS2 units in Thane are listed at 60–80 kW, so 30 kW is conservative.

Not used:
- GLIDA Hotel Raj Kiran (pin 421601 is Shahapur, outside the area; both CCS2 connectors listed as faulted).
- Sites outside the area: Mira Road, Kalyan, Talasari.

## 4. Simplifying assumptions (state these in the paper)

1. Uniform 30 km/h travel speed; no traffic or time-of-day variation.
2. Energy use is linear in distance (no load, gradient, HVAC or speed effects).
3. Uniform charge rate per plug type (no taper near full charge, no power sharing between plugs).
4. Station locations are accurate to the locality (~100–500 m); plug counts at real sites are assumed.
5. Every vehicle starts the day full at the depot.
