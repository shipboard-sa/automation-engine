# Engine design

## 1. Shape

```
  adapters                signal table         evaluator          outputs
 ┌──────────┐           ┌────────────┐       ┌──────────┐      ┌────────────┐
 │ signalk   │──update──>│ name       │──────>│ rules[]  │─req─>│ arbiter    │──> relays
 │ modbus_bus│──update──>│ value      │       │ builtins │─req─>│ (one gate) │──> alarms
 │ cerbo_read│──update──>│ timestamp  │       └──────────┘      └────────────┘──> events
 │ ssm_poller│──update──>│ stale flag │                              │
 └──────────┘           └────────────┘                          ┌────────┐
                                                                │  API   │
                                                                └────────┘
```

## 2. Data files

| File | Purpose |
|---|---|
| `io_master.yml` | Module addresses, channel names, class, fail-safe, state |
| `signals.yml` | Signal catalog: source, rate, max age, unit |
| `rules.yml` | Alarm and automation rules |
| `engine.yml` | Built-in configuration: heartbeat, mode, notifications, forwarding |

The engine loads all four at startup and validates cross-references. A
bad file is rejected; the last good set stays live. Reload via API or
SIGHUP.

## 3. The loop

1. **Adapters update the signal table** as readings arrive.
2. **Every 250 ms** (or immediately on any DI change) the evaluator runs:
   - Each rule's `when` / `if` is resolved against the signal table.
   - Three-valued logic: true / false / UNKNOWN (signal stale or missing).
   - UNKNOWN in a condition keeps the rule from firing, never triggers it.
3. **State machine per rule:** IDLE → PENDING → ACTIVE → ACKED → CLEARED.
   - PENDING exists to enforce `for:` timers.
   - ACTIVE fires the `do:` block once, then sustains.
   - ACKED silences the horn; the rule stays until the condition clears.
4. **Action requests** (set relay, sound alarm, send notification) flow to
   the arbiter.
5. **The arbiter decides.** One gate, one set of ranking rules, one audit
   trail. See §4 below.

## 4. Safety semantics

| Property | How |
|---|---|
| **Three-valued logic** | Every signal is true, false, or UNKNOWN. UNKNOWN never triggers an action. |
| **One gate** | Every relay write passes through the arbiter. No shortcut path exists. |
| **Arbiter guardrails** | Only relays whose io_master class is ASSIST or PROTECT can be written. PROTECT needs `clear: manual`. |
| **Relay ranking** | When two rules disagree, the higher rank wins. Equal-or-lower is refused and audited. |
| **Safe start** | On boot, every relay is read (not written). The first write is the heartbeat. |
| **Safe stop** | On shutdown, the heartbeat stops. All other relays hold their last state (fail-safe direction chosen in io_master). |
| **Atomic reload** | New rules are validated in full before replacing the old set. Partial loads are impossible. |
| **Circuit gating** | A `state: live` rule naming a non-live circuit is rejected at load. |

## 5. API

### Read-only (LAN, no auth required)

| Endpoint | Returns |
|---|---|
| `GET /signals` | Current signal table (name, value, age, stale) |
| `GET /rules` | Rule states (IDLE / PENDING / ACTIVE / ACKED) |
| `GET /active` | Currently active alarms |
| `GET /io` | I/O master with live values |
| `GET /health` | Engine health checks |

### Authenticated

| Endpoint | Action |
|---|---|
| `POST /ack/{rule_id}` | Acknowledge an alarm |
| `POST /simulate` | Override a signal value (tagged, auto-expiring) |
| `POST /reload` | Hot-reload data files |
| `POST /mode` | Manual mode override |

## 6. Layout

```
stacks/rules-engine/
  engine/
    __init__.py
    __main__.py
    core.py            # main loop
    signals.py         # signal table
    conditions.py      # primitive evaluators (is, above, for, rise, ...)
    rules.py           # rule state machine
    arbiter.py         # the one gate
    config.py          # data file loader + validator
    api.py             # FastAPI read + write endpoints
    probe.py           # Modbus diagnostic tool
    adapters/
      signalk.py       # WebSocket subscriber
      modbus_bus.py    # Modbus RTU/TCP master (one thread)
      cerbo_read.py    # Victron MQTT subscriber
      ssm_poller.py    # battery per-cell RS-485
      ...
    builtins/
      heartbeat.py     # pulse while healthy
      mode.py          # boat mode inference
      annunciation.py  # horn + ack logic
      forward.py       # N2K alert forwarder
      ...
  data/
    io_master.yml
    signals.yml
    rules.yml
    engine.yml
  tests/
  compose.yml
  Dockerfile
  requirements.txt
```

## 7. Roles

The engine supports three roles:

| Role | Where | Does what |
|---|---|---|
| **active** | the boat's computer | reads sensors, evaluates rules, drives relays |
| **standby** | a second computer (optional) | reads sensors, evaluates rules, does NOT drive relays; promotes if active is lost |
| **bench** | a laptop anywhere | loads simulated signals for development and testing |

Promotion check: standby pings the active's `/health` endpoint. If three
consecutive checks fail, standby promotes and starts driving relays. The
old active, if it comes back, demotes itself.

## 8. Modbus bus adapter

- **One thread** owns the serial port. All reads and writes are serialised.
- **Re-assert:** relay outputs are re-written every 10 s, so a module
  power-cycle recovers in ≤ 10 s.
- **Silent module:** if a module stops responding, its signals go UNKNOWN
  and its relays are not written. The adapter raises an ALARM.
- **Adapter guardrails:** the adapter refuses to write a relay whose
  io_master `state` is not `live`.

## 9. Testing

- **Simulated signals + fake clock:** the test harness overrides the signal
  table and advances time, so a 30-second `for:` timer resolves in
  milliseconds.
- No mocks of the Modbus bus or SignalK; the adapters are thin enough to
  test through the signal table.
- The same simulation API available in bench mode drives the CI tests, so
  a rule is exercised identically on and off the boat.

## 10. Probe tool

A CLI tool for hands-on Modbus diagnostics:

```
probe scan              # discover modules on the bus
probe watch S4          # live-read all channels of module S4
probe pulse S3-R1 2s    # energise relay S3-R1 for 2 seconds
```

Probe bypasses the engine and talks to the bus directly. It refuses to
write a PROTECT relay unless `--force` is given.
