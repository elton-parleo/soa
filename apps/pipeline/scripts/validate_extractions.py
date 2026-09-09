"""
The extraction validation harness.

The comparator is deterministic and re-checkable; the extraction is the
one judgement in the Layer 2 loop that a model makes. So its agreement
with a human is a number the report has to be able to state, and this is
how that number gets made.

Two modes, and the separation is the point:

    sample   pick N stored answers and write a side-by-side of the answer
             text and what the extractor transcribed from it, for a human
             to read

    record   write the agreement rate that human arrived at onto the
             cycle, where the report reads it

Nothing computes the agreement rate. The script cannot: agreement is
between a machine's reading and a person's, and a script that scored
itself would be measuring the thing it is supposed to be checked against.
Until someone runs `record`, soa_cycles.extraction_validation is NULL and
the report says "not validated" in words rather than printing a number.

Usage:

    python3 -m scripts.validate_extractions sample --cycle fc-2026-09 \
        --n 40 --out /tmp/ws-validation.md

    # ...read it, mark each row agree/disagree, count...

    python3 -m scripts.validate_extractions record --cycle fc-2026-09 \
        --sample-size 40 --agreed 37 --by elton \
        --notes "3 disagreements all on ranged prices"

Sampling is stratified by outcome, not uniform. A uniform sample of a run
that is 80% `exact` spends 80% of a human's attention on the easy case,
and the readings worth checking hardest are the ones that produced a
`wrong` or an `unscoreable`.
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import text

from soa_shared.database import engine

# Every outcome gets representation before any outcome gets a second
# row. `wrong` and `unscoreable` are the readings a human most needs to
# check: one is us calling an assistant incorrect, the other is us
# declining to score it at all.
STRATA = ['wrong', 'unscoreable', 'stale', 'absent', 'exact']

ANSWER_CHARS = 4000


def _cycle_id(conn, cycle_code: str) -> int:
    row = conn.execute(
        text("SELECT id FROM soa_cycles WHERE cycle_code = :code"),
        {"code": cycle_code},
    ).fetchone()
    if row is None:
        raise SystemExit(f"no cycle with code {cycle_code!r}")
    return row[0]


def _rows(conn, cycle_id: int):
    return conn.execute(text("""
        SELECT o.run_id, o.outcome, o.outcome_reason, o.expected_answer,
               o.extraction, o.tier, o.platform,
               q.query_code, q.query_text,
               r.run_number, r.raw_response
        FROM soa_expectation_outcomes o
        JOIN soa_queries q ON q.id = o.query_id
        JOIN soa_runs r ON r.id = o.run_id
        WHERE o.cycle_id = :cycle_id
        ORDER BY o.run_id
    """), {"cycle_id": cycle_id}).mappings().all()


def _stratified(rows, n: int, seed: int):
    """
    Round-robin across outcome buckets until n rows are taken.

    Deterministic given a seed, and the seed is printed into the output —
    a validation nobody can reproduce is a validation nobody can check.
    """
    buckets = defaultdict(list)
    for row in rows:
        buckets[row['outcome']].append(row)

    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    order = [s for s in STRATA if buckets.get(s)] + [
        s for s in buckets if s not in STRATA
    ]
    picked, index = [], 0
    while len(picked) < n:
        progressed = False
        for outcome in order:
            bucket = buckets[outcome]
            if index < len(bucket):
                progressed = True
                picked.append(bucket[index])
                if len(picked) >= n:
                    break
        if not progressed:
            break
        index += 1
    return picked


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _render(cycle_code, picked, total, seed) -> str:
    """
    Markdown, because it is read by a person and diffed by nobody.

    The answer comes FIRST and the extraction second, on purpose. A
    reader shown the extraction first reads the answer looking for
    confirmation of it, which is the thing this document exists to avoid.
    The outcome is shown last for the same reason: the question is "did
    the extractor read this answer correctly", not "was the verdict
    right".
    """
    out = [
        f"# Extraction validation — {cycle_code}",
        "",
        f"{len(picked)} of {total} scored answers, stratified by outcome, seed {seed}.",
        "",
        "For each row: read the ANSWER, decide what a correct transcription",
        "would say, then compare it to WHAT THE EXTRACTOR READ. Mark AGREE or",
        "DISAGREE. You are checking the transcription, not the verdict — an",
        "extractor that read the answer correctly agrees even where the",
        "outcome looks harsh.",
        "",
        "Count the agreements and record them with:",
        "",
        f"    python3 -m scripts.validate_extractions record --cycle {cycle_code} \\",
        f"        --sample-size {len(picked)} --agreed <N> --by <you>",
        "",
        "---",
        "",
    ]

    for i, row in enumerate(picked, 1):
        answer = row['raw_response'] or '(no answer text)'
        if len(answer) > ANSWER_CHARS:
            answer = answer[:ANSWER_CHARS] + '\n…(truncated)'

        out += [
            f"## {i}. {row['query_code']} · {row['platform']} · run {row['run_number']}",
            "",
            f"**Question asked:** {row['query_text']}",
            "",
            "### The answer",
            "",
            "```",
            answer,
            "```",
            "",
            "### What the extractor read",
            "",
            "```json",
            json.dumps(_json(row['extraction']), indent=2),
            "```",
            "",
            "### AGREE / DISAGREE:",
            "",
            "<!-- Only after deciding: -->",
            f"<!-- expected {json.dumps(_json(row['expected_answer']))} "
            f"-> {row['outcome']} ({row['outcome_reason']}) -->",
            "",
            "---",
            "",
        ]
    return "\n".join(out)


def cmd_sample(args) -> int:
    with engine.connect() as conn:
        cycle_id = _cycle_id(conn, args.cycle)
        rows = _rows(conn, cycle_id)

    if not rows:
        print(f"cycle {args.cycle} has no scored expectations to validate")
        return 1

    picked = _stratified(rows, args.n, args.seed)
    document = _render(args.cycle, picked, len(rows), args.seed)

    if args.out:
        with open(args.out, "w") as fh:
            fh.write(document)
        print(f"wrote {len(picked)} rows to {args.out}")
    else:
        sys.stdout.write(document)
    return 0


def cmd_record(args) -> int:
    """
    Writes the human's number onto the cycle. Refuses to invent one:
    --agreed and --sample-size are both required and are stored exactly
    as given, alongside who recorded them and when.
    """
    if args.agreed > args.sample_size:
        raise SystemExit("--agreed cannot exceed --sample-size")

    validation = {
        "sample_size": args.sample_size,
        "agreed": args.agreed,
        "agreement_rate": round(args.agreed / args.sample_size, 4),
        "validated_by": args.by,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "notes": args.notes,
    }

    with engine.connect() as conn:
        cycle_id = _cycle_id(conn, args.cycle)
        conn.execute(text("""
            UPDATE soa_cycles SET extraction_validation = :v, updated_at = NOW()
            WHERE id = :id
        """), {"v": json.dumps(validation), "id": cycle_id})
        conn.commit()

    print(
        f"recorded {args.agreed}/{args.sample_size} "
        f"({validation['agreement_rate']:.1%}) on {args.cycle}"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_extractions",
        description="Sample stored answers for hand-checking, and record the result.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sample = sub.add_parser("sample", help="write a side-by-side for hand-checking")
    sample.add_argument("--cycle", required=True)
    sample.add_argument("--n", type=int, default=40)
    sample.add_argument("--seed", type=int, default=1)
    sample.add_argument("--out", default=None)
    sample.set_defaults(func=cmd_sample)

    record = sub.add_parser("record", help="record the agreement rate a human arrived at")
    record.add_argument("--cycle", required=True)
    record.add_argument("--sample-size", type=int, required=True)
    record.add_argument("--agreed", type=int, required=True)
    record.add_argument("--by", required=True)
    record.add_argument("--notes", default=None)
    record.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
