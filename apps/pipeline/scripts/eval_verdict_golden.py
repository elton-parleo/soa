"""
The 2B verdict golden set: every changed verdict, and the rule that changed it.

    python3 scripts/eval_verdict_golden.py
    python3 scripts/eval_verdict_golden.py --gate

Reads tests/fixtures/verdict_golden/*.json (see its README) and re-runs the
CURRENT deterministic classifier over each row's stored inputs. Prints
before -> after for every row, marks the rows whose verdict moved, and
with --gate fails when the current classifier no longer produces a row's
recorded `verdict_after` — a verdict that moves is a deliberate act with a
new row, never a silent one.

No model call, no network: the record and the reference are fixtures.
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients.truesync_catalog import build_snapshot  # noqa: E402
from scoring import expectation_comparator as cmp  # noqa: E402
from scoring import record_variants as rv  # noqa: E402
from scoring.retailer_reference import ReferenceSet  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / 'tests' / 'fixtures'
GOLDEN_DIR = FIXTURES / 'verdict_golden'


def _load(*parts):
    return json.loads((FIXTURES.joinpath(*parts)).read_text())


def load_rows():
    return [json.loads(p.read_text()) for p in sorted(GOLDEN_DIR.glob('*.json'))]


def classify(row, *, ws_snapshot, reference):
    snapshot = build_snapshot(row['catalog']) if row.get('catalog') else ws_snapshot
    return cmp.compare(
        row['expectation'], row['extraction'], source_ref=row['source_ref'],
        record_variants=rv.from_snapshot(snapshot),
        reference=reference if row.get('reference') else None,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--gate', action='store_true')
    args = parser.parse_args(argv)

    ws = _load('wiggle_and_snug_catalog.json')
    ws_snapshot = build_snapshot(ws['catalog'], merchants=ws['merchants'],
                                 incentives=ws['incentives'], price_history=ws['price_history'])
    reference = ReferenceSet(_load('retailer_prices', 'acme_baby_as_of_cycle2.json'),
                             prior_payload=_load('retailer_prices', 'acme_baby_as_of_cycle1.json'),
                             prior_cycle_code='ACME-C1')
    rows = load_rows()
    failures, moved = [], 0
    print(f"verdict golden set: {len(rows)} rows ({GOLDEN_DIR.relative_to(FIXTURES.parent.parent)})")
    print(f"{'row':<5} {'before':>12} -> {'after':<13} {'moved':<6} rule")
    for row in rows:
        verdict = classify(row, ws_snapshot=ws_snapshot, reference=reference)
        changed = row['verdict_before'] != row['verdict_after']
        moved += changed
        flags = f" flags={','.join(verdict.flag_names)}" if verdict.flag_names else ''
        print(f"{row['id']:<5} {row['verdict_before']:>12} -> {verdict.outcome:<13} "
              f"{'yes' if changed else '':<6} {row['rule']}{flags}")
        if verdict.outcome != row['verdict_after'] or verdict.flag_names != row['flags_after']:
            failures.append(f"{row['id']}: recorded {row['verdict_after']} {row['flags_after']}, "
                            f"now {verdict.outcome} {verdict.flag_names}")
    print(f"\n{moved} of {len(rows)} verdicts differ from main's classifier; every row is "
          f"attributed {sorted({r['attribution'] for r in rows})}")
    if failures:
        print("\nFAILED: " + "; ".join(failures))
        return 1 if args.gate else 0
    print("every row reproduces its recorded verdict.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
