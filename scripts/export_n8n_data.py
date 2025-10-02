#!/usr/bin/env python3
"""Utility script to export workflows and credentials from an n8n instance.

This script uses the n8n REST API over Basic Auth to download the latest
workflows and credentials so they can be checked into the repository under
`n8n/demo-data`. During deployment, the `n8n-import` init container will import
these files to seed the database.

Environment variables:
  N8N_BASE_URL              Base URL of the live n8n instance (default: https://n8n.virtualxperiencellc.com)
  N8N_BASIC_AUTH_USER       Username for n8n basic auth
  N8N_BASIC_AUTH_PASSWORD   Password for n8n basic auth

Example usage:
  $env:N8N_BASIC_AUTH_USER = "user@example.com"
  $env:N8N_BASIC_AUTH_PASSWORD = "s3cret"
  python scripts/export_n8n_data.py --workflows --credentials
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable

DEFAULT_BASE_URL = "https://n8n.virtualxperiencellc.com"
WORKFLOWS_ENDPOINT = "/rest/workflows"
CREDENTIALS_ENDPOINT = "/rest/credentials"


def slugify(value: str) -> str:
    """Return a filesystem-friendly slug based on the provided value."""
    value = value.strip().lower()
    # Replace invalid filename characters with dash
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    # Collapse multiple consecutive dashes
    value = re.sub(r"-+", "-", value)
    return value.strip("-") or "workflow"


def build_auth_headers(user: str, password: str) -> Dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "n8n-export-script/1.0",
    }


def fetch_json(base_url: str, path: str, headers: Dict[str, str]) -> Any:
    url = urllib.parse.urljoin(base_url, path)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(
            f"HTTP {exc.code} error while fetching {url}: {body or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc


def ensure_directory(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: pathlib.Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_workflows(base_url: str, headers: Dict[str, str], output_dir: pathlib.Path) -> int:
    listing = fetch_json(base_url, WORKFLOWS_ENDPOINT, headers)
    workflows = listing.get("data") or []
    count = 0
    for workflow in workflows:
        workflow_id = workflow.get("id")
        if workflow_id is None:
            continue
        detail = fetch_json(base_url, f"{WORKFLOWS_ENDPOINT}/{workflow_id}", headers)
        name = detail.get("name") or f"workflow-{workflow_id}"
        filename = f"{workflow_id}-{slugify(name)}.json"
        write_json(output_dir / filename, detail)
        count += 1
    return count


def export_credentials(base_url: str, headers: Dict[str, str], output_dir: pathlib.Path) -> int:
    params = urllib.parse.urlencode({"includeData": "true"})
    listing = fetch_json(base_url, f"{CREDENTIALS_ENDPOINT}?{params}", headers)
    credentials: Iterable[Dict[str, Any]] = listing.get("data") or []
    count = 0
    for credential in credentials:
        credential_id = credential.get("id")
        if credential_id is None:
            continue
        # When includeData=true, the API already returns full data for each credential
        # but we fetch the detail endpoint as well to keep parity with workflow export.
        detail = fetch_json(
            base_url, f"{CREDENTIALS_ENDPOINT}/{credential_id}?{params}", headers
        )
        name = detail.get("name") or f"credential-{credential_id}"
        filename = f"{credential_id}-{slugify(name)}.json"
        write_json(output_dir / filename, detail)
        count += 1
    return count


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("N8N_BASE_URL", DEFAULT_BASE_URL),
        help="Base URL of the live n8n instance",
    )
    parser.add_argument(
        "--output-root",
        default=pathlib.Path("n8n") / "demo-data",
        type=pathlib.Path,
        help="Root directory where demo data is stored",
    )
    parser.add_argument(
        "--workflows",
        action="store_true",
        help="Export workflows only (default is to export both workflows and credentials)",
    )
    parser.add_argument(
        "--credentials",
        action="store_true",
        help="Export credentials only (default is to export both workflows and credentials)",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    user = os.environ.get("N8N_BASIC_AUTH_USER")
    password = os.environ.get("N8N_BASIC_AUTH_PASSWORD")
    if not user or not password:
        print("Error: N8N_BASIC_AUTH_USER and N8N_BASIC_AUTH_PASSWORD must be set", file=sys.stderr)
        return 1

    headers = build_auth_headers(user, password)
    base_url = args.base_url.rstrip("/") + "/"

    export_workflows_flag = args.workflows or not (args.workflows or args.credentials)
    export_credentials_flag = args.credentials or not (args.workflows or args.credentials)

    workflows_dir = args.output_root / "workflows"
    credentials_dir = args.output_root / "credentials"

    total_workflows = total_credentials = 0

    try:
        if export_workflows_flag:
            ensure_directory(workflows_dir)
            total_workflows = export_workflows(base_url, headers, workflows_dir)

        if export_credentials_flag:
            ensure_directory(credentials_dir)
            total_credentials = export_credentials(base_url, headers, credentials_dir)
    except RuntimeError as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Export completed",
        "workflows" if export_workflows_flag else "",
        total_workflows if export_workflows_flag else "",
        "credentials" if export_credentials_flag else "",
        total_credentials if export_credentials_flag else "",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
