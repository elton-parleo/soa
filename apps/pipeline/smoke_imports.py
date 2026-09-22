"""
smoke_imports.py — fail the deploy, not the first user's audit.

The production outage on 2026-09-22 was a NameError in module-level code
in scan/signing.py. It raised the first time anything imported the scan
package, which — because _run_lite_scan imports run_scan lazily, inside
the request — happened for the first time when a real visitor submitted
a real audit. The container started clean, the health check passed, and
the bug surfaced as a broken report.

This runs the imports the worker will need before the worker starts, in
the SAME process environment it will have (railway.toml chains it ahead
of `python worker.py`), so a missing BOT_SIGNING_KEY or a typo in
module-level code is a failed boot with a named exception rather than a
silently degraded service. Exit 0 means every module below imported
cleanly; any other exit means the deploy should not proceed.

Deliberately imports only — nothing here fetches, scores, or touches the
database. The point is to execute module-level code, which is where this
class of bug lives.
"""
import importlib
import os
import sys
import traceback

# The chain that broke, plus the worker itself. scan.engine pulls in
# fetcher -> signing -> identity and the rest of the package; signing is
# named separately because it is the module that actually failed and the
# one with the env dependency (BOT_SIGNING_KEY).
MODULES = ("scan.engine", "scan.signing", "worker")


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    failed = []
    for name in MODULES:
        try:
            importlib.import_module(name)
            print(f"[smoke] {name}: ok")
        except Exception:
            failed.append(name)
            print(f"[smoke] {name}: FAILED", file=sys.stderr)
            traceback.print_exc()

    if failed:
        print(f"[smoke] {len(failed)} module(s) failed to import: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"[smoke] all {len(MODULES)} modules imported cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
