# II. Related Work

## A. From the Green VRP to the EVRPTW

Routing vehicles that must refuel or recharge during a tour was first formalised by Erdoğan and Miller-Hooks as the Green Vehicle Routing Problem (G-VRP) [2]. In the G-VRP, an alternative-fuel fleet with limited driving range may detour to refuelling stations, and the problem is solved with a mixed-integer linear program and savings- and clustering-based heuristics. Schneider, Stenger and Goeke then specialised this setting to battery-electric vehicles and added customer time windows and vehicle load capacity, defining the Electric Vehicle Routing Problem with Time Windows and Recharging Stations (E-VRPTW) [3]. Their benchmark derives from Solomon's classical VRPTW instances [1], whose random, clustered and mixed customer layouts and tight versus wide time windows have made them the standard testbed for time-window routing since 1987. The E-VRPTW instances inherit this lineage, which explains why most subsequent EVRP studies are evaluated on Solomon-derived data. Exact methods soon followed: Desaulniers *et al.* [8] developed branch-price-and-cut algorithms for four recharging variants (single or multiple recharges per route, full or partial recharging) and solved instances with up to 100 customers and 21 stations to optimality.

## B. Modelling the Charging Process

A second stream refines how an individual vehicle charges. The original E-VRPTW assumed full recharges. Keskin and Çatay relaxed this to partial recharging [6] and showed with an adaptive large neighbourhood search that charging only what the remaining route needs shortens station dwell times and reduces cost. Montoya *et al.* [7] replaced the linear charging assumption with a piecewise-linear approximation of the real, concave charging curve. They found that ignoring the nonlinearity can produce plans that are either infeasible or unnecessarily expensive. Goeke and Schneider [5] went further on the consumption side, using an energy model that accounts for speed, road gradient and cargo load when routing a mixed fleet of electric and conventional vehicles. Charging cost has also been made time-dependent: Pelletier, Jabali and Laporte [16] schedule depot charging for electric freight fleets under time-of-use energy prices, battery degradation and grid power limits. All of these studies treat charging as a decision of a single vehicle. The charger itself is implicitly always available.

## C. Charging Infrastructure as a Shared, Capacitated Resource

Relaxing that availability assumption is the central thread for our work. It has been pursued in three ways.

*Queueing approximations.* The first approach represents congestion through waiting times rather than explicit schedules. Keskin, Laporte and Çatay [9] model time-dependent expected queueing times at stations with limited capacity, allowing late arrivals at a penalty. Keskin, Çatay and Laporte [10] extend this to stochastic waiting times, evaluated with a simulation-based heuristic. Kullman, Goodson and Mendoza [15] take a dynamic view: vehicles recharge at public stations whose queues are uncertain, and routing policies anticipate and react to observed queue states. On real industry instances, these policies were shown to outperform depot-only charging. These approaches capture congestion caused by the wider public, but the fleet's *own* vehicles do not reserve chargers against one another.

*Explicit charger scheduling.* The second approach schedules each charging operation against a finite number of chargers. Bruglieri, Mancini and Pisacane [12] introduced capacitated alternative-fuel stations into the G-VRP, with arc- and path-based MILP formulations and an exact cutting-plane method. Froger *et al.* [11] studied the E-VRP with nonlinear charging, multiple charging technologies and a limited number of chargers at privately managed stations. Their method alternates between route generation and a branch-and-cut assembler that enforces station capacity. Lam, Desaulniers and Stuckey [13] solved the E-VRPTW with piecewise-linear recharging and capacitated stations exactly by branch-and-cut-and-price.

*Shared infrastructure.* Koç *et al.* [14] consider charging stations jointly owned by several companies. In their model, routing decisions are coupled with the investment in shared chargers.

These works establish that charger capacity changes both the cost and the feasibility of electric routing plans. They share one modelling simplification, however: a charger is either free or occupied, and **any** vehicle may use **any** charger. Where several charging technologies are modelled [11], they differ in power, not in which vehicles can physically connect to them. To the best of our knowledge, no existing formulation combines vehicle–connector compatibility with capacity counted *per connector type*. In practice, an e-scooter cannot use a free CCS2 fast charger while it waits for the only LEV socket.

## D. Heterogeneous Fleets

Fleet heterogeneity has been studied mainly through vehicle cost, load capacity and battery size. Hiermann *et al.* [4] introduced the Electric Fleet Size and Mix VRP with Time Windows and Recharging Stations (E-FSMFTW), in which the fleet composition is itself a decision and vehicle types differ in acquisition cost, load capacity and battery capacity. Goeke and Schneider [5] mixed electric and combustion vehicles. In both cases the stations remain uncapacitated, and every electric vehicle can recharge at every station. Heterogeneity therefore affects range and cost, but never *where* a vehicle is allowed to charge. Urban fleets in India, which mix electric two-, three- and four-wheelers using the LEV, Type 2 and CCS2 connector standards, violate this assumption directly.

## E. Solution Methods and Evaluation Practice

