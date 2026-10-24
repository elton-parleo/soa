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

It costs one extraction call per run for every tier but brand-direct.
2O-4: a brand-direct answer costs none. Its claim sentences are selected by
rule from the answer text (scoring/brand_claim_selector.py) and each is
looked up in the brand's fact index (2O-3's verdict), so two runs over the
same answers give the same outcomes, and --dry-run prints for brand-direct
exactly what the real run prints, and writes nothing: the outcomes after,
the rows that would move, and the brand-direct block (the fact index's size
by source, the claim sentences selected, per answer min / median / max,
the no_checkable_fact answers, and "claim sets changed since the stored
scoring: N of M", the second run's check that nothing moved). With only
brand_direct named, neither run needs OPEN_AI_API_KEY. 2O-5: and the index's
slots (lines, sizes and counts per line, ranges per size), the split with
`unverified` apart from unscoreable, fabricated by the slot contradicted and
unverified by the fact type left unverified.

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

--narratives (2L-3) rewrites the cycle's console narratives from what is
stored (soa_shared/narratives.py): two model calls per flagged answer and per
product row, each line checked against its facts before it is stored, and
the template shown for any that fails. Nothing is re-scored. --dry-run calls
the model and prints every line, and stores nothing:

    python3 scripts/rescore_cycle.py --cycle <code> --narratives --dry-run
    python3 scripts/rescore_cycle.py --cycle <code> --narratives

The console's stored score recomputes on its next read: `refreshed_at`
differs from the one the stored score was computed on (console_score.
needs_recompute, 'cycle reference refreshed'). 2N-2: a re-score with no
refresh recomputes it too, the outcomes' scored_at being newer than the
score ('outcomes re-scored').
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
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


# ─── 2O-4: the brand-direct claims, selected by rule ─────────────────────

def selection_report(rows) -> dict:
    """What the brand-direct verdict decided on, from each row's (extraction,
    outcome, reason_code): answers selected by rule (coder version 4), the
    claim sentences (total, per answer), their kinds, the no_checkable_fact
    and fact_type_not_read answers, the missing facts by type, and the fact
    index each was judged against (version, digest, size, by source).
    2O-5: the split as the console reads it (unverified apart from
    unscoreable), the fabricated answers by the slot contradicted, the
    unverified answers by the fact types left unverified, and the slots of
    the last index stamped."""
    out = {'answers': 0, 'claims': 0, 'per_answer': [], 'kinds': Counter(), 'no_checkable_fact': 0,
           'fact_type_not_read': 0, 'missing_by_type': Counter(), 'indexes': Counter(), 'split': Counter(),
           'unverified': 0, 'contradicted_by_slot': Counter(), 'unverified_by_type': Counter(), 'slots': None}
    for extraction, outcome, reason_code in rows:
        if not isinstance(extraction, dict) or 'selector' not in extraction:
            continue
        out['answers'] += 1
        out['split'][ea.UNVERIFIED if outcome == 'unscoreable' and reason_code == ea.UNVERIFIED else outcome] += 1
        claim = extraction.get('brand_claim') or {}
        spans = claim.get('spans') or []
        out['claims'] += len(spans)
        out['per_answer'].append(len(spans))
        for span in spans:
            out['kinds'][span.get('kind')] += 1
        if outcome == 'unscoreable' and reason_code in ('no_checkable_fact', 'fact_type_not_read'):
            out[reason_code] += 1
        decided = claim.get('decided_by')
        deciding = spans[decided] if isinstance(decided, int) and decided < len(spans) else {}
        if outcome == 'fabricated':
            for fact in deciding.get('facts_missing') or []:
                out['missing_by_type'][fact.get('type')] += 1
                out['contradicted_by_slot'][fact.get('slot') or 'missing (2O-4)'] += 1
        if outcome == 'unscoreable' and reason_code == ea.UNVERIFIED:
            out['unverified'] += 1
            for kind in sorted({f.get('type') for f in deciding.get('facts_unverified') or []}):
                out['unverified_by_type'][kind] += 1
        index = claim.get('index') or {}
        if index:
            by = index.get('by_source') or {}
            out['indexes'][(index.get('version'), index.get('digest'), index.get('size'),
                            by.get('record'), by.get('catalog'), by.get('brand_pages'))] += 1
            if index.get('slots'):
                out['slots'] = index['slots']
    counts = sorted(out['per_answer'])
    out['min'], out['max'] = (counts[0], counts[-1]) if counts else (None, None)
    out['median'] = (counts[len(counts) // 2] if len(counts) % 2 else
                     (counts[len(counts) // 2 - 1] + counts[len(counts) // 2]) / 2) if counts else None
    out['no_checkable_fact_share'] = (round(out['no_checkable_fact'] / out['answers'], 3)
                                      if out['answers'] else None)
    return out


def _pairs(counts: dict) -> str:
    return ', '.join(f"{k} {n}" for k, n in counts.items()) or 'none'


def _render_slots(slots: Optional[dict]) -> list:
    """2O-5: the index's slots, as the printout's lines."""
    if not slots:
        return ['    index slots          none stamped (an index before 2O-5)']
    served = 'not served' if slots.get('brand_lines') is None else f"{slots['brand_lines']} lines"
    retired = ', '.join(slots.get('retired') or []) or 'none'
    complete = lambda key: ', '.join(slots.get(key) or []) or 'none'  # noqa: E731
    return [
        f"    index slots          lines {slots['lines']} (status known {slots['status']}, retired: {retired}; "
        f"the brand's line list {served})",
        f"      sizes per line     {_pairs(slots.get('sizes') or {})}  (complete: {complete('sizes_complete')})",
        f"      counts per line    {_pairs(slots.get('counts') or {})}  (complete: {complete('counts_complete')})",
        f"      ranges per size    {_pairs(slots.get('ranges_per_size') or {})}  (lines with a range for the size)",
        f"      attributes / line  {_pairs(slots.get('attributes') or {})}",
    ]


def _render_selection(report: dict, changed: dict) -> str:
    sets = (f"    claim sets changed since the stored scoring: {changed['changed']} of {changed['compared']}  "
            f"(answers both scorings decided on a claim set)")
    if not report['answers']:
        return '\n'.join(['    (no brand-direct answer selected by rule)', sets])
    indexes = '; '.join(
        f"{n} facts (record {r}, catalog {c}, brand pages {b}); v{v} {d}" + (f" x{k}" if len(report['indexes']) > 1 else '')
        for (v, d, n, r, c, b), k in sorted(report['indexes'].items(), key=str))
    kinds = ', '.join(f"{k} {n}" for k, n in sorted(report['kinds'].items(), key=lambda kv: str(kv[0])))
    missing = ', '.join(f"{k} {n}" for k, n in sorted(report['missing_by_type'].items())) or 'none'
    order = ['grounded', 'fabricated', 'misattributed', ea.UNVERIFIED, 'echoed', 'acknowledged_unknown', 'absent',
             'unscoreable']
    split = ', '.join(f"{o} {report['split'][o]}" for o in order if report['split'].get(o)) or 'none'
    median = report['median']
    median = int(median) if median is not None and float(median).is_integer() else median
    return '\n'.join([
        f"    fact index           {indexes or 'none stored'}",
        *_render_slots(report.get('slots')),
        f"    answers              {report['answers']}",
        f"    split                {split}  (unverified: {ea.UNVERIFIED_NOTE}; stored unscoreable, outside "
        f"the counts)",
        f"    claim sentences      {report['claims']}  (per answer: min {report['min']}, median {median}, "
        f"max {report['max']}; {kinds or 'none'})",
        f"    no_checkable_fact    {report['no_checkable_fact']}  ({report['no_checkable_fact_share']:.1%} of "
        f"answers; unscoreable, outside the counts)",
        f"    fact_type_not_read   {report['fact_type_not_read']}",
        f"    fabricated, by the fact missing: {missing}",
        f"    fabricated, by the slot contradicted: "
        f"{', '.join(f'{k} {n}' for k, n in sorted(report['contradicted_by_slot'].items())) or 'none'}",
        f"    unverified, by the fact left unverified: "
        f"{', '.join(f'{k} {n}' for k, n in sorted(report['unverified_by_type'].items())) or 'none'}",
        sets,
    ])


def claim_sets(rows) -> dict:
    """{run_id: the claim sentences a stored row was decided on} from
    (run_id, extraction) pairs: a version-4 row's selection, a version-3
    row's settling call's spans (brand_claim_selector.claim_set); rows with
    neither are left out."""
    from scoring import brand_claim_selector as sel
    out = {}
    for run_id, extraction in rows:
        claims = sel.claim_set(_as_json(extraction))
        if claims is not None:
            out[run_id] = claims
    return out


def claim_sets_changed(before: dict, after: dict) -> dict:
    """{compared, changed}: of the runs both scorings decided on a claim
    set, how many were decided on a different one (the same sentences, in
    the same order, whitespace aside, or not)."""
    def flat(claims):
        return [' '.join(str(c or '').split()) for c in claims]
    common = sorted(set(before) & set(after))
    return {'compared': len(common), 'changed': sum(1 for r in common if flat(before[r]) != flat(after[r]))}


def brand_direct_rows(conn, cid: int) -> list:
    """(run_id, extraction, outcome, reason_code) for the cycle's stored brand-direct rows."""
    rows = conn.execute(text("""
        SELECT run_id, extraction, outcome, reason_code FROM soa_expectation_outcomes
        WHERE cycle_id = :cid AND tier = 'brand_direct'
    """), {"cid": cid}).fetchall()
    return [(r[0], _as_json(r[1]), r[2], r[3]) for r in rows]


def print_brand_direct(before_rows, after_rows) -> None:
    """The brand-direct block, the same for the real run (rows read back) and
    the dry run (rows planned): see selection_report and claim_sets_changed."""
    changed = claim_sets_changed(claim_sets((r[0], r[1]) for r in before_rows),
                                 claim_sets((r[0], r[1]) for r in after_rows))
    print("\nbrand-direct claims (2O-4: selected by rule, no model call; 2O-5: fabricated is contradicted by "
          "the fact index, absent is unverified):")
    print(_render_selection(selection_report([r[1:] for r in after_rows]), changed))


def _brand_direct_scorer(*, fetch: bool = True):
    """2O-4: the scorer a brand-direct-only re-score uses: no model client
    (a call is a bug, and _NoModel says so) and no labeller. With
    fetch=False (the dry run) the cycle's cached reference is read and never
    fetched, since a fetch writes it."""
    from scoring.expectation_scorer import ExpectationScorer, ReferenceCache
    return ExpectationScorer(client=_NoModel(), labeler=False,
                             **({} if fetch else {'references': ReferenceCache(fetch=False)}))


def plan_brand_direct(run_ids, scorer=None) -> list:
    """2O-4: every brand-direct run decided as the real run decides it
    (ExpectationScorer.plan: the selection and the verdict, no model call)
    and nothing written: [(run_id, status, extraction as it would be stored,
    verdict)]. A run with nothing to store has no extraction."""
    from scoring.expectation_scorer import _with_brand_claim
    scorer = scorer or _brand_direct_scorer(fetch=False)
    out = []
    for run_id in run_ids:
        status, run, expectation, extraction, verdict, _model = scorer.plan(run_id)
        if status == 'needs_model':
            raise RuntimeError(f"run {run_id} is not brand-direct; only brand-direct is planned without a model")
        out.append((run_id, status, _with_brand_claim(extraction, verdict) if verdict else None, verdict))
    return out


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
    'coder_disagreed': 'brand-direct (2O-1): no two of the coder\'s calls agreed',
    'fact_not_published': "brand-direct (2O-3): a fact the claim states is not in the brand's fact index",
    'facts_published': "brand-direct (2O-3): every fact the claim states is in the brand's fact index",
    'no_checkable_fact': 'brand-direct (2O-3): the answer states no checkable fact about the brand',
    'fact_type_not_read': 'brand-direct (2O-3): its facts are of a type the cycle read nothing of',
    'fact_contradicted': "brand-direct (2O-5): a fact the claim states, the brand's pages state otherwise",
    ea.UNVERIFIED: "brand-direct (2O-5): facts not on the pages read, nothing contradicts them (unverified)",
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
               r.raw_response,
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
            # 2M-1: _store codes an attribute question's weight range from the answer text
            raw_response=row.get('raw_response'),
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


def _main_narratives(args, writer=None, log=print) -> int:
    """2L-3: --narratives. Every subject's line beside its facts' digest, the
    counts, the dropped lines and why, and the calls and tokens."""
    from soa_shared import narratives

    writer = writer or narratives.LiveWriter()
    with engine.connect() as conn:
        cid = cycle_id(conn, args.cycle)
        if not args.dry_run and not narratives.table_exists(conn):
            raise SystemExit(f"{narratives.TABLE} is missing (migration c8e2f4a6b1d3 not applied); "
                             "run with --dry-run to read the lines")
    log(f"cycle {args.cycle} (id {cid}), narratives, model {getattr(writer, 'model', '?')}"
        f"{' (dry run: the model is called, nothing is stored)' if args.dry_run else ''}")
    reports = narratives.write_cycle(engine, cid, writer, dry_run=args.dry_run, force=True, log=log)
    for r in sorted(reports, key=lambda r: r['subject']):
        log(f"  {r['subject']}  [{r['status']}{': ' + r['reason'] if r['reason'] else ''}]  {r['line'] or ''}")
        if r['status'] == 'dropped':
            # 2L-3a: what each call wrote, so a drop can be read (a line beside a null, or a failed check)
            for i, c in enumerate(r.get('calls') or [], 1):
                log(f"      call {i} [{c.get('check') or 'pass'}]  {c.get('line') or ''}")
    counts = {s: sum(1 for r in reports if r['status'] == s) for s in ('accepted', 'dropped', 'null')}
    totals = narratives.usage_totals(reports)
    log(f"accepted {counts['accepted']}, dropped {counts['dropped']}, null {counts['null']}; "
        f"{totals['calls']} calls, {totals['input_tokens']} input / {totals['output_tokens']} output tokens"
        f"{'' if args.dry_run else '; stored'}")
    from soa_shared import config
    cost = narratives.dollars(totals, getattr(writer, 'model', None))
    if cost is not None:
        price = config.SOA_CODING_MODEL_PRICE
        log(f"about ${cost:.4f} for this cycle at ${price['input']:.2f} / ${price['output']:.2f} per million "
            f"tokens (OpenAI's price as read on {price['as_of']}, unverified)")
    return 0


def _print_after(summary, before, after, after_secondary, before_rows, after_rows) -> list:
    """The lines after a re-score, the real run's and (2O-4) the dry run's
    for brand-direct alike. Returns the tiers whose primary counts moved."""
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
    return moved_primary


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
    parser.add_argument(
        "--narratives", action="store_true",
        help=(
            "2L-3: rewrite the cycle's console narratives (soa_shared/narratives.py) "
            "from the stored outcomes: two model calls per flagged answer and per "
            "product row, every line checked against its facts. Nothing is re-scored. "
            "With --dry-run, calls the model and prints the lines, and stores nothing."
        ),
    )
    args = parser.parse_args(argv)

    if args.narratives:
        if args.classify_only or args.refresh_reference or args.restore or args.backup or args.tiers:
            parser.error("--narratives runs on its own (with --dry-run or not)")
        return _main_narratives(args)

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

    with engine.connect() as conn:
        brand_ids = run_ids_for(conn, cid, ['brand_direct']) if 'brand_direct' in tiers else []
        before_brand = brand_direct_rows(conn, cid) if brand_ids else []
    other_ids = [r for r in run_ids if r not in set(brand_ids)]

    if args.dry_run:
        print(f"\ndry run — nothing written. Brand-direct is decided with no model call, so its "
              f"{len(brand_ids)} answer(s) are scored below exactly as the real run scores them; "
              f"the other tiers' {len(other_ids)} run(s) would cost one extraction call each "
              f"(an extraction and a labelling) and are not scored here.")
        if not brand_ids:
            return 0
        planned = plan_brand_direct(brand_ids)
        after_brand = [(run_id, extraction, verdict.outcome, verdict.reason_code)
                       for run_id, _status, extraction, verdict in planned if verdict is not None]
        after_rows = dict(before_rows)
        for run_id, _extraction, outcome, _code in after_brand:
            label = before_rows.get(run_id)
            if label:
                after_rows[run_id] = label[:4] + (outcome,)
        after = {t: Counter(c) for t, c in before.items() if t != 'brand_direct'}
        for run_id, _extraction, outcome, _code in after_brand:
            after.setdefault('brand_direct', Counter())[outcome] += 1
        summary = SimpleNamespace(
            succeeded=sum(1 for p in planned if p[1] == 'success'), total=len(planned),
            skipped=sum(1 for p in planned if p[1].startswith('skipped')), failed=0, retried=0, failures=[])
        _print_after(summary, before, after, before_secondary, before_rows, after_rows)
        print_brand_direct(before_brand, after_brand)
        return 0

    if other_ids and not os.getenv("OPEN_AI_API_KEY"):
        raise SystemExit("OPEN_AI_API_KEY is not set — extraction cannot run "
                         f"(the {len(other_ids)} run(s) outside brand-direct need it)")

    from scoring.expectation_batch import score_runs

    # 2O-4: brand-direct makes no model call, so its scorer never builds a client
    scorer = None if other_ids else _brand_direct_scorer()
    summary = asyncio.run(score_runs(run_ids, concurrency=args.concurrency,
                                     **({'scorer': scorer} if scorer else {})))

    with engine.connect() as conn:
        after = outcome_counts(conn, cid)
        after_secondary = secondary_counts(conn, cid)
        after_rows = row_outcomes(conn, cid)
        after_brand = brand_direct_rows(conn, cid) if brand_ids else []

    moved_primary = _print_after(summary, before, after, after_secondary, before_rows, after_rows)
    if brand_ids:
        print_brand_direct(before_brand, after_brand)

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
