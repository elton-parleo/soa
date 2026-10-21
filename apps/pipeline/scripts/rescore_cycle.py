"""
Re-score a cycle's Layer 2 outcomes, in place, one tier at a time.

There was no entry point for this. scoring/expectation_batch.py has the
orchestration and the live pipeline calls it, but an ops re-score of a
cycle that has already run had to be typed out by hand — which is how you
end up re-scoring more than you meant to.

    python3 scripts/rescore_cycle.py --cycle <code> --tier brand_direct

What it does, in order:

  1. counts the existing outcomes per tier, and prints them;
  2. re-scores only the runs whose question is in a named tier;
  3. counts them again, prints the diff, and FAILS if a tier nobody
     asked for moved.

Step 3 is the point of the script. Re-scoring one tier is supposed to
leave the others exactly as they were, and "supposed to" is not a thing
you can put in a report. The check runs every time and costs nothing.

A re-score REPLACES each row (soa_expectation_outcomes is unique on
run_id and the scorer deletes before inserting), so running it twice is
the same as running it once. It does not touch soa_runs, soa_coded_
mentions, or anything Layer 1 produced.

It costs one extraction call per run. --dry-run prints the plan and the
current counts and makes no model call and no write.

--classify-only (2B) makes NO model call at all. It re-runs the
deterministic classifier (scoring/expectation_comparator.py, through the
same classify() the live scorer uses) over each outcome row's STORED
expectation and extraction, and replaces the row. This is how every 2B
scoring change is applied to a cycle that already ran:

    python3 scripts/rescore_cycle.py --cycle <code> --classify-only

Layer 1 (soa_coded_mentions) is read as stored and never re-run: it is
model output, and re-deriving it would be a model call. Layer 2's spans,
transcription and labels are the stored extraction, also never re-run.
The network calls it can make are the catalog read (for rule 2's record
variants), the cycle's one retailer-prices read if it was never cached,
and the citation check (24-hour cache).

It replaces the unchanged-tiers guard for this kind of re-score. That
guard compares tier totals before and after, which cried wolf on
re-extract runs (a fresh extraction legitimately moves rows in every
tier). Here the extraction does not move, so the guard is replaced by two
checks that can be stated exactly: every row is classified TWICE and the
two passes must agree before anything is written, and every row whose
outcome moved is printed with the rule that moved it. A move no named rule
explains is `unattributed`, and while any exists the real run refuses to
write and prints them: "unattributed: classifier output changed on
identical inputs" when the stored expectation matches the question's
current one field for field, else the fields that differ.

--refresh-reference (2J-4), with --classify-only, refreshes the cycle's
cached retailer-prices after supply corrected its stored reads (supply's
reparse_reads.py --apply). The cached copy (soa_cycles.reference_prices) is
read once at a cycle's first scoring and never again. The console's True
Value grid and products block read it directly, and the price outcomes
(which the Missed share and the score's price rows count) are classified
against it.

    python3 scripts/rescore_cycle.py --cycle <code> --refresh-reference --classify-only --dry-run
    python3 scripts/rescore_cycle.py --cycle <code> --refresh-reference --classify-only --backup <path>
    python3 scripts/rescore_cycle.py --cycle <code> --classify-only --restore <path>

It reads supply's retailer-prices as of the cycle's STORED reference_as_of,
never now, so it picks up the corrected reads of the same run and not a
newer run. It prints the diff, cell by cell (variant x retailer: price,
method, read_status, verifiable, reference_source), then the outcome counts
before and after and the moves per tier, from classify-only's plan against
the fetched copy. With --dry-run it writes nothing. Without it, it refuses
with no --backup or an existing one; writes the cached copy to the backup
(the column's text exactly, and its sha256); replaces it with supply's
payload plus `refreshed_at` and `previous_sha256` (an envelope inside the
JSON, so no migration); and re-classifies. --restore puts a backup back,
byte for byte, under the same guards plus two: the backup must be this
cycle's, and the cycle's reference must be the one the refresh wrote.

The stale rule is untouched. `stale_basis` reads the PREVIOUS cycle's
cached rows, and this does not refresh them: refreshing cycle N does not
change what cycle N+1 considers stale unless N+1 is refreshed and
re-classified too, with the same flag.

The console's stored score recomputes on its next read: `refreshed_at`
differs from the one the stored score was computed on (console_score.
needs_recompute, 'cycle reference refreshed').
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import bindparam, text  # noqa: E402

from soa_shared import expected_answers as ea  # noqa: E402
from soa_shared.database import engine  # noqa: E402
from soa_shared.expected_answers import QUERY_TIERS  # noqa: E402

#: The tiers whose questions carry no expected answer, so nothing scores them:
#: category control and (2K-1) comparison. The default leaves them out.
NO_EXPECTATION_TIERS = ('category_control', 'comparison')


def cycle_id(conn, cycle_code: str) -> int:
    row = conn.execute(
        text("SELECT id FROM soa_cycles WHERE cycle_code = :code"),
        {"code": cycle_code},
    ).fetchone()
    if not row:
        raise SystemExit(f"no cycle with code {cycle_code!r}")
    return row[0]


def outcome_counts(conn, cid: int) -> dict:
    """{tier: {outcome: n}} for everything currently stored."""
    rows = conn.execute(text("""
        SELECT tier, outcome, COUNT(*)
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cid
        GROUP BY tier, outcome
    """), {"cid": cid}).fetchall()
    out = {}
    for tier, outcome, n in rows:
        out.setdefault(tier or '(untiered)', Counter())[outcome] = n
    return out


def run_ids_for(conn, cid: int, tiers) -> list:
    """
    Scoreable runs, narrowed to the named tiers.

    The expectation filter is the same one scoreable_run_ids uses and is
    not optional: a category-control question carries a tier and no
    expectation, and scoring it would write a row for a question nothing
    was ever expected of.
    """
    statement = text("""
        SELECT r.id
        FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :cid
          AND q.expected_answer IS NOT NULL
          AND q.tier IN :tiers
        ORDER BY r.id
    """).bindparams(bindparam("tiers", expanding=True))
    rows = conn.execute(statement, {"cid": cid, "tiers": list(tiers)}).fetchall()
    return [row[0] for row in rows]


def secondary_counts(conn, cid: int) -> dict:
    """
    {tier: {expectation type: {outcome: n}}} for the secondary results.

    Read apart from the primary outcomes because they move for different
    reasons and a re-score is expected to move only one of them. The
    correction that prompted this — a size read as a pack count — lands
    squarely on a pack_count secondary and must not touch the price
    outcome the secondary rides on.

    Counted in Python for the same reason tier_accuracy counts them in
    Python: secondary_results is a JSON array and the two dialects this
    runs on disagree about how to unnest one.
    """
    rows = conn.execute(text("""
        SELECT tier, secondary_results
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cid AND secondary_results IS NOT NULL
    """), {"cid": cid}).fetchall()

    out = {}
    for tier, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        for item in payload or []:
            kind, outcome = item.get('type'), item.get('outcome')
            if not kind or not outcome:
                continue
            out.setdefault(tier or '(untiered)', {}).setdefault(kind, Counter())
            out[tier][kind][outcome] += 1
    return out


def _render_secondary(counts: dict) -> str:
    lines = []
    for tier in sorted(counts):
        for kind in sorted(counts[tier]):
            inner = counts[tier][kind]
            detail = ', '.join(f"{o} {n}" for o, n in sorted(inner.items()))
            lines.append(f"    {tier} / {kind:<12} {sum(inner.values()):>4}  ({detail})")
    return '\n'.join(lines) or '    (no secondary expectations)'


def row_outcomes(conn, cid: int) -> dict:
    """
    {run_id: (query_code, platform, run_number, tier, outcome)}.

    The tier totals say how many moved; this says which. A correction to
    the extractor is supposed to move particular rows for particular
    reasons, and "twelve went from fabricated to acknowledged_unknown" is
    a number somebody has to take on trust. The list of twelve is not.
    """
    rows = conn.execute(text("""
        SELECT o.run_id, q.query_code, o.platform, r.run_number, o.tier, o.outcome
        FROM soa_expectation_outcomes o
        JOIN soa_runs r ON r.id = o.run_id
        JOIN soa_queries q ON q.id = r.query_id
        WHERE o.cycle_id = :cid
    """), {"cid": cid}).fetchall()
    return {
        row[0]: (row[1], row[2], row[3], row[4], row[5]) for row in rows
    }


def row_diff(before: dict, after: dict) -> list:
    """Every run whose outcome is not what it was, oldest run_id first."""
    moved = []
    for run_id in sorted(set(before) | set(after)):
        was = before.get(run_id)
        now = after.get(run_id)
        if was and now and was[4] == now[4]:
            continue
        moved.append((run_id, was, now))
    return moved


def _render_rows(moved: list, limit: int = 200) -> str:
    if not moved:
        return '    (no row changed its outcome)'
    lines = []
    for run_id, was, now in moved[:limit]:
        label = (now or was)
        code, platform, number, tier = label[0], label[1], label[2], label[3]
        lines.append(
            f"    {code} · {platform} · run {number} · {tier}: "
            f"{was[4] if was else '(none)'} -> {now[4] if now else '(gone)'}"
            f"   [run {run_id}]"
        )
    if len(moved) > limit:
        lines.append(f"    ... and {len(moved) - limit} more")
    return '\n'.join(lines)


def changed_tiers(before: dict, after: dict) -> list:
    """Every tier whose primary outcome counts are not identical."""
    return [
        tier for tier in sorted(set(before) | set(after))
        if dict(before.get(tier, {})) != dict(after.get(tier, {}))
    ]


def _render(counts: dict) -> str:
    lines = []
    for tier in sorted(counts):
        inner = counts[tier]
        total = sum(inner.values())
        detail = ', '.join(f"{o} {n}" for o, n in sorted(inner.items()))
        lines.append(f"    {tier:<20} {total:>4}  ({detail})")
    return '\n'.join(lines) or '    (nothing scored yet)'


def diff_untouched(before: dict, after: dict, targeted) -> list:
    """
    Every tier that changed and was not asked to. Empty is the result
    this script exists to be able to state.
    """
    moved = []
    for tier in sorted(set(before) | set(after)):
        if tier in targeted:
            continue
        if dict(before.get(tier, {})) != dict(after.get(tier, {})):
            moved.append(tier)
    return moved


# ─── 2B: classify-only ─────────────────────────────────────────────────────

RULES = {
    'product_inferred': '§3 rule 3: product_inferred can never be wrong',
    'variant_swap': '§3 rule 2: a clash naming another record variant (variant_swap)',
    'variant_clash': '§3 rule 2: a clash naming no record variant (variant_clash)',
    'not_our_product': '§3 rule 2 (narrowed): a price for something that is not our product is absent',
    'other_brand': "another brand's price (Layer 2 other_brands_named) is never ours",
    'grounding_support': 'brand-direct: a claim grounded by a platform support at a merchant domain',
    'own_domains': "brand-direct: the merchant's own domains are a list",
    'tenant_own_domains': "brand-direct: every own domain of every merchant in the tenant is ours (2D)",
    'program_name_not_tier': "brand-direct: the programme's name is not a tier claim",
}


UNATTRIBUTED = 'unattributed'
UNATTRIBUTED_IDENTICAL = 'unattributed: classifier output changed on identical inputs'


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def changed_inputs(stored_expectation, current_expectation) -> list:
    """
    The expectation fields that differ between the row as last scored
    (soa_expectation_outcomes.expected_answer) and the question as built
    now (soa_queries.expected_answer), compared as canonical JSON. Every
    field, attributed_to included.
    """
    if not isinstance(current_expectation, dict) or not isinstance(stored_expectation, dict):
        return [] if _canonical(stored_expectation) == _canonical(current_expectation) \
            else ['expected_answer']
    keys = sorted(set(stored_expectation) | set(current_expectation))
    return [f'expected_answer.{k}' for k in keys
            if _canonical(stored_expectation.get(k)) != _canonical(current_expectation.get(k))]


def rule_for(verdict, expectation, answer_status=None, *, current_expectation) -> str:
    """
    The 2B rule that produced this verdict, for the before/after list.

    When no named rule fired the move is `unattributed`, and says whether
    the inputs differ. It never guesses: the fallback once read "an input
    did" on rows whose inputs were byte-identical, which is how a
    classifier regression (WIG_171, runs 10758/10759) nearly got written.
    Any unattributed move makes the real run refuse to write.
    """
    if verdict.reason_code in RULES:
        return RULES[verdict.reason_code]
    if answer_status in ('no_ai_answer', 'sign_in_wall', 'blocked'):
        return '§4: a wall or empty consumer answer is absent'
    if expectation.get('attributed_to'):
        return '§2: retailer_price scored against the attributed page'
    if verdict.outcome == 'partial':
        return ('§3 rule 4: whole-dollar member price within 50 cents'
                if expectation.get('type') == 'member_price'
                else '§3 rule 1: whole-dollar within 50 cents')
    changed = changed_inputs(expectation, current_expectation)
    if not changed:
        return UNATTRIBUTED_IDENTICAL
    return f"{UNATTRIBUTED}: no named rule fired; inputs differ: {', '.join(changed)}"


def stored_rows(conn, cid: int, tiers) -> list:
    statement = text("""
        SELECT o.run_id, o.query_id, o.cycle_id, o.platform, o.tier,
               o.expected_answer, o.extraction, o.extraction_model, o.outcome,
               r.retrieved_sources, r.grounding, r.surface, r.answer_status, r.run_number,
               q.source_ref, q.study_type, q.query_code,
               q.expected_answer AS query_expected_answer
        FROM soa_expectation_outcomes o
        JOIN soa_runs r ON r.id = o.run_id
        JOIN soa_queries q ON q.id = r.query_id
        WHERE o.cycle_id = :cid AND (o.tier IN :tiers OR o.tier IS NULL)
        ORDER BY o.run_id
    """).bindparams(bindparam("tiers", expanding=True))
    return conn.execute(statement, {"cid": cid, "tiers": list(tiers)}).mappings().all()


def _as_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _signature(verdict) -> str:
    """Everything a re-score writes, as one comparable string."""
    return json.dumps({
        'outcome': verdict.outcome, 'reason': verdict.reason,
        'matched_published_at': verdict.matched_published_at,
        'source_attribution': verdict.source_attribution,
        'domain_cited': verdict.domain_cited, 'near_miss': verdict.near_miss,
        'secondary': verdict.secondary, 'flags': verdict.flags, 'claims': verdict.claims,
        'source_split': verdict.source_split, 'reason_code': verdict.reason_code,
    }, sort_keys=True, default=str)


def classify_only(cycle_code: str, tiers=None, *, scorer=None, write: bool = True) -> dict:
    """
    Re-classify a cycle's stored outcomes. Returns
    {'cid', 'rows', 'moved': [(run_id, query_code, platform, run_number,
    before, after, rule)], 'unattributed': [the moved entries no named rule
    explains], 'deterministic': bool, 'written': bool, 'skipped': [...]}.

    Nothing is written unless both passes agree AND every move is
    attributed to a named rule.

    `scorer` supplies the caches (history, brand facts, references,
    domain checker) and the writer; an ExpectationScorer with a client
    that is never called. Its extraction client is NOT used: nothing here
    reaches a model.
    """
    from types import SimpleNamespace

    from scoring.expectation_scorer import ExpectationScorer, classify

    tiers = tiers or [t for t in QUERY_TIERS]
    scorer = scorer or ExpectationScorer(client=_NoModel(), labeler=False)

    with engine.connect() as conn:
        cid = cycle_id(conn, cycle_code)
        rows = stored_rows(conn, cid, tiers)

    plan, skipped = [], []
    for row in rows:
        expectation = _as_json(row['expected_answer'])
        extraction = _as_json(row['extraction'])
        if not isinstance(expectation, dict) or not isinstance(extraction, dict):
            skipped.append(row['run_id'])
            continue
        run = SimpleNamespace(
            id=row['run_id'], query_id=row['query_id'], cycle_id=row['cycle_id'],
            platform=row['platform'], tier=row['tier'], source_ref=row['source_ref'],
            study_type=row['study_type'], retrieved_sources=row['retrieved_sources'],
            grounding=row['grounding'],
            surface=row['surface'], answer_status=row['answer_status'],
        )
        kwargs = dict(history=scorer.history, brand_facts=scorer.brand_facts,
                      references=scorer.references, domain_checker=scorer.domain_checker,
                      tenant_domains=getattr(scorer, 'tenant_domains', None))
        first = classify(run, expectation, extraction, **kwargs)
        second = classify(run, expectation, extraction, **kwargs)
        plan.append((row, run, expectation, extraction, first, second))

    deterministic = all(_signature(a) == _signature(b) for *_rest, a, b in plan)
    moved = []
    for row, run, expectation, extraction, verdict, _again in plan:
        if verdict.outcome != row['outcome']:
            moved.append((row['run_id'], row['query_code'], row['platform'], row['run_number'],
                          row['outcome'], verdict.outcome,
                          rule_for(verdict, expectation, row['answer_status'],
                                   current_expectation=_as_json(row['query_expected_answer']))))
    unattributed = [m for m in moved if m[-1].startswith(UNATTRIBUTED)]

    written = bool(write and deterministic and not unattributed)
    if written:
        for row, run, expectation, extraction, verdict, _again in plan:
            scorer._store(run=run, expectation=expectation, extraction=extraction,
                          verdict=verdict, model=row['extraction_model'])

    return {'cid': cid, 'rows': len(plan), 'moved': moved, 'unattributed': unattributed,
            'deterministic': deterministic, 'written': written, 'skipped': skipped}


class _NoModel:
    """The extraction client classify-only hands the scorer. Calling it is
    a bug, and says so."""

    async def extract(self, *_args, **_kwargs):
        raise RuntimeError("classify-only must not call the extraction model")


def _main_classify_only(args) -> int:
    with engine.connect() as conn:
        cid = cycle_id(conn, args.cycle)
        before = outcome_counts(conn, cid)
    print(f"cycle {args.cycle} (id {cid}) — classify-only: no model call; Layer 1 "
          f"and the stored Layer 2 extraction are read as they are")
    print("before:")
    print(_render(before))
    result = classify_only(args.cycle, args.tiers, write=not args.dry_run)
    if not result['deterministic']:
        print("\nPROBLEM: two classification passes over the same stored rows "
              "disagreed. Nothing was written.")
        return 1
    print(f"\nclassified {result['rows']} stored row(s) twice; both passes agree")
    if result['skipped']:
        print(f"skipped (no stored expectation or extraction): {result['skipped']}")
    print(f"\nrows whose outcome moved: {len(result['moved'])} of {result['rows']}")
    for run_id, code, platform, number, was, now, rule in result['moved']:
        print(f"    {code} · {platform} · run {number}: {was} -> {now}   [{rule}]   [run {run_id}]")
    unattributed = result.get('unattributed') or []
    print(f"\nunattributed moves: {len(unattributed)}")
    for run_id, code, platform, number, was, now, rule in unattributed:
        print(f"    {code} · {platform} · run {number}: {was} -> {now}   [{rule}]   [run {run_id}]")
    if args.dry_run:
        if unattributed:
            print("a real run would REFUSE to write while these remain.")
        print("\ndry run — nothing written.")
        return 0
    if unattributed:
        print("\nREFUSED: no named rule explains the moves above. Nothing was written. "
              "Find the cause (a classifier change, or the input named) before re-running.")
        return 1
    with engine.connect() as conn:
        after = outcome_counts(conn, cid)
    print("after:")
    print(_render(after))
    return 0


# ─── 2J-4: refresh the cycle's cached reference ────────────────────────────

#: the cell fields a refresh diffs, per variant x retailer
REFERENCE_FIELDS = ('price', 'method', 'read_status', 'verifiable', 'reference_source')


def _iso(value):
    """A stored timestamp as ISO 8601, UTC when the column hands it back
    naive (sqlite's text), as supply is asked for it."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _sha256(raw) -> str:
    return hashlib.sha256((raw or '').encode('utf-8')).hexdigest()


def stored_reference(conn, cycle_code: str) -> dict:
    """The cycle's cached retailer-prices: the stored text exactly as the
    column holds it (`raw`, what a backup keeps and a restore writes back),
    parsed (`payload`), its as_of and the merchant it was read for."""
    row = conn.execute(text("""
        SELECT id, cycle_code, study_type, CAST(reference_prices AS TEXT) AS raw, reference_as_of
        FROM soa_cycles WHERE cycle_code = :code
    """), {"code": cycle_code}).mappings().fetchone()
    if not row:
        raise SystemExit(f"no cycle with code {cycle_code!r}")
    payload = _as_json(row['raw']) if row['raw'] else None
    merchant = (payload or {}).get('merchant')
    if not merchant:
        counts = Counter()
        for (ref,) in conn.execute(text("""
            SELECT q.source_ref FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
            WHERE r.cycle_id = :cid
        """), {"cid": row['id']}):
            slug = (_as_json(ref) or {}).get('merchant_slug')
            if slug:
                counts[slug] += 1
        merchant = counts.most_common(1)[0][0] if counts else None
    return {'cid': row['id'], 'cycle_code': row['cycle_code'], 'study_type': row['study_type'],
            'raw': row['raw'], 'payload': payload, 'merchant': merchant,
            'as_of': _iso(row['reference_as_of']) or (payload or {}).get('as_of')}


def _cell_key(row: dict) -> tuple:
    from scoring.retailer_reference import gtin14
    variant = row.get('variant_label') or row.get('variant_ref') or gtin14(row.get('gtin')) or row.get('sku')
    domain = ea.normalize_domain(row.get('retailer_domain'))
    # a retailer's row is the default; the brand's own page and a
    # comparison page (2A-4) say so
    role = row.get('role') if row.get('role') not in (None, 'retailer') else ''
    return (str(variant), domain, role)


def reference_diff(before: Optional[dict], after: Optional[dict]) -> list:
    """Every (variant, retailer, field, was, now) that differs between two
    retailer-prices payloads, cell by cell. A cell only one side has is
    one entry, field `(cell)`."""
    index = lambda p: {_cell_key(r): r for r in (p or {}).get('prices') or [] if isinstance(r, dict)}  # noqa: E731
    was, now = index(before), index(after)
    out = []
    for key in sorted(set(was) | set(now), key=lambda k: tuple(str(x) for x in k)):
        variant, domain = key[0] + (f" ({key[2]})" if key[2] else ''), key[1]
        a, b = was.get(key), now.get(key)
        if a is None or b is None:
            out.append((variant, domain, '(cell)', 'absent' if a is None else 'present',
                        'absent' if b is None else 'present'))
            continue
        for field in REFERENCE_FIELDS:
            if a.get(field) != b.get(field):
                out.append((variant, domain, field, a.get(field), b.get(field)))
    return out


def _render_reference_diff(diff: list) -> str:
    if not diff:
        return '    (no cell differs)'
    head = ('variant', 'retailer', 'field', 'cached', 'supply now')
    body = [tuple('null' if v is None else str(v) for v in row) for row in diff]
    widths = [max(len(r[i]) for r in [head] + body) for i in range(5)]
    line = lambda r: '    ' + '  '.join(c.ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return '\n'.join([line(head), line(tuple('-' * w for w in widths))] + [line(r) for r in body])


def transitions(moved: list, tiers_of: dict) -> dict:
    """{tier: Counter((was, now))} from classify_only's moved rows."""
    out = {}
    for run_id, _code, _p, _n, was, now, _rule in moved:
        out.setdefault(tiers_of.get(run_id) or '(untiered)', Counter())[(was, now)] += 1
    return out


def _render_transitions(by_tier: dict) -> str:
    lines = [f"    {tier:<20} {was} -> {now}: {n}"
             for tier in sorted(by_tier) for (was, now), n in sorted(by_tier[tier].items())]
    return '\n'.join(lines) or '    (no row would move)'


def projected(before: dict, moved: list, tiers_of: dict) -> dict:
    after = {tier: Counter(c) for tier, c in before.items()}
    for run_id, _code, _p, _n, was, now, _rule in moved:
        tier = tiers_of.get(run_id) or '(untiered)'
        after.setdefault(tier, Counter())[was] -= 1
        after[tier][now] += 1
    return {t: Counter({o: n for o, n in c.items() if n}) for t, c in after.items()}


def envelope(payload: dict, *, previous_raw, now: datetime) -> dict:
    """Supply's payload as fetched, with the refresh recorded beside it:
    `refreshed_at` and `previous_sha256` (the replaced text's). No column,
    so no migration; the console's score reads `refreshed_at` to recompute."""
    return {**payload, 'refreshed_at': now.isoformat(), 'previous_sha256': _sha256(previous_raw)}


def fetch_reference(cycle: dict, client=None) -> dict:
    """supply's retailer-prices for the cycle's merchant AS OF THE CYCLE'S
    STORED as_of, never now: the corrected reads of the same run. The
    client is the one the cycle's first scoring read through
    (ReferenceCache: the study's customer token)."""
    from clients.truesync_catalog import TrueSyncCatalogClient
    client = client or TrueSyncCatalogClient.for_study(cycle['study_type'])
    payload, error = client.retailer_prices(cycle['merchant'], as_of=cycle['as_of'])
    if error is not None or not isinstance(payload, dict):
        raise SystemExit(f"REFUSED: supply's retailer-prices for {cycle['merchant']} as of "
                         f"{cycle['as_of']} failed ({error}). Nothing was written.")
    return payload


def _plan(cycle_code: str, cid: int, payload: dict, tiers, scorer_factory) -> dict:
    """classify_only's plan against `payload`, writing nothing."""
    scorer = scorer_factory()
    scorer.references.with_payload(cid, payload)
    return classify_only(cycle_code, tiers, scorer=scorer, write=False)


def _default_scorer():
    from scoring.expectation_scorer import ExpectationScorer
    return ExpectationScorer(client=_NoModel(), labeler=False)


def _replace_reference(cid: int, raw: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :id"),
                     {"p": raw, "id": cid})


def _swap(cycle: dict, new_payload: dict, new_raw_for_write, *, tiers, write: bool, scorer_factory,
          before_write=None, label: str) -> dict:
    """The shared half of a refresh and a restore: diff, plan, print, and
    (when `write`) replace the payload and re-classify. `new_raw_for_write`
    is called only when writing; `before_write` runs first (the backup)."""
    print(f"cycle {cycle['cycle_code']} (id {cycle['cid']}) — {label}: merchant {cycle['merchant']}, "
          f"as of {cycle['as_of']}; no model call")
    diff = reference_diff(cycle['payload'], new_payload)
    print(f"\nreference cells that differ: {len({(d[0], d[1]) for d in diff})}")
    print(_render_reference_diff(diff))

    with engine.connect() as conn:
        before = outcome_counts(conn, cycle['cid'])
        tiers_of = {rid: v[3] for rid, v in row_outcomes(conn, cycle['cid']).items()}
    baseline = classify_only(cycle['cycle_code'], tiers, scorer=scorer_factory(), write=False)
    plan = _plan(cycle['cycle_code'], cycle['cid'], new_payload, tiers, scorer_factory)
    by_tier = transitions(plan['moved'], tiers_of)
    print("\noutcomes before:")
    print(_render(before))
    print("outcomes after (planned):")
    print(_render(projected(before, plan['moved'], tiers_of)))
    print("\nmoves, per tier:")
    print(_render_transitions(by_tier))
    print(f"\nrows whose outcome would move: {len(plan['moved'])} of {plan['rows']}")
    for run_id, code, platform, number, was, now, rule in plan['moved']:
        print(f"    {code} · {platform} · run {number}: {was} -> {now}   [{rule}]   [run {run_id}]")
    if baseline['moved']:
        print(f"\nof which {len(baseline['moved'])} would move on the CACHED reference too (a classifier "
              f"change since the last classify-only); they are written with the rest")
    result = {'diff': diff, 'moved': plan['moved'], 'by_tier': by_tier, 'written': False}
    if not plan['deterministic']:
        print("\nREFUSED: two classification passes disagreed. Nothing was written.")
        return {**result, 'refused': 'nondeterministic'}
    if plan['unattributed']:
        print(f"\nREFUSED: {len(plan['unattributed'])} move(s) no named rule explains. Nothing was written.")
        return {**result, 'refused': 'unattributed'}
    if not diff:
        print("\nno cell differs: nothing to write.")
        return result
    if not write:
        print("\ndry run — nothing written.")
        return result

    if before_write:
        before_write()
    _replace_reference(cycle['cid'], new_raw_for_write())
    done = classify_only(cycle['cycle_code'], tiers, scorer=scorer_factory(), write=True)
    if not done['written']:
        print("\nPROBLEM: the reference was replaced but the re-classify did not write "
              "(see above). Put the previous one back with --restore.")
        return {**result, 'refused': 'rescore_not_written'}
    with engine.connect() as conn:
        after = outcome_counts(conn, cycle['cid'])
    print(f"\nwritten: reference replaced; {len(done['moved'])} row(s) moved")
    for run_id, code, platform, number, was, now, rule in done['moved']:
        print(f"    {code} · {platform} · run {number}: {was} -> {now}   [{rule}]   [run {run_id}]")
    print("after:")
    print(_render(after))
    print("\nthe console's stored score recomputes on its next read ('cycle reference refreshed').")
    return {**result, 'written': True, 'moved_written': done['moved']}


def refresh_reference(cycle_code: str, *, backup: Optional[str], write: bool = True, tiers=None,
                      client=None, scorer_factory=None, now: Optional[datetime] = None) -> dict:
    """
    2J-4: re-read the cycle's retailer-prices from supply as of its stored
    as_of, diff it against the cached copy, and (when `write`) back the
    cached copy up to `backup`, replace it, and re-classify.

    The stale rule is untouched: `stale_basis` reads the PREVIOUS cycle's
    cached rows, which this does not refresh. Refreshing cycle N does not
    change what cycle N+1 considers stale unless N+1 is refreshed and
    re-classified too (the same flag, on N+1).
    """
    scorer_factory = scorer_factory or _default_scorer
    if write:
        _check_new_backup(backup)
    with engine.connect() as conn:
        cycle = stored_reference(conn, cycle_code)
    if cycle['payload'] is None:
        raise SystemExit(f"REFUSED: {cycle_code} has no cached reference to refresh; a plain "
                         f"re-score reads one. Nothing was written.")
    if not cycle['merchant'] or not cycle['as_of']:
        raise SystemExit(f"REFUSED: {cycle_code}'s cached reference names no merchant or as_of. "
                         f"Nothing was written.")
    fetched = fetch_reference(cycle, client)
    stamp = now or datetime.now(timezone.utc)
    new_raw = json.dumps(envelope(fetched, previous_raw=cycle['raw'], now=stamp))

    def write_backup():
        with open(backup, 'x') as fh:
            json.dump({'cycle_code': cycle['cycle_code'], 'cycle_id': cycle['cid'],
                       'merchant': cycle['merchant'], 'reference_as_of': cycle['as_of'],
                       'reference_prices_raw': cycle['raw'], 'sha256': _sha256(cycle['raw']),
                       'replaced_by_sha256': _sha256(new_raw), 'written_at': stamp.isoformat()},
                      fh, indent=2)
        print(f"\nbackup written: {backup}")

    return _swap(cycle, fetched, lambda: new_raw, tiers=tiers, write=write, scorer_factory=scorer_factory,
                 before_write=write_backup, label='refresh reference')


def restore_reference(cycle_code: str, backup: str, *, write: bool = True, tiers=None,
                      scorer_factory=None) -> dict:
    """Put a --refresh-reference backup back, byte for byte, and
    re-classify. Refuses a backup of another cycle, and a cycle whose
    reference changed since the refresh that wrote the backup."""
    scorer_factory = scorer_factory or _default_scorer
    if not backup or not os.path.exists(backup):
        raise SystemExit(f"REFUSED: no backup at {backup!r}. Nothing was written.")
    with open(backup) as fh:
        saved = json.load(fh)
    with engine.connect() as conn:
        cycle = stored_reference(conn, cycle_code)
    if saved.get('cycle_code') != cycle['cycle_code'] or saved.get('cycle_id') != cycle['cid']:
        raise SystemExit(f"REFUSED: {backup} is a backup of {saved.get('cycle_code')!r} "
                         f"(id {saved.get('cycle_id')}), not {cycle_code}. Nothing was written.")
    if _sha256(cycle['raw']) != saved.get('replaced_by_sha256'):
        raise SystemExit(f"REFUSED: {cycle_code}'s reference changed since this backup's refresh "
                         f"(sha256 {_sha256(cycle['raw'])[:12]}, expected "
                         f"{str(saved.get('replaced_by_sha256'))[:12]}). Nothing was written.")
    raw = saved['reference_prices_raw']
    return _swap(cycle, _as_json(raw), lambda: raw, tiers=tiers, write=write,
                 scorer_factory=scorer_factory, label=f'restore reference from {backup}')


def _check_new_backup(backup) -> None:
    if not backup:
        raise SystemExit("REFUSED: --refresh-reference without --dry-run needs --backup <path>. "
                         "Nothing was written.")
    if os.path.exists(backup):
        raise SystemExit(f"REFUSED: {backup} exists; a backup is never overwritten. Nothing was written.")


def _main_reference(args) -> int:
    if args.restore:
        result = restore_reference(args.cycle, args.restore, write=not args.dry_run, tiers=args.tiers)
    else:
        result = refresh_reference(args.cycle, backup=args.backup, write=not args.dry_run, tiers=args.tiers)
    return 1 if result.get('refused') else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-score one or more tiers of a cycle, in place.",
    )
    parser.add_argument("--cycle", required=True, help="cycle_code, not id")
    parser.add_argument(
        "--tier", action="append", dest="tiers", choices=QUERY_TIERS,
        help="repeatable; omit to re-score every scoreable tier",
    )
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the plan and the current counts; no model call, no write",
    )
    parser.add_argument(
        "--expect-unchanged", action="append", dest="expect_unchanged",
        default=[], metavar="TIER",
        help=(
            "repeatable; fail if this tier's PRIMARY outcome counts move. "
            "Secondary results are not covered — a correction can be meant "
            "to move a pack-count secondary while leaving the price "
            "outcome it rides on exactly where it was, and that is a "
            "distinction worth being able to assert."
        ),
    )
    parser.add_argument(
        "--classify-only", action="store_true",
        help=(
            "re-run only the deterministic classifier over the STORED "
            "extraction; no model call (2B). With --dry-run, prints what "
            "would move and writes nothing."
        ),
    )
    parser.add_argument(
        "--refresh-reference", action="store_true",
        help=(
            "2J-4, with --classify-only: re-read supply's retailer-prices for the "
            "cycle's merchant as of the cycle's STORED reference_as_of (never now), "
            "print the cell-by-cell diff against the cached copy and the price "
            "outcomes that would move, then (without --dry-run) back the cached "
            "copy up to --backup, replace it and re-classify. The previous "
            "cycle's cached rows, which `stale` reads, are not refreshed."
        ),
    )
    parser.add_argument(
        "--backup", metavar="PATH",
        help="with --refresh-reference: where the replaced copy is written; required "
             "without --dry-run, and never overwritten",
    )
    parser.add_argument(
        "--restore", metavar="BACKUP",
        help="with --classify-only: put a --refresh-reference backup back, byte for "
             "byte, and re-classify; refused for another cycle's backup or a cycle "
             "whose reference changed since",
    )
    args = parser.parse_args(argv)

    if args.refresh_reference or args.restore:
        if not args.classify_only:
            parser.error("--refresh-reference and --restore run with --classify-only")
        if args.refresh_reference and args.restore:
            parser.error("--refresh-reference and --restore are one or the other")
        return _main_reference(args)
    if args.backup:
        parser.error("--backup goes with --refresh-reference")

    if args.classify_only:
        return _main_classify_only(args)

    tiers = args.tiers or [t for t in QUERY_TIERS if t not in NO_EXPECTATION_TIERS]

    with engine.connect() as conn:
        cid = cycle_id(conn, args.cycle)
        before = outcome_counts(conn, cid)
        before_secondary = secondary_counts(conn, cid)
        before_rows = row_outcomes(conn, cid)
        run_ids = run_ids_for(conn, cid, tiers)

    print(f"cycle {args.cycle} (id {cid})")
    print(f"re-scoring tiers: {', '.join(tiers)}")
    print(f"runs to score:    {len(run_ids)}")
    print("before:")
    print(_render(before))
    print("before (secondary):")
    print(_render_secondary(before_secondary))

    if not run_ids:
        print("\nnothing to do.")
        return 0

    if args.dry_run:
        print(f"\ndry run — no model calls, no writes. "
              f"A real run costs {len(run_ids)} extraction calls.")
        return 0

    if not os.getenv("OPEN_AI_API_KEY"):
        raise SystemExit("OPEN_AI_API_KEY is not set — extraction cannot run")

    from scoring.expectation_batch import score_runs

    summary = asyncio.run(score_runs(run_ids, concurrency=args.concurrency))

    with engine.connect() as conn:
        after = outcome_counts(conn, cid)
        after_secondary = secondary_counts(conn, cid)
        after_rows = row_outcomes(conn, cid)

    print(f"\nscored {summary.succeeded}/{summary.total} "
          f"(skipped {summary.skipped}, failed {summary.failed}, "
          f"retried {summary.retried})")
    print("after:")
    print(_render(after))
    print("after (secondary):")
    print(_render_secondary(after_secondary))

    moved_primary = changed_tiers(before, after)
    print(f"\nprimary outcomes changed in: "
          f"{', '.join(moved_primary) if moved_primary else 'nothing'}")

    moved_rows = row_diff(before_rows, after_rows)
    print(f"\nrows whose outcome moved: {len(moved_rows)} of {len(after_rows)}")
    print(_render_rows(moved_rows))

    for failure in summary.failures[:10]:
        print(f"    FAILED run {failure.run_id}: {failure.status} "
              f"{failure.error_message or ''}")

    problems = []

    moved = diff_untouched(before, after, set(tiers))
    if moved:
        problems.append(
            f"{', '.join(moved)} changed and {'was' if len(moved) == 1 else 'were'} "
            f"not re-scored. A re-score of one tier must leave the others alone."
        )

    # Asserted rather than eyeballed. "The price outcomes did not move" is
    # a claim somebody is going to put in a report, and it should be
    # checked by the thing that did the re-scoring.
    broke_promise = [t for t in args.expect_unchanged if t in moved_primary]
    if broke_promise:
        problems.append(
            f"{', '.join(broke_promise)} was expected to be unchanged and "
            f"its primary outcomes moved."
        )

    for problem in problems:
        print(f"\nPROBLEM: {problem}")
    if problems:
        return 1

    if args.expect_unchanged:
        print(f"unchanged, as promised: {', '.join(sorted(args.expect_unchanged))}")
    untouched = sorted(set(before) - set(tiers))
    if untouched:
        print(f"unchanged, not re-scored: {', '.join(untouched)}")
    return 0 if not summary.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
