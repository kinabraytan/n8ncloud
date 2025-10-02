#!/usr/bin/env python3
"""Import workflows and credentials into an n8n instance via REST API.

Intended for seeding a freshly deployed Render-hosted (or any) n8n service
from repository-exported JSON files found under `n8n/demo-data`.

The script is idempotent:
* Existing workflows matched by id will be updated (PUT) instead of duplicated.
* Existing credentials matched by id will be updated (PATCH) instead of created.

Authentication: Basic Auth (same as export script). Provide credentials via
environment variables N8N_BASIC_AUTH_USER / N8N_BASIC_AUTH_PASSWORD.

Environment variables:
  N8N_BASE_URL              Base URL of the target n8n instance (required)
  N8N_BASIC_AUTH_USER       Username for n8n basic auth (required)
  N8N_BASIC_AUTH_PASSWORD   Password for n8n basic auth (required)
  N8N_SKIP_CREDENTIALS      If set to any truthy value, skip credential import
  N8N_SKIP_WORKFLOWS        If set to any truthy value, skip workflow import

Example usage (PowerShell):
  $env:N8N_BASE_URL = "https://your-n8n.onrender.com";
  $env:N8N_BASIC_AUTH_USER = "user@example.com";
  $env:N8N_BASIC_AUTH_PASSWORD = "s3cret";
  python scripts/import_n8n_data.py --root n8n/demo-data

Notes:
* Credential JSON must contain the encrypted `data` field which is portable
  only if the target instance uses the SAME N8N_ENCRYPTION_KEY.
* Ensure you have set the identical N8N_ENCRYPTION_KEY in Render before running.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable

WORKFLOWS_ENDPOINT = "/rest/workflows"
CREDENTIALS_ENDPOINT = "/rest/credentials"


def build_auth_headers(user: str, password: str) -> Dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "n8n-import-script/1.0",
    }


def request_json(base_url: str, method: str, path: str, headers: Dict[str, str], body: Any | None = None, expected: Iterable[int] = (200, 201)) -> Any:
    url = urllib.parse.urljoin(base_url, path)
    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status not in expected:
                raise RuntimeError(f"Unexpected status {resp.status} for {method} {url}")
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                charset = resp.headers.get_content_charset() or "utf-8"
                return json.loads(resp.read().decode(charset))
            return resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {body_txt or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc


def load_json_files(directory: pathlib.Path) -> list[tuple[pathlib.Path, Any]]:
    """Load JSON files.

    Supports two shapes:
      * Single object (dict) – treated as one entity
      * Array of objects     – each element treated as separate entity
    Returns a list of (source_path, object) pairs. For array expansions the
    filename is annotated with a pseudo index suffix for clearer logging.
    """
    items: list[tuple[pathlib.Path, Any]] = []
    if not directory.exists():
        return items
    for path in sorted(directory.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                for idx, element in enumerate(data):
                    if not isinstance(element, dict):  # skip non-object entries
                        print(f"Skipping {path} index {idx} (not an object)", file=sys.stderr)
                        continue
                    # Use a synthetic display path (original path kept for parent reference)
                    synthetic = pathlib.Path(f"{path.name}#{idx}")
                    items.append((synthetic, element))
            else:
                items.append((path, data))
        except Exception as exc:  # noqa: BLE001
            print(f"Skipping {path} (invalid JSON): {exc}", file=sys.stderr)
    return items


def upsert_workflow(base_url: str, headers: Dict[str, str], workflow: Dict[str, Any]) -> str:
    workflow_id = workflow.get("id")
    if not workflow_id:
        # Create new workflow if no id (rare for exported set)
        created = request_json(base_url, "POST", WORKFLOWS_ENDPOINT, headers, workflow, (200, 201))
        return f"created:{created.get('id','?')}"
    # Try update
    request_json(base_url, "PUT", f"{WORKFLOWS_ENDPOINT}/{workflow_id}", headers, workflow, (200,))
    return f"updated:{workflow_id}"


def upsert_credential(base_url: str, headers: Dict[str, str], credential: Dict[str, Any]) -> str:
    credential_id = credential.get("id")
    if not credential_id:
        created = request_json(base_url, "POST", CREDENTIALS_ENDPOINT, headers, credential, (200, 201))
        return f"created:{created.get('id','?')}"
    request_json(base_url, "PATCH", f"{CREDENTIALS_ENDPOINT}/{credential_id}", headers, credential, (200,))
    return f"updated:{credential_id}"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import workflows and credentials into n8n")
    p.add_argument("--root", default=pathlib.Path("n8n") / "demo-data", type=pathlib.Path, help="Root folder containing workflows/ and credentials/")
    p.add_argument("--dry-run", action="store_true", help="Parse files but do not call API")
    p.add_argument("--wait-ready", type=int, default=0, metavar="SECONDS", help="Wait up to SECONDS for the n8n API to become responsive before importing")
    p.add_argument("--ready-interval", type=float, default=2.0, metavar="SEC", help="Polling interval while waiting for readiness (default: 2s)")
    p.add_argument("--min-workflows", type=int, default=0, help="Fail if fewer than this many workflow JSON objects are discovered locally")
    p.add_argument("--min-credentials", type=int, default=0, help="Fail if fewer than this many credential JSON objects are discovered locally")
    return p.parse_args(list(argv))


def wait_for_ready(base_url: str, headers: Dict[str, str], timeout_seconds: int, interval: float) -> bool:
    """Poll the workflows endpoint until it responds or timeout expires.

    Returns True if ready, False otherwise.
    """
    if timeout_seconds <= 0:
        return True
    deadline = time.time() + timeout_seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            # Lightweight readiness probe: list workflows (no modification)
            request_json(base_url, "GET", WORKFLOWS_ENDPOINT, headers, None, (200,))
            print(f"Service ready after {attempt} attempt(s)")
            return True
        except Exception:  # noqa: BLE001
            time.sleep(interval)
    return False


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    base_url = os.environ.get("N8N_BASE_URL") or os.environ.get("WEBHOOK_URL")
    if not base_url:
        print("Error: N8N_BASE_URL (or WEBHOOK_URL) must be set", file=sys.stderr)
        return 1
    if not base_url.endswith("/"):
        base_url += "/"

    user = os.environ.get("N8N_BASIC_AUTH_USER")
    password = os.environ.get("N8N_BASIC_AUTH_PASSWORD")
    if not user or not password:
        print("Error: N8N_BASIC_AUTH_USER and N8N_BASIC_AUTH_PASSWORD must be set", file=sys.stderr)
        return 1

    skip_workflows = bool(os.environ.get("N8N_SKIP_WORKFLOWS"))
    skip_credentials = bool(os.environ.get("N8N_SKIP_CREDENTIALS"))

    headers = build_auth_headers(user, password)

    workflows_dir = args.root / "workflows"
    credentials_dir = args.root / "credentials"

    workflow_files = load_json_files(workflows_dir)
    credential_files = load_json_files(credentials_dir)

    print(f"Prepared {len(workflow_files)} workflow objects, {len(credential_files)} credential objects")

    # Local count sanity checks before API calls
    if args.min_workflows and len(workflow_files) < args.min_workflows:
        print(f"Error: discovered only {len(workflow_files)} workflows (< --min-workflows {args.min_workflows})", file=sys.stderr)
        return 1
    if args.min_credentials and len(credential_files) < args.min_credentials:
        print(f"Error: discovered only {len(credential_files)} credentials (< --min-credentials {args.min_credentials})", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry-run complete; no API calls made")
        return 0

    if not wait_for_ready(base_url, headers, args.wait_ready, args.ready_interval):
        print(f"Error: n8n API not ready after --wait-ready {args.wait_ready} seconds", file=sys.stderr)
        return 1

    actions: list[str] = []

    try:
        if not skip_workflows:
            for path, wf in workflow_files:
                result = upsert_workflow(base_url, headers, wf)
                actions.append(f"workflow:{path.name}:{result}")
        else:
            print("Skipping workflows (N8N_SKIP_WORKFLOWS set)")

        if not skip_credentials:
            for path, cred in credential_files:
                result = upsert_credential(base_url, headers, cred)
                actions.append(f"credential:{path.name}:{result}")
        else:
            print("Skipping credentials (N8N_SKIP_CREDENTIALS set)")

    except RuntimeError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print("Import summary:")
    for a in actions:
        print("  -", a)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
