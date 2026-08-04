#!/usr/bin/env python3
"""
generate_key_directory.py — W3: builds the JWKS-style key directory
document that KEY_DIRECTORY_URL (scan/identity.py) is meant to serve —
https://bots.parleo.io/.well-known/http-message-signatures-directory.

PUBLIC KEY MATERIAL ONLY. Reads BOT_SIGNING_KEY from the environment
(same variable scan/signing.py signs requests with) purely to derive
the public key + its WBA keyid — the private seed itself is never
written anywhere by this script.

This script is NEVER run automatically and its output is NEVER
committed (see the repo .gitignore) — a directory document is only
meaningful when it matches whatever key is CURRENTLY live in the
signing environment, and committing one risks it silently going stale
(or, worse, looking like a real published key when it's actually a
leftover from a dev machine). Regenerate on rotation:

    make keydirectory

Exits non-zero with a clear message if BOT_SIGNING_KEY isn't set —
never writes a placeholder/empty document that could be mistaken for
a real one.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scan import signing  # noqa: E402

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "keydirectory" / "http-message-signatures-directory.json"


def build_directory_document() -> dict:
    private_key = signing._load_private_key()
    if private_key is None:
        raise SystemExit(
            "BOT_SIGNING_KEY is not set (or is unusable) in this environment — "
            "refusing to write a key directory with no real key in it. "
            "Set BOT_SIGNING_KEY to the base64-encoded Ed25519 seed and retry."
        )
    jwk = signing.public_key_jwk(private_key)
    return {"keys": [jwk]}


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_PATH
    document = build_directory_document()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"wrote {output_path} (kid={document['keys'][0]['kid']})")


if __name__ == "__main__":
    main()
