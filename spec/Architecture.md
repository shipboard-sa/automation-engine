# Architecture

## Data flow

```
Sensors -> SignalK (hub) -> rules engine + history writer -> PostgreSQL/TimescaleDB -> dashboards
```

Hardware protection (hard-wired kills, fire suppression, over-voltage cut) is
**computer-free** and sits below all software layers.

## Layers

```
 [ Humans: helm switches, alarm panel, horns ]              <- always wins
 [ Computer-free hardware: fire kill relays, OV cut, emergency stops ]
 ------------------------------------------------------------------ Automation below
 Ingest    SignalK <- N2K (CAN), AIS 0183, Cerbo MQTT, SSM RS-485 per-cell, genset CAN
 Logic     rules engine -> Modbus gateway -> RTU relay/input modules
 History   history writer <- SignalK at catalog rates -> PostgreSQL + TimescaleDB
 Present   Grafana (engineering), vessel-ops app (crew views), passage planner
 Egress    reverse proxy (LAN only), push notifications, Tailscale
 Ops       systemd timers (backup), Ansible (deploy + rollback from this repo)
```

## Principles

1. **The alarm panel is primary and standalone.** If the automation computer
   dies, the boat is at passive-alarm behaviour and the panel says so (a
   heartbeat output that drops when the computer stops).

2. **Automation is advisory; its failure is announced.** The crew always has
   the final say. No automated action proceeds without the crew's ability to
   override it in copper.

3. **Manual control stays in copper.** Every automated load has a manual
   override that works with no software: a physical switch that breaks or
   makes a circuit.

4. **Fail-safe direction is chosen per output:**
   - Engine kills: NC contacts in series. Dead computer = engine runs.
   - Charging permissives: NC contacts energise-to-disconnect. Dead relay =
     loads stay on.
   - Emergency loads (bilge pump): fed ahead of the breaker panel. Panel
     off = pump runs.

5. **I/O assignments are data.** One master table (`io_master.yml`) maps
   every Modbus channel to a function name. Code uses function names, never
   raw addresses. Move a channel in the table, not in the code.

6. **Boring and debuggable.** Everything is built so it can be diagnosed
   from the nav station with a multimeter and no internet connection.

## Integration patterns

Each process owns its own data; they meet through four patterns:

| Pattern | Used for | Example |
|---|---|---|
| **Subscribe to live state** | anything that must react now | rules engine subscribes to SignalK for alarm inputs |
| **Query history on demand** | a value "as of now" or a trend | vessel-ops stamps a logbook entry with position/wind/depth |
| **Push an event** | something happened that another system must record | rules engine POSTs "high water" to the vessel-ops logbook |
| **Lazy cached pull** | slow counters | vessel-ops refreshes engine hours only when its cache is stale |

**The history DB is history, not a message bus.** One writer feeds it; readers
query it. Nobody polls it to discover events.

## The Modbus bus

All I/O modules sit on one RS-485 Modbus RTU bus (9600 8N1, one master).
A Modbus TCP gateway bridges from the automation computer to the bus.

| Address range | Role | Example |
|---|---|---|
| 1 – 4 | DI + relay modules | alarm inputs, engine stop, horn |
| 5+ | Expansion (analog, additional DI/relay) | tank levels, extra relays |

## Container platform

Each service is a container sharing the host's Linux kernel:

- **One command for the boat:** top-level `compose.yml` includes each service.
- **Pinned images**, updated one at a time, previous kept for rollback.
- **One internal network**; only the reverse proxy is exposed.
- **Stable serial names** by udev rules.
- **Data** under `/srv/boat/<service>/`; config read-only from the repo.
- **Backup** = repo + data tree + saved images.

## Commissioning workflow

Every circuit follows the same path:

1. **Ring out** — verify continuity of every wire with a meter
2. **Wire from the sheet** — the rendered HTML page is the build document
3. **Prove it** — test the circuit for its designed function
4. **Owner's acceptance** — the owner says yes
5. **Go live** — update io_master state to `live`; the matching rule activates
6. **Update the register** — record the proof and status
