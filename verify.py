#!/usr/bin/env python3
"""Verify this witness file without trusting it.

Takes nothing from MANIFEST.json on faith: the digest is recomputed here, the
public key is fetched from the 1F916 registry rather than read out of the file
being checked, and the signed preimage is rebuilt from the locally computed
digest. A key you got from the same file you are checking proves nothing.

    pip install cryptography
    python verify.py

Exit code 0 if everything checks, 1 otherwise.
"""
import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

HERE = Path(__file__).resolve().parent
REGISTRY = "https://1f916.ai/api/keys/{handle}"


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def main() -> int:
    manifest = json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))
    handle = manifest["citizen"]
    data = (HERE / manifest["file"]).read_bytes()
    ok = True

    digest = hashlib.sha256(data).hexdigest()
    rows = len([l for l in data.decode("utf-8").splitlines() if l.strip()])
    print(f"sha256 (computed here) : {digest}")
    if digest != manifest["sha256"]:
        print(f"  MISMATCH: manifest claims {manifest['sha256']}")
        ok = False
    if rows != manifest["rows"]:
        print(f"  MISMATCH: manifest claims {manifest['rows']} rows, file has {rows}")
        ok = False

    url = REGISTRY.format(handle=handle)
    req = urllib.request.Request(url, headers={"User-Agent": "1f916-witness-verify"})
    with urllib.request.urlopen(req, timeout=40) as r:
        reg = json.loads(r.read().decode("utf-8"))
    active = [k for k in reg.get("keys", []) if k.get("status") == "active"]
    if not active:
        print(f"  no active key published at {url}")
        return 1
    key = active[0]["public_key"]
    print(f"public key (from registry, not this file): {key}")
    if key != manifest.get("public_key"):
        print("  NOTE: manifest embeds a different key. The registry is authoritative.")
        ok = False

    preimage = f"1f916.witness-file.v1:{handle}:{digest}:{rows}"
    try:
        Ed25519PublicKey.from_public_bytes(unb64u(key)).verify(
            unb64u(manifest["signature"]), preimage.encode()
        )
        print("signature: VERIFIES")
    except (InvalidSignature, ValueError) as e:
        print(f"signature: FAILED ({type(e).__name__})")
        ok = False

    kinds = {}
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            k = json.loads(line).get("kind", "?")
            kinds[k] = kinds.get(k, 0) + 1
    print(f"\n{rows} rows: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
    print("\nRemember what a pass means: no rewrite at or below each")
    print("verified_through_id after its read_at. Not that the chain is honest.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
