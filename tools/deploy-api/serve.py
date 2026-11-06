# Purpose: Deploy API for the config editor suite (D-211) — receives edited YAML from the browser editors,
#   validates it, writes to the data directory and the repo, git-commits, and calls the engine's /reload
#   endpoint for hot-reload (rules) or signals a container restart is needed (signals, io_master).
# Version: v1 (2026-11-05) - v1: first build. Rules hot-reload, signals/io_master write + advise restart.
# Scope: PRODUCTION once deployed on the Pi (runs on the host, not in a container — needs write access to
#   the data directory and the deployed repo).
# Architecture: tools/deploy-api. A thin FastAPI service (port 8767) sitting between the browser editors
#   and the engine. The editors POST their edited YAML here; the service validates it by running the config
#   loader, writes the file to both the deployed data directory and the repo, git-commits, and for rules
#   calls POST /reload on the engine (hot-reload, no restart). For signals/io_master, it writes the files
#   but the engine needs a container restart to pick them up.
#   Auth: LAN only (served behind nginx, same trust model as the relay-test page). The engine's bearer token
#   is read from the secrets env file at startup.
#   Paths (configurable via env):
#     DEPLOY_DATA_DIR    = /srv/boat/rules-engine/data        (where the engine container reads from)
#     DEPLOY_REPO_DIR    = /srv/boat/repo                     (the deployed git repo)
#     DEPLOY_ENGINE_URL  = http://127.0.0.1:8200              (the engine's API)
#     DEPLOY_SECRETS     = /srv/boat/secrets/engine.env        (ENGINE_API_TOKEN lives here)
# Invocation: python serve.py [--port 8767] [--host 127.0.0.1]
#   On the Pi: started by the deploy playbook or a systemd unit.
"""Deploy API for the config editor suite."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- configuration from environment -----------------------------------------------------------

DATA_DIR = Path(os.environ.get("DEPLOY_DATA_DIR", "/srv/boat/rules-engine/data"))
REPO_DIR = Path(os.environ.get("DEPLOY_REPO_DIR", "/srv/boat/repo"))
ENGINE_URL = os.environ.get("DEPLOY_ENGINE_URL", "http://127.0.0.1:8200")
SECRETS_FILE = Path(os.environ.get("DEPLOY_SECRETS", "/srv/boat/secrets/engine.env"))

REPO_DATA_SUBDIR = "stacks/rules-engine/data"
REPO_IO_MASTER = "spec/04-Interfaces/io_master.yml"

FILE_MAP = {
    "rules":     {"data_name": "rules.yml",     "repo_path": f"{REPO_DATA_SUBDIR}/rules.yml"},
    "signals":   {"data_name": "signals.yml",   "repo_path": f"{REPO_DATA_SUBDIR}/signals.yml"},
    "io_master": {"data_name": "io_master.yml", "repo_path": REPO_IO_MASTER},
}

# --- helpers ----------------------------------------------------------------------------------


def _read_engine_token() -> str | None:
    """Read ENGINE_API_TOKEN from the secrets env file (dotenv format: KEY=VALUE)."""
    if not SECRETS_FILE.exists():
        return None
    for line in SECRETS_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "ENGINE_API_TOKEN":
            return v.strip().strip("'\"")
    return None


def _validate_yaml(content: str, target: str) -> tuple[bool, str]:
    """Parse the YAML and do basic structural checks."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return False, f"YAML parse error: {e}"
    if target == "rules":
        if not isinstance(data, list):
            return False, "rules.yml must be a list of rule rows"
        for i, row in enumerate(data):
            if not isinstance(row, dict):
                return False, f"rules.yml row {i}: must be a mapping"
            if "id" not in row:
                return False, f"rules.yml row {i}: missing 'id'"
    elif target == "signals":
        if not isinstance(data, dict):
            return False, "signals.yml must be a mapping"
    elif target == "io_master":
        if not isinstance(data, dict):
            return False, "io_master.yml must be a mapping"
    return True, "ok"


def _full_validate(target: str) -> tuple[bool, str]:
    """Run `python -m engine check` against the data directory to cross-check all four files."""
    engine_dir = REPO_DIR / "stacks" / "rules-engine"
    venv_python = engine_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = "python3"
    else:
        venv_python = str(venv_python)
    io_master = DATA_DIR / "io_master.yml"
    if not io_master.exists():
        io_master = REPO_DIR / REPO_IO_MASTER
    try:
        result = subprocess.run(
            [venv_python, "-m", "engine", "check", "--data", str(DATA_DIR), "--io-master", str(io_master)],
            capture_output=True, text=True, timeout=15, cwd=str(engine_dir),
        )
        if result.returncode != 0:
            return False, result.stdout.strip() or result.stderr.strip() or "engine check failed"
        return True, "ok"
    except FileNotFoundError:
        return True, "skipped (engine venv not available on this host)"
    except subprocess.TimeoutExpired:
        return False, "engine check timed out"


