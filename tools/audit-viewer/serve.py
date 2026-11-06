"""
Purpose: Lightweight API bridge for the Audit Viewer — reads from PostgreSQL (reporting.* views)
    or local JSONL audit files and serves JSON over HTTP for the HTML front end.
Version: v2 (2026-11-05) - v2: HISTORY_DSN fallback (runs on the Pi with history.env).
Scope: PRODUCTION once deployed on the Pi as boat-audit-api.service; also usable standalone.
Architecture: tools/audit-viewer/. Tiny HTTP server (stdlib http.server + psycopg for PG).
    No framework dependency beyond psycopg (optional — JSONL mode needs nothing).
Invocation: python serve.py [--dsn DSN] [--jsonl PATH] [--port 8766]
    --dsn  PostgreSQL connection string (AUDIT_DSN or explicit)
    --jsonl  path to var/audit.jsonl (engine host or copied)
    --port  HTTP port (default 8766)
    Serves tools/audit-viewer/ static files AND /api/* endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent

# --- JSONL reader ---
def read_jsonl(path: Path, limit: int = 10000) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def jsonl_decisions(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r.get("kind") == "audit":
            out.append(r)
    return out


def jsonl_events(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r.get("kind") == "event":
            out.append(r)
    return out


def jsonl_signal_history(rows: list[dict], signal: str) -> list[dict]:
    """Extract value snapshots for a given signal from decision_input records."""
    points = []
    for r in rows:
        if r.get("kind") != "audit":
            continue
        inputs = r.get("inputs") or r.get("payload", {}).get("inputs") or []
        for inp in inputs:
            if inp.get("signal") == signal and inp.get("known"):
                points.append({
                    "ts": r.get("ts"),
                    "value": inp.get("value"),
                    "rule": r.get("rule"),
                    "decision_kind": r.get("payload", {}).get("kind") if isinstance(r.get("payload"), dict) else None,
                    "outcome": r.get("outcome"),
                    "severity": r.get("payload", {}).get("severity") if isinstance(r.get("payload"), dict) else None,
                })
        # Also check top-level structure from audit_db.py queue items
        for inp in (r.get("inputs") or []):
            if isinstance(inp, dict) and inp.get("signal") == signal and inp.get("known"):
                if not any(p["ts"] == r.get("ts") for p in points):
                    points.append({
                        "ts": r.get("ts"),
                        "value": inp.get("value"),
                        "rule": r.get("rule") or r.get("rule_id"),
                        "decision_kind": r.get("kind") if r.get("kind") != "audit" else None,
                        "outcome": r.get("outcome"),
                        "severity": r.get("severity"),
                    })
    points.sort(key=lambda p: p["ts"] or 0)
    return points


def jsonl_signals(rows: list[dict]) -> list[str]:
    """Unique signal names seen in decision inputs."""
    sigs = set()
    for r in rows:
        for inp in (r.get("inputs") or []):
            if isinstance(inp, dict) and inp.get("signal"):
                sigs.add(inp["signal"])
        payload = r.get("payload")
        if isinstance(payload, dict):
            for inp in (payload.get("inputs") or []):
                if isinstance(inp, dict) and inp.get("signal"):
                    sigs.add(inp["signal"])
    return sorted(sigs)


def jsonl_rules(rows: list[dict]) -> list[str]:
    """Unique rule IDs seen in decisions."""
    rules = set()
    for r in rows:
        rid = r.get("rule") or r.get("rule_id")
        if rid:
            rules.add(rid)
    return sorted(rules)


# --- PostgreSQL reader ---
class PgReader:
    def __init__(self, dsn: str):
        import psycopg
        self.conn = psycopg.connect(dsn, autocommit=True)

    def decisions(self, limit: int = 500, rule: str | None = None,
                  severity: str | None = None, since: str | None = None) -> list[dict]:
        q = "SELECT * FROM reporting.audit_decisions WHERE true"
        params: list = []
        if rule:
            q += " AND rule_id = %s"
            params.append(rule)
        if severity:
            q += " AND severity = %s"
            params.append(severity)
        if since:
            q += " AND ts >= %s::timestamptz"
            params.append(since)
        q += " ORDER BY ts DESC, decision_id DESC LIMIT %s"
        params.append(limit)
        cur = self.conn.execute(q, params)
        cols = [d.name for d in cur.description]
        return [_row_to_dict(cols, row) for row in cur.fetchall()]

    def decision_inputs(self, decision_id: int) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM reporting.audit_why WHERE decision_id = %s ORDER BY signal",
            (decision_id,))
        cols = [d.name for d in cur.description]
        return [_row_to_dict(cols, row) for row in cur.fetchall()]

    def signal_history(self, signal: str, limit: int = 1000, since: str | None = None) -> list[dict]:
        q = ("SELECT ts, decision_id, value, known, age_s, "
             "(SELECT d.rule_id FROM audit.decision d WHERE d.host = i.host AND d.id = i.decision_id AND d.ts = i.ts) as rule_id, "
             "(SELECT d.kind FROM audit.decision d WHERE d.host = i.host AND d.id = i.decision_id AND d.ts = i.ts) as decision_kind, "
             "(SELECT d.outcome FROM audit.decision d WHERE d.host = i.host AND d.id = i.decision_id AND d.ts = i.ts) as outcome, "
             "(SELECT d.severity FROM audit.decision d WHERE d.host = i.host AND d.id = i.decision_id AND d.ts = i.ts) as severity "
             "FROM audit.decision_input i WHERE signal = %s")
        params: list = [signal]
        if since:
            q += " AND ts >= %s::timestamptz"
            params.append(since)
        q += " ORDER BY ts DESC LIMIT %s"
        params.append(limit)
        cur = self.conn.execute(q, params)
        cols = [d.name for d in cur.description]
        return [_row_to_dict(cols, row) for row in cur.fetchall()]

    def relay_proof(self, limit: int = 200, function: str | None = None) -> list[dict]:
        q = "SELECT * FROM reporting.relay_proof WHERE true"
        params: list = []
        if function:
            q += " AND function = %s"
            params.append(function)
        q += " LIMIT %s"
        params.append(limit)
        cur = self.conn.execute(q, params)
        cols = [d.name for d in cur.description]
        return [_row_to_dict(cols, row) for row in cur.fetchall()]

    def timeline(self, limit: int = 500, rule: str | None = None, since: str | None = None) -> list[dict]:
        q = "SELECT * FROM reporting.timeline WHERE true"
        params: list = []
        if rule:
            q += " AND rule_id = %s"
            params.append(rule)
        if since:
            q += " AND ts >= %s::timestamptz"
            params.append(since)
        q += " ORDER BY ts DESC, id DESC NULLS LAST LIMIT %s"
        params.append(limit)
        cur = self.conn.execute(q, params)
        cols = [d.name for d in cur.description]
        return [_row_to_dict(cols, row) for row in cur.fetchall()]

    def signals(self) -> list[str]:
        cur = self.conn.execute("SELECT DISTINCT signal FROM audit.decision_input ORDER BY signal")
        return [row[0] for row in cur.fetchall()]

    def rules(self) -> list[str]:
        cur = self.conn.execute("SELECT DISTINCT rule_id FROM audit.decision WHERE rule_id IS NOT NULL ORDER BY rule_id")
        return [row[0] for row in cur.fetchall()]


def _row_to_dict(cols: list[str], row: tuple) -> dict:
    d = {}
    for c, v in zip(cols, row):
        if isinstance(v, datetime):
            d[c] = v.isoformat()
        elif hasattr(v, "obj"):  # psycopg Jsonb wrapper
            d[c] = v.obj
        else:
            d[c] = v
    return d


# --- HTTP handler ---
class AuditHandler(SimpleHTTPRequestHandler):
    pg: PgReader | None = None
    jsonl_rows: list[dict] | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed.path[5:], parse_qs(parsed.query))
        else:
            super().do_GET()

    def _handle_api(self, path: str, qs: dict):
        try:
            data = self._dispatch(path, qs)
            self._json_response(200, data)
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _dispatch(self, path: str, qs: dict) -> Any:
        limit = int(qs.get("limit", [500])[0])
        rule = qs.get("rule", [None])[0]
        severity = qs.get("severity", [None])[0]
        since = qs.get("since", [None])[0]
        signal = qs.get("signal", [None])[0]
        function = qs.get("function", [None])[0]

        if self.pg:
            return self._dispatch_pg(path, limit, rule, severity, since, signal, function)
        elif self.jsonl_rows is not None:
            return self._dispatch_jsonl(path, limit, rule, severity, since, signal)
        else:
            return {"error": "no data source configured (use --dsn or --jsonl)"}

    def _dispatch_pg(self, path, limit, rule, severity, since, signal, function):
        if path == "decisions":
            return self.pg.decisions(limit, rule, severity, since)
        elif path == "signals":
            return self.pg.signals()
        elif path == "rules":
            return self.pg.rules()
        elif path == "signal-history" and signal:
            return self.pg.signal_history(signal, limit, since)
        elif path == "relay-proof":
            return self.pg.relay_proof(limit, function)
        elif path == "timeline":
            return self.pg.timeline(limit, rule, since)
        elif path.startswith("decision/"):
            did = int(path.split("/")[1])
            return self.pg.decision_inputs(did)
        else:
            return {"error": f"unknown endpoint: {path}"}

    def _dispatch_jsonl(self, path, limit, rule, severity, since, signal):
        rows = self.jsonl_rows
        if path == "decisions":
            decs = jsonl_decisions(rows)
            if rule:
                decs = [d for d in decs if (d.get("rule") or d.get("rule_id")) == rule]
            if severity:
                decs = [d for d in decs if d.get("severity") == severity or
                        (isinstance(d.get("payload"), dict) and d.get("payload", {}).get("severity") == severity)]
            return decs[-limit:]
        elif path == "events":
            return jsonl_events(rows)[-limit:]
        elif path == "signals":
            return jsonl_signals(rows)
        elif path == "rules":
            return jsonl_rules(rows)
        elif path == "signal-history" and signal:
            return jsonl_signal_history(rows, signal)[-limit:]
        elif path == "all":
            return rows[-limit:]
        else:
            return {"error": f"unknown endpoint: {path}"}

    def _json_response(self, code: int, data: Any):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)


def main():
    p = argparse.ArgumentParser(description="Audit Viewer API bridge")
    p.add_argument("--dsn", help="PostgreSQL DSN (or set AUDIT_DSN env var)")
    p.add_argument("--jsonl", help="path to audit.jsonl file")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()

    dsn = args.dsn or os.environ.get("AUDIT_DSN") or os.environ.get("HISTORY_DSN")
    if dsn:
        try:
            AuditHandler.pg = PgReader(dsn)
            print(f"Connected to PostgreSQL (reporting.* views)")
        except Exception as e:
            print(f"PostgreSQL connection failed: {e}")
            sys.exit(1)
    elif args.jsonl:
        path = Path(args.jsonl)
        if not path.exists():
            print(f"JSONL file not found: {path}")
            sys.exit(1)
        AuditHandler.jsonl_rows = read_jsonl(path)
        print(f"Loaded {len(AuditHandler.jsonl_rows)} rows from {path}")
    else:
        print("No data source: pass --dsn or --jsonl (or set AUDIT_DSN)")
        print("Starting in demo mode (API returns empty results)")
        AuditHandler.jsonl_rows = []

    server = HTTPServer(("127.0.0.1", args.port), AuditHandler)
    print(f"Audit Viewer at http://localhost:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
