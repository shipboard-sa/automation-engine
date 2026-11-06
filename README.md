# Automation Engine

A rules-as-data engine for marine vessel automation. Generic code evaluates
YAML rule definitions against live sensor data and drives relay outputs through
a single safety gate. Everything boat-specific lives in data files, not code.

This repo documents the **architecture and rule language** of the system.
The engine is a Python asyncio process that:

1. Reads sensors via adapters (Modbus RTU/TCP, SignalK, MQTT, RS-485)
2. Maintains a signal table (latest value + timestamp + staleness)
3. Evaluates YAML rules every 250 ms (or on digital-input change)
4. Routes action requests through a single arbiter (the safety gate)
5. Drives relay outputs, alarms, notifications, and logbook events

## Design principles

1. **The alarm panel is primary and standalone.** If the automation computer
   dies, the boat is back at passive-alarm behaviour and the panel says so.
2. **Automation is advisory; its failure is announced.** The crew always has
   the final say. No automated action proceeds without a copper override.
3. **Manual control stays in copper.** Every automated load has a physical
   switch that works with no software.
4. **Fail-safe direction is chosen per output.** Engine kills: NC contacts
   in series (dead computer = engine runs). Emergency loads: fed ahead of
   the breaker panel.
5. **I/O assignments are data.** One master table maps every Modbus channel
   to a function name. Code uses names, never addresses.
6. **Boring and debuggable.** Everything diagnosable from the nav station
   with a multimeter and no internet.

## Repo structure

```
spec/
  Architecture.md        Layered architecture, data flows, integration patterns
  Rules-Language.md      The rules-as-data format: signals, conditions, actions
  Engine-Design.md       Engine shape, evaluation loop, safety semantics, API
  Workflows.md           Workflow methodology: levels, conventions, card template
examples/
  engine.yml             Engine configuration (built-ins, heartbeat, mode)
  signals.yml            Signal catalog (sources, rates, max ages)
  rules.yml              Example rules (bilge, engine flow, low battery)
  io_master.yml          I/O module and channel definitions
tools/
  audit-viewer/          Browser-based audit log viewer (decisions, signal history, relay proof, timeline)
  deploy-api/            FastAPI deploy bridge — validates, writes, git-commits, and hot-reloads config
  io-editor/             I/O master table editor — full device library, state/class badges, inline editing
  rules-editor/          Rules editor — sentence builder, condition-type syntax coloring, rule wizard
  signals-editor/        Signal catalog editor — prefix grouping, type inference, live-value display
```

## The rules language (quick look)

```yaml
- id: WF-201
  when: {sk.engine_rpm: {above: 500, for: 30s}}
  if:   {io.raw_water_flow: {is: false, for: 15s}}
  do:
    alarm: {severity: EMERGENCY}
    message: "EMERGENCY Raw-water flow lost - check strainer / impeller"
    after_unacked: {in: 15s, do: {set: {io.engine_stop: on}}}
  clear: manual
```

Rules are YAML rows. The engine validates every row at load; a bad row
is rejected. Adding or tuning an alarm means editing a row and reloading,
with no code change.

See [spec/Rules-Language.md](spec/Rules-Language.md) for the full format.

## Adapting to your vessel

1. **Define your I/O** in `io_master.yml` — one row per Modbus channel
   with its function name, class (MONITOR / ASSIST / PROTECT), and
   fail-safe direction.
2. **Map your signals** in `signals.yml` — each signal names its source
   (SignalK path, Modbus function, MQTT topic) and its staleness threshold.
3. **Write your rules** in `rules.yml` — one row per alarm or automation
   behaviour, using the primitives documented in the rules language spec.
4. **Configure the engine** in `engine.yml` — heartbeat output, mode
   thresholds, notification recipients, alert forwarding.

## Tools

The `tools/` directory contains browser-based editors and viewers that
connect to the engine's deploy API or read data files directly.

- **Audit Viewer** — four-tab browser for the engine's audit trail: decisions
  (with input values), signal history (with inline SVG chart), relay proof
  (readback confirmation), and a unified timeline. Connects to a PostgreSQL
  reporting schema or loads local JSONL files for offline use.
- **Deploy API** — a thin FastAPI service that receives edited YAML from the
  browser editors, validates it, writes to the data directory and git-commits,
  then hot-reloads rules (or advises a restart for signals/io_master changes).
- **I/O Editor** — full device library view of io_master.yml. Shows every
  physical slot (assigned and unassigned) with state badges, class badges, and
  module grouping. Inline editing of state, class, function, wiring notes.
  Auto-creates `io.*` signals for newly assigned DI/AI ports.
- **Rules Editor** — syntax-aware viewer and editor for rules.yml. Renders
  each rule as a human-readable sentence with condition-type coloring
  (threshold, state, timer, rate, diff, latch). Includes a step-by-step
  rule wizard, inline threshold tuning, YAML preview with syntax highlighting,
  and deploy to the running engine.
- **Signals Editor** — viewer and editor for the signal catalog. Prefix
  grouping, type inference badges (bool/real/string/position), live-value
  polling from the engine API, and a builder for new signals with
  prefix-specific defaults.

All tools run as single-page HTML+JS apps (no build step). They load YAML
via js-yaml from CDN and talk to the deploy API for writes.

## NMEA 2000 switch bank integration

The engine exposes relay functions as an N2K switch bank (PGN 127501 status /
PGN 127502 command). This lets any NMEA 2000 MFD (Garmin, B&G, Raymarine)
display soft switches that the crew can tap to toggle automation-controlled
relays — anchor wash pump, deck lights, etc.

The crew toggle path (`POST /switch` or PGN 127502 command) goes through the
same arbiter safety gate as rules: circuit state, class permission, and
read-only module checks all apply. When the crew toggles a relay ON, the
arbiter records a `crew:<source>` ownership hold that outranks automation
rules. Toggling OFF releases the hold, returning the relay to automation
control.

## Related repos

| Repo | What |
|---|---|
| [guide](https://github.com/shipboard-sa/guide) | New owner's entry point — how to start |
| [wiring-io](https://github.com/shipboard-sa/wiring-io) | YAML wiring sheets + ladder diagram renderer |
| [vessel-ops](https://github.com/shipboard-sa/vessel-ops) | Maintenance, inventory, logbook (FastAPI + React) |
| [alarm-panel](https://github.com/shipboard-sa/alarm-panel) | Standalone alarm panel PCB (EasyEDA) |
| [anchor-alarm](https://github.com/shipboard-sa/anchor-alarm) | ESP32 anchor watch + automation health display |
| [passage-planner](https://github.com/shipboard-sa/passage-planner) | Weather routing and passage planning |
| [music-player](https://github.com/shipboard-sa/music-player) | Offline music player for Jellyfin |

## License

MIT — see [LICENSE](LICENSE).
