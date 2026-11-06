# I/O Master Editor

Browser-based editor for `io_master.yml` — the file that defines every physical I/O channel on the boat (relays, digital inputs, analog inputs) and maps them to named functions.

## What it does

- Renders every I/O channel as a card with state, class, and module badges
- Groups channels by module (E1, S2, S3, S4, S5, etc.)
- Shows a device library with all physical slots — assigned and unassigned — so you can see what's wired and what's available
- Inline editing of state (`unverified` / `verified` / `live`), class (`INFORM` / `NOTICE` / `ASSIST` / `PROTECT`), function name, documentation text, and workflow references
- Auto-creates matching `io.*` signal entries in `signals.yml` when you assign a new DI/AI port

## How to run

No build step, no install. Serve the repo root with any HTTP server:

```bash
python -m http.server 8090
```

Then open `http://localhost:8090/tools/io-editor/`.

Also works from `file://` — open `index.html` directly and use the file picker to load your YAML.

## Dependencies

- [js-yaml 4.1.0](https://github.com/nodeca/js-yaml) loaded from CDN (no npm install needed)

## Data paths

When served from the repo root, the editor loads:

| File | Relative path |
|------|--------------|
| `io_master.yml` | `../../spec/04-Interfaces/io_master.yml` |
| `signals.yml` | `../../stacks/rules-engine/data/signals.yml` |

Paths are configurable in the toolbar if your layout differs.

## Deploying changes

The Save button POSTs edited YAML to the [deploy-api](../deploy-api/) service. The deploy-api must be running (default port 8767) and reachable from the browser. The editor discovers it at `{origin}/deploy/api/deploy/io_master`.

Without the deploy-api, use the Download button to save the edited YAML locally and copy it to the engine's data directory yourself.

## Device library

The editor includes a hardcoded device library describing the physical slot layout of each I/O module (relay count, DI count, AI count per module). Edit the `DEVICE_SLOTS` object in `index.html` to match your own hardware.
