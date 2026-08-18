# `feat/transcript-narrative-testing` — testing the transcript's narrative boxes

This branch exists to test the accuracy of the "From the transcript"
widget's WHAT WENT RIGHT / WHAT LEAKED clause logic
([`app/services/transcript_pick.py`](../apps/api/app/services/transcript_pick.py))
before it ships on the main feature branch. It is otherwise identical
to `feat/transcript-widget` — see that branch for the transcript
section itself (question, verbatim answer, highlights, expander,
provenance), which always ships regardless of this flag.

## The flag

`TRANSCRIPT_NARRATIVE_ENABLED` ([`soa_shared/config.py`](../apps/api/soa_shared/config.py)):

| Branch | Default |
|---|---|
| `feat/transcript-widget` (main feature branch) | `false` — boxes hidden |
| `feat/transcript-narrative-testing` (this branch) | `true` — boxes shown |

That one-line default flip is the *only* intentional diff between the
two branches, so a clause-logic fix landed here merges straight back
to the main branch without conflict. With the flag off,
`select_transcript` still selects the transcript and computes spans/
highlights — only the payload's `right`/`leaked` fields are omitted
(never empty strings); `narrative_case`/`selection_tier` stay present
for diagnostics either way.

## Outstanding work

The clause-accuracy fixes this branch exists to test are the ones
described in `claude-code-prompt-transcript-dtc-fix.md`:

- **SELF vs THIRD_PARTY attribution via entity_id** — the observation's
  `entity_id` needs to be checked against the primary brand's own
  entity id before a price is read as "off-site," not inferred from
  domain/merchant-name text matching alone.
- **Domain-aware self resolution** — a price quoted from the brand's
  own domain (its storefront's own hostname) must resolve to SELF
  attribution, not THIRD_PARTY, even when the merchant name string
  doesn't literally match the brand name.
- **Brand-named-in-query gating on the "unprompted" clause** — WHAT
  WENT RIGHT's "named unprompted" phrasing must not fire when the
  brand's own name was already in the query text (the agent naming a
  brand the user just asked about isn't unprompted).

### Known-bad regression case

Report token **`eccd7fb8dc394bb58a3f5d99ee5c3a0f`** reproduces both
known issues (brand-named-query "unprompted" misfire, and a brand's
own domain read as a third-party price source) — use it as the
regression fixture when landing the fixes above.
