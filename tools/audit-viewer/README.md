# Audit Log Viewer

API bridge and browser interface for the automation audit log — every decision the rules engine made, the input values that triggered it, relay readback proof, and alarm delivery records.

## What it does

- Timeline view of engine decisions with filtering by rule, function, outcome, and time range
- Signal history graphs — see what a signal was doing when a rule fired
- Relay proof table — readback confirmation that hardware followed software
- Decision drill-down — expand any decision to see every input value the engine read
- Works against a live PostgreSQL database or offline JSONL audit files

## How to run

### Against PostgreSQL (production)

```bash
pip install psycopg
python serve.py --dsn "postgresql://boat:boat@192.168.50.113:5432/boat"
```

### Against JSONL files (offline / development)

```bash
python serve.py --jsonl /path/to/audit.jsonl
```

### Demo mode (no data source)

```bash
python serve.py
```

Starts with empty results — useful for exploring the UI.

Default: `http://127.0.0.1:8766`

### Command-line options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8766 | Listen port |
| `--dsn` | (none) | PostgreSQL connection string |
| `--jsonl` | (none) | Path to JSONL audit file |

The DSN can also be set via `AUDIT_DSN` or `HISTORY_DSN` environment variables.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/decisions` | Paginated decision list with filters |
| `GET` | `/api/decision/{id}` | Single decision with full input snapshot |
| `GET` | `/api/signals` | Signal catalog as the engine sees it |
| `GET` | `/api/signal-history?signal=X` | Time series for one signal |
| `GET` | `/api/rules` | Rule definitions |
| `GET` | `/api/relay-proof` | Relay readback results |
| `GET` | `/api/timeline` | Unified timeline (decisions + inputs + relays + notifications) |
| `GET` | `/api/events` | Engine events (mode changes, health, config loads) |
| `GET` | `/api/all` | Full dump (development use) |

## Database views

In PostgreSQL mode, the viewer reads from the `reporting.*` schema views:

- `reporting.audit_decisions` — decisions joined with config version
- `reporting.audit_why` — decisions joined with their input snapshots
- `reporting.relay_proof` — relay readback joined with the triggering decision
- `reporting.timeline` — unified four-source timeline (inputs, decisions, relays, notifications)

These views are created by `audit_schema.sql`.

## Dependencies

- Python 3.10+
- `psycopg` (only for PostgreSQL mode; JSONL mode uses stdlib only)
