# Workflows

A **workflow** is a named alarm or automation behaviour. Each has an ID
(`WF-nnn`), a level, and a card that documents its inputs, process, outputs,
and overrides.

## Level convention

| Letter | Name | Meaning |
|---|---|---|
| **I** | INFORM | Display only. No action, no alarm. |
| **N** | NOTICE | Soft alert (logbook, low-priority notification). |
| **A** | ASSIST | Automation that helps the crew (switch a load, sound a horn). |
| **P** | PROTECT | Safety automation (engine kill, lockout). Requires manual clear. |

A workflow's level is fixed in its card. The engine enforces level
constraints: a PROTECT rule must use `clear: manual` and can only `set`
relays whose io_master class is PROTECT.

## Remote severity

When a rule fires, the engine sends a push notification at the rule's
severity:

| Severity | Pushover priority | Behaviour |
|---|---|---|
| EMERGENCY | emergency (repeat until acked) | phone alarm sound, retry every 30 s for 5 min |
| ALARM | high | alert sound, no repeat |
| NOTICE | normal | normal notification |
| LOG | lowest | silent; appears in notification history |

Recipients are configured in `engine.yml` (`call_home.recipients`). Each
recipient can filter by severity.

## Runs-on taxonomy

Each workflow declares where its logic lives:

| Tag | Where |
|---|---|
| HW | copper only — no software involved |
| PANEL | alarm panel firmware |
| RTI | Cerbo relay / generator controller |
| ENGINE | rules engine (this repo) |
| APP | vessel-ops or passage-planner |
| VRM | Victron cloud (GX relay rules) |

## Modes

The engine infers the boat's mode from sensor data:

| Mode | How detected |
|---|---|
| DOCK | shore power connected, SOG < threshold |
| ANCHOR | no shore power, SOG < threshold, no RPM |
| MOTOR | RPM > threshold |
| SAIL | SOG > threshold, no RPM |
| AWAY | crew not aboard (LAN presence empty) |

Rules can gate on mode: `when: {mode: {in: [MOTOR, SAIL]}}`.

Mode can be overridden manually via API.

## Status words

Each workflow carries a status:

| Status | Meaning |
|---|---|
| BUILT | wired and ring-out complete |
| SETTLED | tested and proven |
| KEEP | accepted and live |
| PARK | intentionally disabled |
| DROP | abandoned |
| HW-ONLY | copper path only, no software |

## Workflow card template

Every workflow is documented with this card:

```
WF-nnn: <Short title>
Level: I / N / A / P
Runs-on: ENGINE / HW / PANEL / ...
Status: BUILT / SETTLED / KEEP / ...

Input:    what sensors or signals arm or trigger it
Arm:      arming condition (when:) — the rule is inert otherwise
Process:  what the rule evaluates (if:) and what timers apply
Output:   what happens when it fires (do:)
Override: how the crew overrides it (copper switch, ack, API)
Fallback: what happens if the automation computer is dead
Open:     unresolved questions or known limitations
```

## Example workflow areas

| Range | Area | Examples |
|---|---|---|
| WF-001 – WF-010 | Core (lockouts, heartbeat) | WF-007 high-water lockout |
| WF-101 – WF-120 | Safety (bilge, fire, gas) | WF-101 high water, WF-102 fire |
| WF-201 – WF-220 | Propulsion (engine, raw water) | WF-201 raw-water flow |
| WF-301 – WF-320 | Energy (battery, charging, loads) | WF-305 low SoC |
| WF-401 – WF-420 | Water systems | WF-401 tank levels |
| WF-501 – WF-510 | Climate / comfort | WF-501 cabin temperature |
| WF-601 – WF-620 | Navigation (AIS, depth, weather) | WF-601 shallow water |

## Decision and finding register

The project tracks decisions (D-nnn) and findings (F-nnn) in a running
register:

- **D-nnn:** a decision that affects design, wiring, or rules. Recorded
  with rationale and date.
- **F-nnn:** a finding from testing, commissioning, or operation. Recorded
  with evidence.

Rules reference their D/F numbers in `note:` or `purpose:` fields, so
the rationale chain is traceable from the alarm back to the decision.
