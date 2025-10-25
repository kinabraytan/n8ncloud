#!/usr/bin/env python3
"""
Decrypt n8n credentials from credentials1.json using N8N_ENCRYPTION_KEY and print the decrypted data for API import.

Usage:
  $env:N8N_ENCRYPTION_KEY = "your-32-char-hex-key"
  python scripts/decrypt_n8n_credentials.py

Notes:
- This script assumes n8n uses CryptoJS AES encryption (AES-256-CBC, PKCS7 padding, PBKDF2-SHA1, 1000 iterations).
- The encrypted blob is base64-encoded; format is likely: Salted__ + salt (8 bytes) + ciphertext.
- Requires pycryptodome.
"""
import os
import json
import pathlib
import base64
import sys
from Crypto.Cipher import AES
import hashlib
from Crypto.Util.Padding import unpad

CREDENTIALS_FILE = pathlib.Path("n8n/demo-data/credentials/credentials1.json")

# n8n uses 'Salted__' + salt (8 bytes) + ciphertext (OpenSSL format)
OPENSSL_MAGIC = b"Salted__"
PBKDF2_ITER = 1000
KEY_LEN = 32  # AES-256
IV_LEN = 16



def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int, iv_len: int) -> tuple[bytes, bytes]:
    # OpenSSL EVP_BytesToKey with MD5, 1 iteration
    dtot = b""
    d = b""
    while len(dtot) < (key_len + iv_len):
        d = hashlib.md5(d + password + salt).digest()
        dtot += d
    return dtot[:key_len], dtot[key_len:key_len + iv_len]


def decrypt_blob(blob: str, password: str) -> str:
    raw = base64.b64decode(blob)
    if not raw.startswith(OPENSSL_MAGIC):
        raise ValueError("Blob does not start with OpenSSL magic")
    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = evp_bytes_to_key(password.encode("utf-8"), salt, KEY_LEN, IV_LEN)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return decrypted.decode("utf-8")


def main():
    encryption_key = os.environ.get("N8N_ENCRYPTION_KEY")
    if not encryption_key:
        print("Missing N8N_ENCRYPTION_KEY environment variable.", file=sys.stderr)
        sys.exit(1)
    if not CREDENTIALS_FILE.exists():
        print(f"Credentials file not found: {CREDENTIALS_FILE}", file=sys.stderr)
        sys.exit(1)
    try:
        raw = CREDENTIALS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            print("credentials1.json must be a JSON array.", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"Failed to parse credentials1.json: {exc}", file=sys.stderr)
        sys.exit(1)
    output = []
    for cred in data:
        name = cred.get("name", "?")
        blob = cred.get("data")
        cred_id = cred.get("id")
        cred_type = cred.get("type")
        is_managed = cred.get("isManaged", False)
        created_at = cred.get("createdAt")
        updated_at = cred.get("updatedAt")
        if not blob:
            print(f"Credential '{name}' missing data field.", file=sys.stderr)
            continue
        try:
            decrypted = decrypt_blob(blob, encryption_key)
            # decrypted is a JSON string, parse it
            decrypted_data = json.loads(decrypted)
            output.append({
                "id": cred_id,
                "name": name,
                "type": cred_type,
                "data": decrypted_data,
                "isManaged": is_managed,
                "createdAt": created_at,
                "updatedAt": updated_at
            })
        except Exception as exc:
            print(f"Failed to decrypt credential '{name}': {exc}", file=sys.stderr)
    # Write output to JSON file
    out_path = pathlib.Path("n8n/demo-data/credentials/decrypted_credentials_for_import.json")
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Decrypted credentials written to {out_path}")

if __name__ == "__main__":
    main()
