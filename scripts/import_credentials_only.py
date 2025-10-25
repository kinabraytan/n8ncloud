#!/usr/bin/env python3
"""
Import credentials from credentials1.json into an n8n instance via REST API (public API v1).

IMPORTANT LIMITATION:
    - credentials1.json contains encrypted credential blobs (the 'data' field is a string).
    - The n8n public API expects the 'data' field to be a decrypted object, not an encrypted string.
    - This script cannot import credentials from credentials1.json via the public API unless it can decrypt the 'data' field (requires N8N_ENCRYPTION_KEY).
    - For proper import, use the n8n-import container or run the import script inside n8n with access to the encryption key.

Usage:
    $env:N8N_BASE_URL = "https://your-n8n.onrender.com"
    $env:N8N_API_KEY = "your-n8n-api-key"
    python scripts/import_credentials_only.py

Notes:
- Only POST is used (no update/PUT logic) to avoid 405 errors.
- credentials1.json must be in n8n/demo-data/credentials/.
- Requires N8N_BASE_URL and N8N_API_KEY environment variables.
- Will skip credentials that fail to import and print errors.
- If you see 'request/body/data must be object', you are trying to import encrypted credentials via the public API, which is not supported.
"""

import os
import json
import pathlib
import sys
import urllib.request
import urllib.parse
import urllib.error
import argparse

CREDENTIALS_FILE_DEFAULT = pathlib.Path("n8n/demo-data/credentials/decrypted_credentials_for_import.json")
CREDENTIALS_ENDPOINT = "/api/v1/credentials"


def build_headers(api_key: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-N8N-API-KEY": api_key,
    }


from typing import Optional

def fetch_schema(base_url: str, headers: dict, cred_type: str, cache: dict) -> Optional[dict]:
    if not isinstance(cred_type, str):
        return None
    if cred_type in cache:
        return cache[cred_type]
    url = urllib.parse.urljoin(base_url, f"/api/v1/credentials/schema/{cred_type}")
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Unexpected status {resp.status} for GET {url}")
            schema = json.loads(resp.read().decode("utf-8"))
            cache[cred_type] = schema
            return schema
    except Exception as exc:
        print(f"Warning: Could not fetch schema for type '{cred_type}': {exc}", file=sys.stderr)
        cache[cred_type] = None
        return None

def sanitize_data(data: dict, schema: Optional[dict]) -> dict:
    if not schema or "properties" not in schema:
        return data
    allowed = set(schema["properties"].keys())
    sanitized = {k: v for k, v in data.items() if k in allowed}
    # Add defaults for missing required fields
    for prop, prop_schema in schema["properties"].items():
        if prop not in sanitized and isinstance(prop_schema, dict) and "default" in prop_schema:
            sanitized[prop] = prop_schema["default"]
    return sanitized

def post_credential(base_url: str, headers: dict, cred: dict, schema_cache: dict) -> str:
    url = urllib.parse.urljoin(base_url, CREDENTIALS_ENDPOINT)
    allowed_keys = {"name", "type", "data", "nodesAccess", "tags", "isManaged"}
    cred_type = cred.get("type") or ""
    data = cred.get("data", {})
    schema = fetch_schema(base_url, headers, cred_type, schema_cache)
    if schema and "required" in schema:
        sanitized = sanitize_data(data, schema)
        missing = [req for req in schema["required"] if req not in sanitized]
        if missing:
            print(f"Skipping credential '{cred.get('name','?')}' (missing required fields: {missing})", file=sys.stderr)
            return "error:missing_required"
        payload = {k: v for k, v in cred.items() if k in allowed_keys}
        payload["data"] = sanitized
    else:
        print(f"Warning: No schema for credential type '{cred_type}' (credential '{cred.get('name','?')}')", file=sys.stderr)
        payload = {k: v for k, v in cred.items() if k in allowed_keys}
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"Unexpected status {resp.status} for POST {url}")
            return f"created:{resp.status}"
    except urllib.error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        print(f"Failed to import credential '{cred.get('name','?')}' (HTTP {exc.code}): {body_txt or exc.reason}", file=sys.stderr)
        return f"error:{exc.code}"
    except Exception as exc:
        print(f"Failed to import credential '{cred.get('name','?')}' ({exc})", file=sys.stderr)
        return "error:unknown"


def main():
    parser = argparse.ArgumentParser(description="Import credentials to n8n via public API.")
    parser.add_argument("--input", type=str, default=str(CREDENTIALS_FILE_DEFAULT), help="Path to credentials JSON file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate import but do not POST.")
    args = parser.parse_args()

    base_url = os.environ.get("N8N_BASE_URL")
    api_key = os.environ.get("N8N_API_KEY")
    if not base_url or not api_key:
        print("Missing N8N_BASE_URL or N8N_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)
    cred_file = pathlib.Path(args.input)
    if not cred_file.exists():
        print(f"Credentials file not found: {cred_file}", file=sys.stderr)
        sys.exit(1)
    try:
        raw = cred_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            print("Credentials file must be a JSON array.", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"Failed to parse credentials file: {exc}", file=sys.stderr)
        sys.exit(1)
    headers = build_headers(api_key)
    schema_cache = {}
    success = 0
    skipped = 0
    for cred in data:
        cred_type = cred.get("type") or ""
        data_obj = cred.get("data", {})
        schema = fetch_schema(base_url, headers, cred_type, schema_cache)
        if schema and "required" in schema:
            sanitized = sanitize_data(data_obj, schema)
            missing = [req for req in schema["required"] if req not in sanitized]
            if missing:
                print(f"Skipping credential '{cred.get('name','?')}' (missing required fields: {missing})", file=sys.stderr)
                skipped += 1
                continue
        if args.dry_run:
            print(f"[DRY-RUN] Would import credential '{cred.get('name','?')}' of type '{cred_type}'")
            success += 1
        else:
            result = post_credential(base_url, headers, cred, schema_cache)
            if result.startswith("created"):
                success += 1
    print(f"{'Dry-run:' if args.dry_run else 'Imported'} {success} credentials out of {len(data)}. Skipped: {skipped}.")

if __name__ == "__main__":
    main()