Solution methods span exact branch-price-and-cut [8], [13], decomposition schemes [11], [15] and metaheuristics such as variable neighbourhood and tabu search [3] and adaptive large neighbourhood search [5], [6]. Evaluation practice is more uniform. Most studies report results on Solomon-derived synthetic instances [1], [3], [7], with Euclidean distances and stations placed by construction. Kullman *et al.* [15] are a notable exception, using real instances from industry. A second, subtler gap concerns how plans are assessed. Plans are typically scored under the same assumptions they were optimised for. Even the queue-aware methods [9], [10], [15] optimise against a congestion model. They do not measure how a plan built under *simpler* assumptions, for instance uncapacitated or type-agnostic chargers, degrades once executed under strict first-in-first-out queueing at real connectors.

## F. Research Gap and Positioning

The literature leaves three gaps that this paper addresses:

1. **Compatibility-constrained, per-type charger capacity.** Capacitated-station models [11]–[13] treat chargers as interchangeable, and heterogeneous-fleet models [4], [5] treat stations as uncapacitated. No formulation enforces both vehicle–plug compatibility and a capacity limit for each plug type at each station.
2. **Realistic network instances.** Evaluation relies predominantly on synthetic, Solomon-derived instances [1], [3]. Real road networks and real charging locations are rare.
3. **The cost of modelling simplifications.** The gap between a plan's *planned* performance and its *realised* performance under strict queueing has not been quantified for capacity-blind or type-blind planners.

We respond with four contributions:
1. A MILP formulation of EVRPTW-HCC that enforces vehicle–charger compatibility and exact per-plug-type capacity.
2. A Timeline-Aware Greedy Insertion heuristic that books plug-level time slots, validated against the exact MILP on small instances.
3. A benchmark built on the real Thane road network, extracted with OSMnx, with charging stations placed at real public charging sites.
4. A discrete-event "Reality Engine" simulator that replays plans under strict FIFO queues and plug-type rules, measuring the *Price of Ignoring Reality*: the degradation of capacity-blind and type-blind plans once they meet real charging infrastructure.

---

## References

[1] M. M. Solomon, "Algorithms for the vehicle routing and scheduling problems with time window constraints," *Operations Research*, vol. 35, no. 2, pp. 254–265, 1987.

[2] S. Erdoğan and E. Miller-Hooks, "A green vehicle routing problem," *Transportation Research Part E: Logistics and Transportation Review*, vol. 48, no. 1, pp. 100–114, 2012.

[3] M. Schneider, A. Stenger, and D. Goeke, "The electric vehicle-routing problem with time windows and recharging stations," *Transportation Science*, vol. 48, no. 4, pp. 500–520, 2014.

[4] G. Hiermann, J. Puchinger, S. Ropke, and R. F. Hartl, "The electric fleet size and mix vehicle routing problem with time windows and recharging stations," *European Journal of Operational Research*, vol. 252, no. 3, pp. 995–1018, 2016.

[5] D. Goeke and M. Schneider, "Routing a mixed fleet of electric and conventional vehicles," *European Journal of Operational Research*, vol. 245, no. 1, pp. 81–99, 2015.

[6] M. Keskin and B. Çatay, "Partial recharge strategies for the electric vehicle routing problem with time windows," *Transportation Research Part C: Emerging Technologies*, vol. 65, pp. 111–127, 2016.

[7] A. Montoya, C. Guéret, J. E. Mendoza, and J. G. Villegas, "The electric vehicle routing problem with nonlinear charging function," *Transportation Research Part B: Methodological*, vol. 103, pp. 87–110, 2017.

[8] G. Desaulniers, F. Errico, S. Irnich, and M. Schneider, "Exact algorithms for electric vehicle-routing problems with time windows," *Operations Research*, vol. 64, no. 6, pp. 1388–1405, 2016.

[9] M. Keskin, G. Laporte, and B. Çatay, "Electric vehicle routing problem with time-dependent waiting times at recharging stations," *Computers & Operations Research*, vol. 107, pp. 77–94, 2019.

[10] M. Keskin, B. Çatay, and G. Laporte, "A simulation-based heuristic for the electric vehicle routing problem with time windows and stochastic waiting times at recharging stations," *Computers & Operations Research*, vol. 125, art. 105060, 2021.

[11] A. Froger, O. Jabali, J. E. Mendoza, and G. Laporte, "The electric vehicle routing problem with capacitated charging stations," *Transportation Science*, vol. 56, no. 2, pp. 460–482, 2022.

[12] M. Bruglieri, S. Mancini, and O. Pisacane, "The green vehicle routing problem with capacitated alternative fuel stations," *Computers & Operations Research*, vol. 112, art. 104759, 2019.

[13] E. Lam, G. Desaulniers, and P. J. Stuckey, "Branch-and-cut-and-price for the electric vehicle routing problem with time windows, piecewise-linear recharging and capacitated recharging stations," *Computers & Operations Research*, vol. 145, art. 105870, 2022.

[14] Ç. Koç, O. Jabali, J. E. Mendoza, and G. Laporte, "The electric vehicle routing problem with shared charging stations," *International Transactions in Operational Research*, vol. 26, no. 4, pp. 1211–1243, 2019.

[15] N. D. Kullman, J. C. Goodson, and J. E. Mendoza, "Electric vehicle routing with public charging stations," *Transportation Science*, vol. 55, no. 3, pp. 637–659, 2021.

[16] S. Pelletier, O. Jabali, and G. Laporte, "Charge scheduling for electric freight vehicles," *Transportation Research Part B: Methodological*, vol. 115, pp. 246–269, 2018.
