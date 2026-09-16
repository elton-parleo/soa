"""
Per-field agreement against the frozen golden set.

    python3 scripts/eval_extraction_golden.py
    python3 scripts/eval_extraction_golden.py --gate

The golden set is tests/fixtures/extraction_golden/: every row from a
hand-reviewed validate_extractions sample, with the answer, the
transcription as it was extracted at the time, and the field values the
review settled on.

What this measures is the DETERMINISTIC pipeline — the post-processing
and the classifier — run over the stored transcription. It makes no model
call, which is the point: it can run in CI, and it isolates the code from
the extractor. A field that regresses here regressed because somebody
changed the code.

What it does NOT measure is the extractor or the labeller. Those are
measured by drawing a fresh sample and reading it, which is what produced
this fixture in the first place. Nothing here replaces that, and a green
gate is not evidence that the model got better.

The gate is a floor, not a target: overall agreement must clear
--min-overall, and no field may score below the level recorded in
BASELINE. A field that improves raises its own floor the next time
somebody updates BASELINE deliberately.
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import extraction_postprocess as pp  # noqa: E402
from soa_shared import expected_answers as ea  # noqa: E402

GOLDEN_DIR = pathlib.Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'extraction_golden'

BRAND = 'Wiggle & Snug'
DOMAIN = 'trueshopstore.com'

# Where each field stood when the gate was introduced, measured by this
# script on the day it was written. Raising one of these is a deliberate
# act; a field falling below its entry is a regression and fails the run.
# Measured on the day the gate was introduced, over all three reviewed
# samples. A field below its entry is a regression and fails the run;
# raising an entry is a deliberate act.
#
# The four fields short of 1.000 are short for one reason, and it is not
# the code: EVERY remaining miss is in seed 1, drawn from the first
# extractor, which had no `sizes` field and no `recommended_retailers` —
# so "4 oz" is sitting in pack_counts and three recommended shops are
# sitting in sources_cited. Nothing downstream can know that a bare 4
# attributed to a balm means ounces. Those were fixed in the extractor,
# and seeds 2, 3 and 4 all scoring 1.000 is what says so. Seed 1 stays in
# the golden set because a gate that only contains rows the code can win
# is not a gate.
#
# What the gate does NOT cover: the labeller. It replays the golden
# labels, so it measures the code around them. Labelling accuracy is
# measured by drawing a sample and reading it.
BASELINE = {
    'brand_mentioned': 1.0,
    'sizes': 0.974,
    'prices': 0.993,
    'pack_counts': 0.974,
    'member_prices': 1.0,
    'sources_cited': 0.993,
    'other_brands': 1.0,
    'retailers': 0.993,
}

FIELDS = tuple(BASELINE)


def load():
    return [json.loads(p.read_text()) for p in sorted(GOLDEN_DIR.glob('*.json'))]


def _key(entry):
    if isinstance(entry, dict):
        return tuple(sorted((k, pp._flat(v)) for k, v in entry.items()))
    return pp._flat(entry)


def _same(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, map(_key, a))) == sorted(map(str, map(_key, b)))
    return a == b


def run_pipeline(row):
    """The deterministic pass over the stored transcription, plus the
    golden labels replayed — so this measures the code and not the
    labeller."""
    record = pp.normalize(
        json.loads(json.dumps(row['as_extracted'])),
        answer_text=row['answer'], brand=BRAND, brand_domain=DOMAIN,
    )
    labels = {
        'brand_sentences': [],
        # Including the names the review said are not brands at all: the
        # golden drops them, so the label that drops them has to be sent.
        'other_brands': [
            {'name': name, 'relation': relation}
            for name, relation in {
                **{n: r for n, r in (row['golden'].get('other_brands') or {}).items() if r},
                **{n: r for n, r in ((row.get('review_note') or {}).get('brands') or {}).items()
                   if r == 'not_a_brand'},
            }.items()
        ],
        'retailers': [
            {'name': name, 'role': role}
            for name, role in (row['golden'].get('retailers') or {}).items()
            if role
        ],
    }
    return pp.apply_labels(record, labels)


def as_extracted(row):
    """
    What was stored before any of this — the transcription as the cycle
    scored it, with the fields the new pipeline adds absent.

    This is the "before" number, and it is the only one in this script
    that is not partly circular: the golden values for the mechanical
    fields were DERIVED by applying the rulings, so the new pipeline
    agreeing with them measures that the rules were implemented as
    written, not that they are right. What the before/after gap measures
    is real — it is the distance the stored rows had to travel.
    """
    record = json.loads(json.dumps(row['as_extracted']))
    record.setdefault('retailer_mentions', [
        {'name': name, 'role': None}
        for name in record.get('recommended_retailers') or []
    ])
    return record


def compare(row, produced):
    golden = row['golden']
    out = {}
    for field in FIELDS:
        if field == 'other_brands':
            got = {e['name'] for e in produced.get('other_brands_named') or []
                   if isinstance(e, dict) and e.get('name')}
            out[field] = got == set(golden['other_brands'])
        elif field == 'retailers':
            got = {m['name'] for m in produced.get('retailer_mentions') or []}
            out[field] = got == set(golden['retailers'])
        else:
            out[field] = _same(produced.get(field), golden[field])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-field agreement against the frozen golden set.",
    )
    parser.add_argument('--gate', action='store_true',
                        help='exit non-zero if the floor is not met')
    parser.add_argument('--min-overall', type=float, default=0.90)
    parser.add_argument('--show-misses', action='store_true')
    parser.add_argument(
        '--before', action='store_true',
        help='score the stored transcription instead of the new pipeline',
    )
    parser.add_argument('--seed', type=int, action='append', dest='seeds',
                        help='restrict to one sample; repeatable')
    parser.add_argument(
        '--reviewed-only', action='store_true',
        help=(
            'only the rows the review explicitly ruled on. The mechanical '
            'golden values were derived from the rulings, so agreeing with '
            'them is partly circular; these rows are the part that is not.'
        ),
    )
    args = parser.parse_args(argv)

    rows = load()
    if args.seeds:
        rows = [r for r in rows if r['seed'] in args.seeds]
    if args.reviewed_only:
        rows = [r for r in rows if r.get('flagged_by_review')]
    if not rows:
        raise SystemExit(f"no golden rows in {GOLDEN_DIR}")

    produce = as_extracted if args.before else run_pipeline

    tally = {field: [0, 0] for field in FIELDS}
    misses = []
    for row in rows:
        result = compare(row, produce(row))
        for field, ok in result.items():
            tally[field][1] += 1
            tally[field][0] += 1 if ok else 0
            if not ok:
                misses.append((row['row'], field))

    print(f"golden set: {len(rows)} rows from "
          f"{len({r['seed'] for r in rows})} reviewed sample(s)"
          f"{' — review-flagged only' if args.reviewed_only else ''}")
    print(f"scoring: {'the stored transcription (before)' if args.before else 'the current pipeline (after)'}")
    print(f"{'field':<20} {'agree':>8}  {'baseline':>8}")
    failures = []
    for field in FIELDS:
        good, total = tally[field]
        rate = good / total if total else 0.0
        floor = BASELINE[field]
        flag = ''
        if rate < floor - 1e-9:
            flag = '   REGRESSION'
            failures.append(f"{field} {rate:.3f} < {floor:.3f}")
        print(f"{field:<20} {good:>3}/{total:<4}{rate:>7.3f}  {floor:>8.3f}{flag}")

    overall_good = sum(t[0] for t in tally.values())
    overall_total = sum(t[1] for t in tally.values())
    overall = overall_good / overall_total if overall_total else 0.0
    print(f"\noverall {overall_good}/{overall_total} = {overall:.3f} "
          f"(floor {args.min_overall:.2f})")
    if overall < args.min_overall - 1e-9:
        failures.append(f"overall {overall:.3f} < {args.min_overall:.2f}")

    if args.show_misses and misses:
        print("\nrows that disagree:")
        for row_number, field in misses:
            print(f"    row {row_number:>2}  {field}")

    if failures:
        print("\nFAILED: " + "; ".join(failures))
        # --before is a measurement, never a gate: it is expected to fail.
        return 1 if (args.gate and not args.before) else 0
    print("\nevery field at or above its floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
