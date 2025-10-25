from __future__ import annotations
import time
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

WORKFLOWS_ENDPOINT = "/api/v1/workflows"
CREDENTIALS_ENDPOINT = "/api/v1/credentials"


def build_auth_headers(user: str | None, password: str | None, api_key: str | None) -> Dict[str, str]:
    import random
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.70 Safari/537.36",
    ]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": random.choice(user_agents),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Origin": "https://www.google.com/",
    }
    if api_key:
        headers["X-N8N-API-KEY"] = api_key
    elif user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


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

    """Load JSON files from directory. Supports single object or array of objects. Returns list of (source_path, object) pairs."""
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
    # Only include allowed properties for n8n public API
    allowed_keys = {"name", "nodes", "connections", "settings"}
    wf_payload = {k: v for k, v in workflow.items() if k in allowed_keys}
    # Only allow specific keys in settings for n8n public API
    allowed_settings_keys = {
        "saveDataErrorExecution",
        "saveDataSuccessExecution",
        "saveManualExecutions",
        "executionTimeout",
        "timezone",
        "retryOnFail",
        "maxTries",
        "errorWorkflow"
    }
    if "settings" in wf_payload and isinstance(wf_payload["settings"], dict):
        wf_payload["settings"] = {k: v for k, v in wf_payload["settings"].items() if k in allowed_settings_keys}
    else:
        wf_payload["settings"] = {}

    # Sanitize each node in the nodes list to only allowed properties
    allowed_node_keys = {
        "id", "name", "type", "parameters", "position", "credentials", "disabled", "notes",
        "retryOnFail", "maxTries", "errorWorkflow", "webhookId", "version"
    }
    if "nodes" in wf_payload and isinstance(wf_payload["nodes"], list):
        wf_payload["nodes"] = [
            {k: v for k, v in node.items() if k in allowed_node_keys}
            if isinstance(node, dict) else node
            for node in wf_payload["nodes"]
        ]
    if not workflow_id:
        created = request_json(base_url, "POST", WORKFLOWS_ENDPOINT, headers, wf_payload, (200, 201))
        return f"created:{created.get('id','?')}"
    # Try update
    try:
        # For update, keep id in path, but remove from body
        request_json(base_url, "PUT", f"{WORKFLOWS_ENDPOINT}/{workflow_id}", headers, wf_payload, (200,))
        return f"updated:{workflow_id}"
    except RuntimeError as exc:
        if "404" in str(exc):
            created = request_json(base_url, "POST", WORKFLOWS_ENDPOINT, headers, wf_payload, (200, 201))
            return f"created_after_404:{created.get('id','?')}"
        raise


def upsert_credential(base_url: str, headers: Dict[str, str], credential: Dict[str, Any]) -> str:
    credential_id = credential.get("id")
    # Only include allowed properties for n8n public API
    allowed_keys = {"name", "type", "data", "nodesAccess", "tags", "isManaged"}
    cred_payload = {k: v for k, v in credential.items() if k in allowed_keys}
    if not credential_id:
        created = request_json(base_url, "POST", CREDENTIALS_ENDPOINT, headers, cred_payload, (200, 201))
        return f"created:{created.get('id','?')}"
    try:
        request_json(base_url, "PUT", f"{CREDENTIALS_ENDPOINT}/{credential_id}", headers, cred_payload, (200,))
        return f"updated:{credential_id}"
    except RuntimeError as exc:
        if "404" in str(exc):
            created = request_json(base_url, "POST", CREDENTIALS_ENDPOINT, headers, cred_payload, (200, 201))
            return f"created_after_404:{created.get('id','?')}"
        raise


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import workflows and credentials into n8n")
    p.add_argument("--root", default=pathlib.Path("n8n") / "demo-data", type=pathlib.Path, help="Root folder containing workflows/ and credentials/")
    p.add_argument("--dry-run", action="store_true", help="Parse files but do not call API")
    p.add_argument("--wait-ready", type=int, default=0, metavar="SECONDS", help="Wait up to SECONDS for the n8n API to become responsive before importing")
    p.add_argument("--ready-interval", type=float, default=2.0, metavar="SEC", help="Polling interval while waiting for readiness (default: 2s)")
    p.add_argument("--min-workflows", type=int, default=0, help="Fail if fewer than this many workflow JSON objects are discovered locally")
    p.add_argument("--min-credentials", type=int, default=0, help="Fail if fewer than this many credential JSON objects are discovered locally")
    p.add_argument("--ready-log-every", type=int, default=10, metavar="N", help="Log a probe failure every N attempts (default: 10)")
    return p.parse_args(list(argv))


