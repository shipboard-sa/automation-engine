# Signals Editor

Browser-based editor for `signals.yml` — the signal catalog that tells the engine where every data point comes from and how to interpret it.

## What it does

- Groups signals by prefix (`sk.*` from SignalK, `io.*` from I/O modules, `cerbo.*` from Victron, etc.)
- Type inference badges — identifies each signal as bool, real, string, or position
- Live value polling — connect to a running engine to see current values alongside the definitions
- New signal builder with prefix-specific defaults and required fields
- Validates signal definitions (path, source, type, stale timeout)

## How to run

No build step, no install. Serve the repo root with any HTTP server:

```bash
python -m http.server 8090
```

Then open `http://localhost:8090/tools/signals-editor/`.

Also works from `file://` — open `index.html` directly and use the file picker.

## Dependencies

- [js-yaml 4.1.0](https://github.com/nodeca/js-yaml) loaded from CDN (no npm install needed)

## Data paths

When served from the repo root, the editor loads:

| File | Relative path |
|------|--------------|
| `signals.yml` | `../../stacks/rules-engine/data/signals.yml` |

## Live engine connection

Enter your engine's URL in the toolbar (e.g., `http://192.168.50.113:8200`) to enable live value display. The editor polls `GET /signals` every 5 seconds and shows the current value next to each signal definition. This is optional — the editor works fully offline.

## Deploying changes

The Save button POSTs edited YAML to the [deploy-api](../deploy-api/) service (default port 8767). Signal changes require an engine restart (the deploy-api will advise this).

Without the deploy-api, use the Download button to save locally.

## Signal prefixes

| Prefix | Source | Examples |
|--------|--------|----------|
| `sk.*` | SignalK (NMEA 2000, instruments) | `sk.yanmar_rpm`, `sk.depth` |
| `io.*` | I/O modules (Waveshare relays/DI) | `io.bilge_high`, `io.anchor_wash` |
| `cerbo.*` | Victron Cerbo GX | `cerbo.battery_soc`, `cerbo.shore_connected` |
| `net.*` | Network infrastructure | `net.starlink_online`, `net.router_up` |
| `host.*` | Host system health | `host.cpu_temp`, `host.disk_free` |
