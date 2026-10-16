#!/usr/bin/env python3
"""
Run the Audit's domain checks for one cycle scored before 2E, and store them.

    python3 scripts/run_domain_checks.py --cycle <id or code> --dry-run
    python3 scripts/run_domain_checks.py --cycle <id or code>

The worker runs these at scoring time from 2E on (orchestrator stage 2d).
A cycle scored before that (229) has none, so its Share of Algorithm shows
Protocol & Feed Presence and Value Protocols as not measured. This runs
the same code (scoring/domain_checks.run_for_cycle) for one cycle: the
merchant from the cycle's questions, its own domains from supply
/retailers, a product page from the reference read the cycle was scored
against, and the fetches through the scan's own fetcher, with the honest
UA, robots.txt honoured, the SSRF guard, and Web Bot Auth when the key is
set.

It fetches the merchant's LIVE domains. --dry-run fetches and prints
exactly what would be stored, and writes nothing to the database; on a
cycle that already holds a record it prints the stored record beside the
new one, field by field. Without it, the record is stored on
soa_cycles.domain_checks: a record already there is replaced (with
--replace), never appended, and the new one's `revision` is one past it.
The next read of the cycle's score recomputes (its measured set or the
record's revision changed) and keeps the old value in the score's history.

Journaled: every run appends to a JSON-lines journal (--journal, default
./domain_checks_journal/<cycle>.jsonl): the start, the record exactly as
it would be stored, and whether it was. A cycle that already holds a
record is refused without --replace, and the replaced record goes to the
journal first.

No model is called.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from scoring import domain_checks  # noqa: E402


def find_cycle(conn, ref: str):
    """(id, cycle_code, study_type) by id or code."""
    by = "id = :r" if str(ref).isdigit() else "cycle_code = :r"
    row = conn.execute(text(f"SELECT id, cycle_code, study_type FROM soa_cycles WHERE {by}"),
                       {"r": int(ref) if str(ref).isdigit() else ref}).fetchone()
    if not row:
        raise SystemExit(f"no cycle {ref!r}")
    return row


def stored_measured(conn, cycle_id: int):
    """The measured set the cycle's stored score was computed on, if any."""
    try:
        body = domain_checks._json(conn.execute(
            text("SELECT share_of_algorithm FROM soa_cycles WHERE id = :i"), {"i": cycle_id}).scalar())
    except Exception:  # noqa: BLE001 - the score column is not there before f3b8d2a6c4e1
        return None
    return (body or {}).get("measured") if isinstance(body, dict) else None


class Journal:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def write(self, event: str, **fields) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                               default=str) + "\n")


def main(argv=None, *, engine=None, client=None, fetch=None, out=None) -> int:
    parser = argparse.ArgumentParser(description="Run and store the Audit's domain checks for one cycle.")
    parser.add_argument("--cycle", required=True, help="cycle id or cycle_code")
    parser.add_argument("--dry-run", action="store_true", help="fetch and print; write nothing to the database")
    parser.add_argument("--replace", action="store_true", help="replace a record the cycle already holds")
    parser.add_argument("--journal", help="JSON-lines journal path (default ./domain_checks_journal/<cycle>.jsonl)")
    args = parser.parse_args(argv)
    out = out or sys.stdout

    if engine is None:
        from soa_shared.database import engine
    with engine.connect() as conn:
        cid, code, study_type = find_cycle(conn, args.cycle)
        has_column = domain_checks.column_exists(conn)
        before_measured = stored_measured(conn, cid)
    existing = domain_checks.stored(engine, cid) if has_column else None
    journal = Journal(args.journal or os.path.join("domain_checks_journal", f"{code}.jsonl"))

    def say(line=""):
        print(line, file=out)

    say(f"cycle {code} (id {cid}) — the Audit's domain checks, live fetches with the honest UA; no model call")
    if not has_column and not args.dry_run:
        say("soa_cycles.domain_checks is missing: apply migration b4e8f1c3a9d2 first (or run --dry-run)")
        return 2
    if existing and not args.replace and not args.dry_run:
        say(f"the cycle already holds a record (checked {existing.get('checked_at')}); --replace to replace it")
        return 2

    journal.write("start", cycle=code, cycle_id=cid, dry_run=args.dry_run, replace=args.replace,
                  existing_checked_at=(existing or {}).get("checked_at"))
    if client is None:
        from clients.truesync_catalog import TrueSyncCatalogClient
        client = TrueSyncCatalogClient.for_study(study_type)
    record = domain_checks.run_for_cycle(cid, engine=engine, client=client, fetch=fetch)
    journal.write("record", cycle=code, record=record)

    for line in domain_checks.summary_lines(record):
        say(line)
    say()
    if existing:
        say(f"the stored record (revision {existing.get('revision') or 1}) beside this one "
            f"(revision {domain_checks.next_revision(existing)} if written); * = changed:")
        for line in domain_checks.compare_lines({**existing, 'revision': existing.get('revision') or 1},
                                                {**record, 'revision': domain_checks.next_revision(existing)}):
            say(line)
        say()
    if not record.get("domains"):
        say("nothing checked: no own domain for the cycle's merchant. Nothing written.")
        journal.write("end", cycle=code, stored=False, reason="nothing checked")
        return 1
    if before_measured is not None:
        say(f"stored score's measured set: {', '.join(before_measured)}")
    if existing:
        say("the score of record recomputes on its next read (the record's revision changes); "
            "the previous value stays in the score's history.")
    else:
        say("protocol_feed and value_protocols join the measured set on the next read of the score "
            "(not measured before); the previous value stays in the score's history.")
    if args.dry_run:
        say("dry run — nothing written.")
        journal.write("end", cycle=code, stored=False, reason="dry run")
        say(f"journal: {journal.path}")
        return 0
    if existing:
        journal.write("replaced", cycle=code, record=existing)
    ok = domain_checks.store(engine, cid, record)
    say((f"{'replaced' if existing else 'stored'} on soa_cycles.domain_checks, revision {record['revision']}."
         if ok else "NOT stored: the column is missing."))
    journal.write("end", cycle=code, stored=ok)
    say(f"journal: {journal.path}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
