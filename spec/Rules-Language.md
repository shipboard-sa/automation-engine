# Rules as data

**The split:** the engine is generic code, written and tested once. The rules
are rows in `rules.yml` that the owner edits. Adding or tuning an alarm means
editing a row and reloading, with no code change. The engine validates every
row at load; a bad row is rejected and the last good set stays live.

## 1. Signals (inputs a rule may reference)

| Source | Written as | Example |
|---|---|---|
| IO master function (Modbus DI / relay state) | `io.<function>` | `io.raw_water_flow` |
| SignalK path | `sk.<name>` | `sk.engine_rpm` |
| Cerbo / Victron MQTT | `cerbo.<name>` | `cerbo.house_soc` |
| Battery management per-pack/cell | `ssm.<pack>.<field>` | `ssm.any.cell_max_v` |
| Engine state | `mode`, `ack.<rule>`, `active.<rule>` | `mode in [ANCHOR, AWAY]` |

**Sender pin** (`signals.yml` `device:`): a SignalK path that several devices
write can be bound to one sender. Other senders are ignored.

**Part key** (`part:`): read one key of an object value, e.g.
`sk.roll: {path: navigation.attitude, part: roll}`.

## 2. Primitives (what a condition can be)

| Primitive | Meaning |
|---|---|
| `is: true/false` | digital state |
| `above` / `below` + `clear_at` | threshold with hysteresis |
| `for: 15s` | condition must hold this long (debounce / sustain) |
| `rise: {by: 15, within: 5m}` | rate of rise |
| `fall: {by: 3, within: 1h}` | rate of fall (e.g. barometer) |
| `starts: {at_least: 6, within: 60s}` | off->on edges in a sliding window (pump cycling) |
| `stale: 60s` | no reading received for this long |
| `all:` / `any:` / `not:` | combine conditions |
| `latch: {set: <cond>, reset: <cond>}` | SR latch: true from set until reset |
| `when:` | arming condition — the rule is inert otherwise |

## 3. Actions

| Action | Meaning |
|---|---|
| `alarm: {severity: EMERGENCY/ALARM/NOTICE/LOG}` | raise into the annunciation built-in |
| `message:` | text template with optional `choose:` variants |
| `message` placeholders | `{signal}`, `{signal:.0f}`, `{eta:signal:target}` |
| `set: {io.<function>: on/off}` | drive a relay (class must allow it) |
| `after_unacked: {in: 15s, do: ...}` | ack-or-kill: do X unless acknowledged in time |
| `inhibits: [rule_or_function]` | while active, block those (lockout precedence) |
| `event:` | push to the vessel-ops logbook |
| `clear: auto / on_ack / manual` | self-clearing by default; PROTECT needs manual |
| `purpose: "<one line>"` | why this rule exists (documentation only) |

### Message variants with `choose:`

```yaml
message:
  choose:
    - if: {io.bilge_pump_running: {is: true}}
      text: "High water - pump running, being overwhelmed"
    - text: "High water - pump NOT running, check breaker"
```

Conditions in `choose:` are evaluated every tick, so `for:` / `starts:`
carry history when the alarm fires.

## 4. Engine built-ins (configured by data, not rule rows)

| Built-in | Configured by | Purpose |
|---|---|---|
| Annunciation | horn output, ack inputs | active minus acked; new key re-sounds |
| Call-home ladder | recipients, severity routing | push notifications by severity |
| Heartbeat | health checks, output, period | pulse only while healthy |
| Boat mode | inference thresholds, manual override | DOCK / ANCHOR / MOTOR / SAIL / AWAY |
| L3 per-cell watchdog | per-pack cutoffs, DVCC write | battery protection |
| Modbus bus owner | io_master.yml | the only writer of relays |
| Device alert forwarder | `forward:` entries | N2K notifications -> engine alarms |

### Alert forwarder (`forward:`)

SignalK `notifications.*` from devices become engine alarms without a rule row:

```yaml
forward:
  - {id: WF-204-OIL, match: notifications.propulsion.port.lowOilPressure,
     states: {alarm: EMERGENCY, emergency: EMERGENCY, warn: ALARM},
     when: {sk.engine_rpm: {above: 400, for: 10s}},
     message: "LOW OIL PRESSURE - stop the engine"}
```

First matching entry wins (order specific -> general). `mode` defaults to
`dry_run`. A forward never drives a relay.

## 5. Worked examples

```yaml
# Engine raw-water flow: ack-or-kill
- id: WF-201
  when: {sk.engine_rpm: {above: 500, for: 30s}}
  if:   {io.raw_water_flow: {is: false, for: 15s}}
  do:
    alarm: {severity: EMERGENCY}
    message: "EMERGENCY Raw-water flow lost - check strainer / impeller; engine stops in 15 s unless acked"
    after_unacked: {in: 15s, do: {set: {io.engine_stop: on}}}
  inhibited_by: [WF-007]
  clear: manual

# High water with a derived message
- id: WF-101
  if: {any: [{io.high_water_salon: {is: true}}, {io.high_water_bow: {is: true}}]}
  do:
    alarm: {severity: EMERGENCY}
    message:
      choose:
        - if: {io.bilge_pump_running: {is: true}}
          text: "EMERGENCY High water - pump running, being overwhelmed"
        - text: "EMERGENCY High water - pump NOT running, check pump / breaker"

# High-water lockout (precedence as data)
- id: WF-007
  if: {active: WF-101}
  do:
    inhibits: [WF-201, WF-202, io.ok_to_discharge]
    set: {io.water_heater_enable: off}
    alarm: {severity: NOTICE}
    message: "High water - switch off non-essential loads"

# Low battery with mode awareness
- id: WF-305
  if: {cerbo.house_soc: {below: 20, clear_at: 25, for: 5m}}
  do:
    alarm: {severity: NOTICE}
    message: "House bank {cerbo.house_soc}%"
  inhibited_by: [WF-007]
```

## 6. Dry-run and simulation

```yaml
- id: WF-201
  mode: dry_run     # logs "would set io.engine_stop on" but does not act
```

- Every rule starts `dry_run`; promoted to `live` only after testing.
- **Simulation:** override one signal's value via API, tagged SIMULATED,
  auto-expiring. A simulated signal can never drive a PROTECT relay live.
- The same simulation drives the test suite, so a rule is exercised
  identically off and on the boat.

## 7. Guardrails in the format

- A rule can only `set` relays whose io_master `class` is ASSIST or PROTECT;
  PROTECT sets need `clear: manual`.
- **Relay ownership:** when two active rules want different states on one
  relay, the higher rank wins. An equal or lower rank is refused and audited.
- Every rule carries a WF-id; unknown signals or functions fail validation.
- `io_master` circuit `state:` (unverified / verified / live) gates rule
  activation — a live rule naming a non-live circuit is rejected at load.

## 8. Allowed row keys

`id`, `mode`, `when`, `if`, `do`, `inhibited_by`, `clear`, `override`,
`note`, `purpose`, `record`.

`do:` keys: `alarm`, `message`, `set`, `after_unacked`, `inhibits`.

Any other key is rejected at load.