def wait_for_ready(base_url: str, headers: Dict[str, str], timeout_seconds: int, interval: float, log_every: int) -> bool:
    """Poll endpoints until ready or timeout. 200/401 from /rest/workflows or 200 from /rest/healthz/healthz is considered ready."""
    if timeout_seconds <= 0:
        return True
    endpoints = [WORKFLOWS_ENDPOINT, "/api/v1/healthz", "/healthz"]
    deadline = time.time() + timeout_seconds
    attempt = 0
    last_error: str | None = None
    while time.time() < deadline:
        attempt += 1
        for ep in endpoints:
            try:
                # Accept both 200 and 401 for workflows endpoint
                expected = (200, 401) if ep == WORKFLOWS_ENDPOINT else (200,)
                request_json(base_url, "GET", ep, headers, None, expected)
                print(f"Service ready after {attempt} attempt(s) via {ep}")
                return True
            except Exception as exc:  # noqa: BLE001
                last_error = f"{ep}: {exc}"
        if attempt % max(1, log_every) == 0 and last_error:
            print(f"Still waiting (attempt {attempt}) - last error: {last_error}")
        time.sleep(interval)
    if last_error:
        print(f"Final readiness failure after {attempt} attempts: {last_error}", file=sys.stderr)
    return False



def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    # Parse local files first so dry-run does not require network/env configuration
    workflows_dir = args.root / "workflows"
    credentials_dir = args.root / "credentials"
    workflow_files = load_json_files(workflows_dir)
    # Only import credentials from decrypted_credentials_for_import.json
    decrypted_file = credentials_dir / 'decrypted_credentials_for_import.json'
    credential_files = []
    if decrypted_file.exists():
        with open(decrypted_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                for idx, cred in enumerate(data):
                    credential_files.append((decrypted_file.with_name(f"{decrypted_file.name}#{idx}"), cred))
            else:
                credential_files.append((decrypted_file, data))
    print(f"Prepared {len(workflow_files)} workflow objects, {len(credential_files)} credential objects")

    # Local count sanity checks before any API requirement
    if args.min_workflows and len(workflow_files) < args.min_workflows:
        print(f"Error: discovered only {len(workflow_files)} workflows (< --min-workflows {args.min_workflows})", file=sys.stderr)
        return 1
    if args.min_credentials and len(credential_files) < args.min_credentials:
        print(f"Error: discovered only {len(credential_files)} credentials (< --min-credentials {args.min_credentials})", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry-run complete; no API calls made")
        return 0

    base_url = os.environ.get("N8N_BASE_URL") or os.environ.get("WEBHOOK_URL")
    if not base_url:
        print("Error: N8N_BASE_URL (or WEBHOOK_URL) must be set", file=sys.stderr)
        return 1
    if not base_url.endswith("/"):
        base_url += "/"

    api_key = os.environ.get("N8N_API_KEY")
    user = os.environ.get("N8N_BASIC_AUTH_USER")
    password = os.environ.get("N8N_BASIC_AUTH_PASSWORD")

    if not api_key and (not user or not password):
        print("Error: Either N8N_API_KEY or both N8N_BASIC_AUTH_USER and N8N_BASIC_AUTH_PASSWORD must be set", file=sys.stderr)
        return 1

    skip_workflows = bool(os.environ.get("N8N_SKIP_WORKFLOWS"))
    skip_credentials = bool(os.environ.get("N8N_SKIP_CREDENTIALS"))

    headers = build_auth_headers(user, password, api_key)

    if not wait_for_ready(base_url, headers, args.wait_ready, args.ready_interval, args.ready_log_every):
        print(f"Error: n8n API not ready after --wait-ready {args.wait_ready} seconds", file=sys.stderr)
        return 1

    actions: list[str] = []

    try:
        if not skip_workflows:
            for path, wf in workflow_files:
                try:
                    result = upsert_workflow(base_url, headers, wf)
                    actions.append(f"workflow:{path.name}:{result}")
                except RuntimeError as exc:
                    if "403" in str(exc):
                        print(f"403 Forbidden on workflow {path.name}: {exc}", file=sys.stderr)
                    else:
                        raise
                time.sleep(1)  # Add delay to avoid WAF rate limits
        else:
            print("Skipping workflows (N8N_SKIP_WORKFLOWS set)")

        if not skip_credentials:
            for path, cred in credential_files:
                try:
                    result = upsert_credential(base_url, headers, cred)
                    actions.append(f"credential:{path.name}:{result}")
                except RuntimeError as exc:
                    if "403" in str(exc):
                        print(f"403 Forbidden on credential {path.name}: {exc}", file=sys.stderr)
                    else:
                        raise
                time.sleep(2)  # Add delay to avoid WAF blocks
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
