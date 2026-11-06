# Rules Editor

Browser-based editor for `rules.yml` — the alarm and automation rule definitions that the engine evaluates every cycle.

## What it does

- Renders each rule as a human-readable sentence with color-coded condition types (threshold, state, timer, rate-of-change, differential, latch)
- Inline threshold tuning — adjust trigger values without editing raw YAML
- YAML preview with syntax highlighting for any rule
- New rule builder with signal pick lists populated from `signals.yml`
- Step-by-step rule wizard for common patterns (high/low threshold, state change, rate alarm)
- Backup browser — view and restore previous versions
- Cross-references `signals.yml`, `engine.yml`, and `io_master.yml` for validation and pick lists

## How to run

No build step, no install. Serve the repo root with any HTTP server:

```bash
python -m http.server 8090
```

Then open `http://localhost:8090/tools/rules-editor/`.

Also works from `file://` — open `index.html` directly and use the file picker to load your YAML.

## Dependencies

- [js-yaml 4.1.0](https://github.com/nodeca/js-yaml) loaded from CDN (no npm install needed)

## Data paths

When served from the repo root, the editor loads from `../../stacks/rules-engine/data/`:

| File | Purpose |
|------|---------|
| `rules.yml` | The rule definitions (primary file) |
| `signals.yml` | Signal catalog — populates condition pick lists |
| `engine.yml` | Engine config — escalation tiers, built-in settings |
| `io_master.yml` | I/O map — validates relay targets |

## Deploying changes

The Save button POSTs edited YAML to the [deploy-api](../deploy-api/) service (default port 8767). The deploy-api validates the YAML, writes it, runs `engine check` for cross-validation, commits to git, and hot-reloads the running engine — no restart needed for rule changes.

Without the deploy-api, use the Download button to save locally.

## Understanding the rule display

Each rule card shows:

- **Condition** — the trigger expression, rendered as a sentence ("when yanmar_rpm > 3200 for 5s")
- **Actions** — what the rule does (sets relays, raises alarms, sends events)
- **Class badges** — PROTECT rules (red) drive safety-critical relays; ASSIST rules (blue) drive operational ones
- **Mode** — `live` (active on the boat), `dry_run` (logged but not executed), `disabled`
