#!/usr/bin/env python3
"""
2L-3: record the narrative writer's model responses for the FL13-shaped
fixture (tests/narratives_fixture.py: its flagged answers and 10 products),
so the tests replay them and never call a model.

    python scripts/record_narratives.py --cycle fl13
    python scripts/record_narratives.py --cycle fl13 --compare

One JSON file per subject's facts digest in tests/fixtures/narratives/, with
both calls (soa_shared/narratives.py CALLS), each call's usage, the model and
the request digest. A recording whose request changed (the prompt, the schema
or the facts) is stale and re-recorded; a current one is kept unless --force.

--compare calls the model again on every recorded subject and writes
nothing: how many lines differ in wording from the recording, and how many
fail a check. --no-record lists what would be recorded, with no call.

The summary: calls, input and output tokens (median and max per call), wall
time, and dollars at PRICE. Needs OPEN_AI_API_KEY; reads no database but the
fixture's in-memory sqlite.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# never the configured database: soa_shared.database builds its engine at import
os.environ['DATABASE_URL'] = 'postgresql://nobody@127.0.0.1:1/unused'

from soa_shared import narratives as n  # noqa: E402
from tests import narratives_fixture as fx  # noqa: E402

#: USD per million tokens for the default model (config.SOA_CODING_MODEL), from
#: OpenAI's pricing page (config.SOA_CODING_MODEL_PRICE says where and when). UNVERIFIED.
from soa_shared import config  # noqa: E402
PRICE = config.SOA_CODING_MODEL_PRICE


def summary(reports, seconds: float) -> str:
    calls = [c for r in reports for c in r['calls']]
    ins = [int((c.get('usage') or {}).get('input_tokens') or 0) for c in calls]
    outs = [int((c.get('usage') or {}).get('output_tokens') or 0) for c in calls]
    total = n.usage_totals(reports)
    return (f"{len(reports)} subjects, {len(calls)} calls, {seconds:.1f} s; input tokens median "
            f"{statistics.median(ins) if ins else 0:.0f} / max {max(ins, default=0)}, output tokens median "
            f"{statistics.median(outs) if outs else 0:.0f} / max {max(outs, default=0)}; "
            f"${n.dollars(total) or 0:.4f} at ${PRICE['input']:.2f} / ${PRICE['output']:.2f} per million tokens "
            f"(price of {PRICE['as_of']}, unverified)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--cycle', default=fx.NAME, choices=[fx.NAME], help='the fixture to record')
    p.add_argument('--out', default=fx.FIXTURES)
    p.add_argument('--force', action='store_true', help='re-record current recordings too')
    p.add_argument('--compare', action='store_true', help='call again and compare with the recordings; write nothing')
    p.add_argument('--no-record', action='store_true', help='list what would be recorded; no call')
    args = p.parse_args(argv)

    engine = fx.engine()
    with engine.connect() as conn:
        facts = n.load_cycle_facts(conn, fx.CYCLE_ID)
    os.makedirs(args.out, exist_ok=True)
    writer = n.LiveWriter()
    replay = n.RecordedWriter(args.out)

    def current(f) -> bool:
        try:
            replay(f)
            return True
        except n.MissingRecording:
            return False

    if args.compare:
        todo = [(s, f) for s, f in facts.items() if current(f)]
    else:
        todo = [(s, f) for s, f in facts.items() if args.force or not current(f)]
    print(f"{args.cycle}: {len(facts)} subjects, {len(todo)} to {'compare' if args.compare else 'record'}, "
          f"model {writer.model}")
    if args.no_record:
        for s, _f in todo:
            print(' ', s)
        return 0

    started = time.monotonic()
    reports, differ, moved, failed = [], 0, [], 0
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n.MAX_WORKERS) as pool:
        answers = list(pool.map(lambda item: writer(item[1]), todo))
    for (subject, f), answer in zip(todo, answers):
        decision = n.decide(answer, f)
        reports.append({'subject': subject, **decision})
        if args.compare:
            old = n.decide(replay(f), f)
            if decision['status'] == old['status'] == 'accepted':
                differ += decision['line'] != old['line']
            elif decision['status'] != old['status']:
                moved.append(f"{subject}: {old['status']} -> {decision['status']}"
                             + (f" ({decision['reason']})" if decision['reason'] else ''))
            failed += sum(1 for c in decision['calls'] if c['line'] is not None and c['check'] is not None)
            continue
        digest = n.facts_digest(f)
        with open(os.path.join(args.out, f"{digest}.json"), 'w') as fh:
            json.dump({'subject': subject, 'facts_digest': digest, 'request_digest': n.request_digest(f, answer.model),
                       'model': answer.model, 'facts': f,
                       'calls': [{'response': r, 'usage': u} for r, u in zip(answer.raws, answer.usage)]},
                      fh, indent=1, ensure_ascii=False, sort_keys=True)
            fh.write('\n')
    seconds = time.monotonic() - started
    counts = {s: sum(1 for r in reports if r['status'] == s) for s in ('accepted', 'dropped', 'null')}
    print(f"accepted {counts['accepted']}, dropped {counts['dropped']}, null {counts['null']}")
    for r in reports:
        if r['status'] == 'dropped':
            print(f"  dropped {r['subject']}: {r['reason']}")
    if args.compare:
        both = sum(1 for r in reports if r['status'] == 'accepted') - sum(1 for m in moved if m.endswith('accepted'))
        print(f"compared with the recordings: of the lines accepted both times ({both}), {differ} differ in "
              f"wording; {len(moved)} subject(s) changed status; {failed} of {2 * len(reports)} call(s) wrote a "
              f"line that fails a check (each dropped, never shown)")
        for m in moved:
            print('  ', m)
    print(summary(reports, seconds))
    return 0


if __name__ == '__main__':
    sys.exit(main())