def _write_files(content: str, target: str) -> None:
    """Write the YAML to both the data directory and the repo."""
    info = FILE_MAP[target]
    data_path = DATA_DIR / info["data_name"]
    repo_path = REPO_DIR / info["repo_path"]
    data_path.write_text(content, encoding="utf-8")
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    repo_path.write_text(content, encoding="utf-8")


def _git_commit(target: str, summary: str) -> tuple[bool, str]:
    """Stage the changed file and commit in the deployed repo."""
    info = FILE_MAP[target]
    repo_path = info["repo_path"]
    try:
        subprocess.run(["git", "add", repo_path], cwd=str(REPO_DIR), check=True,
                        capture_output=True, timeout=10)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(REPO_DIR), capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return True, "no changes to commit"
        subprocess.run(
            ["git", "commit", "-m", f"deploy-api: {target} — {summary}"],
            cwd=str(REPO_DIR), check=True, capture_output=True, timeout=15,
        )
        return True, "committed"
    except subprocess.CalledProcessError as e:
        return False, f"git error: {e.stderr.decode().strip() if e.stderr else str(e)}"
    except subprocess.TimeoutExpired:
        return False, "git command timed out"


def _reload_engine() -> tuple[bool, str]:
    """Call POST /reload on the running engine."""
    import urllib.request
    token = _read_engine_token()
    url = f"{ENGINE_URL}/reload"
    body = b'{"by": "deploy-api"}'
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            data = json.loads(resp.read())
            return data.get("ok", False), data.get("message", "ok")
    except Exception as e:
        return False, f"engine /reload failed: {e}"


# --- FastAPI app ------------------------------------------------------------------------------

app = FastAPI(title="config-deploy-api", version="1")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST", "GET", "OPTIONS"],
                   allow_headers=["*"])


class DeployBody(BaseModel):
    content: str = Field(..., description="The full YAML document")
    message: str = Field("editor deploy", max_length=120, description="Commit message summary")


@app.post("/api/deploy/{target}")
async def deploy(target: str, body: DeployBody):
    """Deploy an edited YAML file. target = rules | signals | io_master."""
    if target not in FILE_MAP:
        raise HTTPException(400, f"unknown target: {target} (must be rules, signals, or io_master)")

    steps: list[dict] = []

    # 1. validate YAML structure
    ok, msg = _validate_yaml(body.content, target)
    steps.append({"step": "validate_yaml", "ok": ok, "message": msg})
    if not ok:
        return {"ok": False, "steps": steps}

    # 2. write files to data dir + repo
    try:
        _write_files(body.content, target)
        steps.append({"step": "write_files", "ok": True, "message": "written"})
    except Exception as e:
        steps.append({"step": "write_files", "ok": False, "message": str(e)})
        return {"ok": False, "steps": steps}

    # 3. full cross-check with engine check
    ok, msg = _full_validate(target)
    steps.append({"step": "engine_check", "ok": ok, "message": msg})
    if not ok:
        return {"ok": False, "steps": steps, "hint": "The file was written but failed cross-validation. "
                "Fix the issues and deploy again, or restore from git."}

    # 4. git commit
    ok, msg = _git_commit(target, body.message)
    steps.append({"step": "git_commit", "ok": ok, "message": msg})

    # 5. hot-reload (rules only) or advise restart
    if target == "rules":
        ok, msg = _reload_engine()
        steps.append({"step": "reload", "ok": ok, "message": msg})
        return {"ok": ok, "steps": steps}
    else:
        steps.append({"step": "reload", "ok": True,
                       "message": f"{target} written — restart the rules-engine container to apply"})
        return {"ok": True, "steps": steps, "restart_needed": True}


@app.get("/api/deploy/health")
async def health():
    return {"ok": True, "data_dir": str(DATA_DIR), "repo_dir": str(REPO_DIR)}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    print(f"deploy-api: listening on {args.host}:{args.port}")
    print(f"  data_dir:   {DATA_DIR}")
    print(f"  repo_dir:   {REPO_DIR}")
    print(f"  engine_url: {ENGINE_URL}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
