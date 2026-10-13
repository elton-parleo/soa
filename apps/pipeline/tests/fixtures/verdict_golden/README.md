# Verdict golden set (2B)

The extraction golden set (`../extraction_golden/`) grades Layer 2's
*fields* over stored transcriptions; its rows carry no expectation, so no
verdict there can move. This set grades the deterministic classifier's
*verdicts* — one row per 2B rule, plus guard rows that must not move.

Each row stores the expectation, the `source_ref`, the stored extraction, and:

- `verdict_before` — computed with `main`'s comparator (the classifier as it
  stood before 2B, `git show main:apps/pipeline/scoring/expectation_comparator.py`)
  over the same inputs, with the arguments it accepted then;
- `verdict_after` — this branch's classifier, with the record's variants (the
  W&S catalog fixture, or the row's own `catalog`) and, for `§2` rows, the
  recorded retailer-prices fixtures;
- `attribution: claude-reviewed, elton-pending` — every row awaits Elton's
  hand-check. None is a re-label of an existing golden row.

Sources: W&S rows use `../wiggle_and_snug_catalog.json`; engine rows take the
example named in parleohq/truesync console-demo `services/engine/src/checks.ts`;
`acme-baby` and `fictional-toothbrush-co` are fictional. No customer data.

    python3 scripts/eval_verdict_golden.py          # the before/after table
    python3 scripts/eval_verdict_golden.py --gate   # fail if any `after` moved

The gate compares outcome, flags and reason code: the same outcome reached by a
different rule is a moved verdict. r17 and r18 are WIG_171 runs 10758 and 10759
(cycle 20260915-113207-wiggle-snug-full; W&S is Parleo's own test store), kept
`absent` because their member prices name another tier and another product; r19
is their list-price twin.
