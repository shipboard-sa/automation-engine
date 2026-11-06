# Deploy API

FastAPI service that receives edited YAML from the browser editors, validates it, writes it to the engine's data directory, commits to git, and hot-reloads the running engine.

## What it does

When you click Save in any of the browser editors, the deploy-api:

1. **Validates** the YAML (well-formed, expected structure)
2. **Writes** the file to the engine's data directory
3. **Cross-validates** by running `python -m engine check` (catches broken rule references, missing signals, invalid I/O mappings)
4. **Commits** the change to the deployed git checkout
5. **Hot-reloads** (for `rules.yml`) or advises restart (for `signals.yml` / `io_master.yml`)

## How to run

```bash
pip install fastapi uvicorn pyyaml pydantic
python serve.py
```

Default: `http://127.0.0.1:8767`

### Command-line options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8767 | Listen port |
| `--host` | 127.0.0.1 | Bind address |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOY_DATA_DIR` | `/srv/boat/rules-engine/data` | Engine's data mount (where YAML files live) |
| `DEPLOY_REPO_DIR` | `/srv/boat/repo` | Deployed git checkout (for commit after write) |
| `DEPLOY_ENGINE_URL` | `http://127.0.0.1:8200` | Engine API base URL (for hot-reload and check) |
| `DEPLOY_SECRETS` | `/srv/boat/secrets/engine.env` | File containing `ENGINE_API_TOKEN=...` |

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/deploy/{target}` | Deploy a file. `target` = `rules`, `signals`, or `io_master` |
| `GET` | `/api/deploy/health` | Health check |

### Deploy request body

```
Content-Type: text/plain

(raw YAML content)
```

### Deploy response

```json
{
  "status": "ok",
  "target": "rules",
  "commit": "a1b2c3d",
  "reload": "hot-reloaded"
}
```

## CORS

Allows all origins — this is a LAN-only tool, not exposed to the internet.

## Dependencies

- Python 3.10+
- `fastapi`, `uvicorn`, `pyyaml`, `pydantic`
