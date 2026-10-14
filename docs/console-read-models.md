# Console read models (2B, 2C)

soa's results in the shapes the console reads (parleohq/truesync, branch
`console-demo`, `apps/console/src/data/types.ts` and `studio.ts`). The console
is the product UI from 2C-0 on; the soa web app's existing report endpoints are
untouched and stay linked from the console until they are ported.

Code: `apps/api/app/routers/console.py`, `apps/api/app/routers/full_loop.py`,
`apps/api/app/services/console_read_models.py` (every mapping), `apps/api/app/console_scope.py`
(tenancy). Shapes are tested against `apps/api/tests/fixtures/console/console_types.schema.json`,
a JSON Schema derived field by field from `types.ts` and `studio.ts`.

## Tenancy

Every endpoint is behind soa's own auth and scoped to one tenant, server-side; the
tenant token never reaches a browser.

| caller | reads |
|---|---|
| org member | their own org. `?org=<another org>` is **403**, never a quiet fallback |
| operator | any linked org with `?org=<org id>` (or the `X-Parleo-Customer` header) |

A cycle belongs to the customer its study was generated for
(`soa_query_generation_jobs.customer_organization_id`), falling back to the org that
created the cycle. A cycle outside the scope is a **404** worded like a missing one.
Lists (`runs`, `studio/*`) return only the scope's rows.

## Endpoints

| endpoint | returns | console type |
|---|---|---|
| `GET /api/console/surfaces` | the surface list the modal shows | — (soa) |
| `GET /api/console/answers?cycle=<code>` | one per run | `Answer[]` |
| `GET /api/console/answers/summary?cycle=<code>` | per tier and per surface: every outcome, `unverifiable`, `answered_with_other_brand` (2C) | — (soa) |
| `GET /api/console/true-value?cycle=<code>` | variants x retailers | `TrueValue` |
| `GET /api/console/accessibility?merchant=<slug>` | supply's access payload | `Accessibility` |
| `GET /api/console/studies?cycle=<code>` | question x agent | `StudyRow[]` |
| `GET /api/console/accuracy?cycle=<code>` | per-surface accuracy, never pooled | — (soa) |
| `GET /api/console/runs` | the tenant's cycles | `Run[]` (studio.ts) |
| `GET /api/console/studio/studies` | the tenant's studies with prompts | `Study[]` + `Prompt` (studio.ts) |
| `GET /api/console/studio/entities` | entities the tenant's cycles compare | `Entity[]` (studio.ts) |
| `GET /api/console/full-loop/{id}`, `GET /api/full-loop/{id}` | the full loop's combined status | — (soa) |
| `POST /api/full-loop` | queues a full loop for the worker (202 `{full_loop_id, status: 'queued'}`) | — (soa) |
| `GET /api/console/me` | who is signed in and the orgs they may select (2C-0) | — (the console's workspace switcher) |
| `GET /api/console/full-loop/latest` | the scope's most recent full loop, or `null` (2C-0) | — (soa) |

Extra fields ride **beside** the typed ones; a typed field is never bent to hold
something it does not mean. Optional typed fields (`field?: string`) are omitted,
never `null`.

## Mappings

### Answer

| console field | from |
|---|---|
| `id` | `run-<soa_runs.id>` |
| `agent` | the platform's agent in `soa_shared/surfaces.py` (`chatgpt_api` and `chatgpt` are both `chatgpt`; `claude` is new to AgentId) |
| `query`, `queryType` | the question's text; its tier label (`Catalog accuracy`…), else its stage |
| `runAt`, `runs` | `soa_runs.run_at`; `run n of runs_per_query` |
| `severity` | value: wrong → high; partial/stale → medium; absent/unverifiable/unscoreable → low; exact → ok. Brand: fabricated/misattributed → high; acknowledged_unknown → medium; echoed/absent → low; grounded → ok. A fabricated_citation or fabricated_availability flag → high |
| `summary` | the outcome's reason |
| `paragraphs: Segment[][]` | the extraction's **stored spans**, verbatim, found in the answer in order; gaps are unmarked segments; a blank line starts a paragraph. A span carrying a price claim gets `mark` (exact → `ok`, wrong → `wrong`, partial/stale → `miss`) and `ann` = that claim's 1-based index in `checks`. No stored spans (an extraction from before the segmenter): the answer's own paragraphs, unmarked |
| `named`, `first` | Layer 1 (`soa_coded_mentions`, mentioned, by position) |
| `checks: Check[]` | one per price claim (`claim_results`): `claim` = stated price and product, `live` = what it was judged against (the page's price at its domain, or the record), `verdict` as below, `note` = the reason in prose, `reason` = the rule code that decided the claim (2C, below). No claim: one Check with `claim: "—"`, whose `reason` is the outcome's rule code |
| `variant_id`, `gtin`, `retailer` (2C, beside) | the question's `source_ref` variant and GTIN, and the retailer the answer was judged at (`expected_answer.attributed_to`; absent when it was judged against the record), so the console can find the True Value cell and its reference price |
| `surface`, `collector` (2C, typed) | the run's surface kind (`api`, `grounded_api`, `consumer_ui`) and the collector that fetched it (`openai`, `google_genai`, `serpapi`…), from `soa_runs`, else `soa_shared/surfaces.py` |

**Verdict mapping** (`Answer.verdict`, `Check.verdict`) — explicit, not lossy:

| soa outcome | verdict | tone |
|---|---|---|
| exact | `right` | ok |
| wrong | `wrong` | bad |
| absent | `missed` | warn |
| partial | `partial` | warn |
| stale | `stale` (verbatim) | warn |
| unverifiable | `unverifiable` (verbatim) | neu |
| unscoreable | `unscoreable` (verbatim) | neu |

Brand-direct outcomes (`grounded / echoed / misattributed / fabricated /
acknowledged_unknown`, plus absent and unscoreable) travel in **`brand_verdict`**;
`verdict` is `null` on those rows. `fabricated_citation`, `fabricated_availability`
and `variant_swap` are in **`flags[]`** (evidence in `flag_details`).

Extras: `cycle, platform, answer_status, tier, reason, verdict, tone,
brand_verdict, flags, flag_details, variant_id, gtin, retailer`. `reason` on the answer is the outcome's rule code
(`soa_expectation_outcomes.reason_code`), omitted when no rule decided it.

**Reason codes** (2C, `Check.reason`, `Answer.reason`): the classifier's
(`scoring/expectation_comparator.py` `REASON_*`), verbatim. Before 2C they were
not sent at all; `note` carried the prose only, which the 2C-0 console could not
read a rule from.

| code | rule |
|---|---|
| `other_brand` | the only price was another brand's product; dropped, so the answer stated none for ours (`absent`) |
| `not_our_product` | the price was for a product that is not ours (`absent`) |
| `variant_clash` | our product, a variant the record does not have (`wrong`) |
| `variant_swap` | the price was for a sibling variant, judged against it |
| `product_inferred` | a price attached to no product; never scored wrong (`unscoreable`) |

A code soa adds later passes through verbatim; the console renders an unknown one neutral.

### Answers summary (2C)

`GET /api/console/answers/summary?cycle=<code>`, `build_answers_summary` in
`console_read_models.py`. One row per run of the cycle; a run with no outcome counts
as `not_scored`.

| field | meaning |
|---|---|
| `surfaces[]` | one entry per surface kind (`api`, `grounded_api`, `consumer_ui`) across the value tiers. Brand-direct outcomes are not a price verdict and are only under `tiers` |
| `tiers[].surfaces[]` | the same entry per tier (`brand_direct`, `catalog_accuracy`, `value_incentives`, `category_control`) and surface |
| `runs`, `answered` | runs, and runs whose `answer_status` is `answered` |
| `counts` | every outcome verbatim (`exact`, `wrong`, `partial`, `stale`, `absent`, `unverifiable`, `unscoreable`, the brand outcomes, `not_scored`) |
| `scored`, `accuracy` | exact + partial + stale + wrong, and exact / scored (`null` when nothing was scored). `unverifiable`, `absent` and `unscoreable` are outside it |
| `unverifiable` | its own count, never in a denominator |
| `answered_with_other_brand` | `absent` with `reason_code: other_brand` |
| `flags` | runs carrying `fabricated_citation`, `fabricated_availability`, `variant_swap` |

There is no all-surfaces total, by tier or overall: an accuracy averaged across a
model-only API, a grounded API and a consumer UI describes none of them.

### TrueValue

| console field | from |
|---|---|
| `columns` | the retailers in the record: the domains in the cycle's cached retailer-prices (2A). A cycle scored against the record (a hosted seller) has one column, its own domain |
| `rows` | one per variant (`sku` = GTIN, or the record's variant id) |
| `TvCell.live` | the 2A reference row's price, `unverifiable` when supply says `verifiable: false`; the record's price when no reference is cached |
| `TvCell.quoted` | the stated price of the runs whose outcome the cell reports (most common) |
| `TvCell.status` | the most common scored outcome across the cell's runs (an absent or a wall decides only when no run was scored; ties go to the worse): exact → `exact`, wrong → `wrong`, partial → `partial`, absent → `missed`, stale → `wrong` (`outcome` says `stale`), unverifiable → **`unverifiable`** (extension), no question → `none` |
| `programs` | `[]` — no per-retailer program terms are scored here |

Extras on each cell: `outcome` (the raw soa outcome), `runs`.

### Accessibility

Proxied from supply's `GET /api/truesync/merchants/{slug}/access` with the tenant
token. Supply already returns the console's `Accessibility`; soa adds `claude` to the
agent vocabulary: a request row with `agent: "claude"` gets `vendor: "claude"`
(supply sends `"other"` because `AgentId` has no claude; 2C-0 adds it). Supply's other
divergences are passed through in `divergences`.

### StudyRow / StudyCell

One row per question in the cycle, `cells` keyed by `AgentId`. Two surfaces can belong
to one agent (`chatgpt` and `chatgpt_api`); `cells` holds the higher-fidelity one
(consumer_ui > grounded_api > api) and **`cells_by_platform`** keeps every surface.
`s`: exact/grounded → ok; wrong/fabricated/misattributed → bad; partial/stale/echoed/
acknowledged_unknown → warn; absent/unverifiable/unscoreable → neu; no run → na; the most
common outcome across the question's runs, ties to the worse. `pick` = Layer 1's
position-1 entity; `named` = whether the primary entity was mentioned; `text`,
`prices`, `at` from run 1; `note` = the outcome's reason.

### Per-surface accuracy

`soa_shared/surface_accuracy.py`: one entry per surface kind (`api`, `grounded_api`,
`consumer_ui`), each with its platforms; accuracy = exact / scored, scored = exact +
partial + stale + wrong; absent, unscoreable and unverifiable are counted and outside the
denominator; coverage counts walls and empty consumer answers as results and failed calls
as failures. **No cross-surface total exists**, by design.

### Full loop

`POST /api/full-loop` `{merchant_slug, study_type, platforms, runs_per_query?, allow_hosted_render?}`
validates the study and surfaces, records the request and answers **202
`{full_loop_id, status: 'queued'}`** (`id` is the same number) without calling supply.
The worker picks the row up from the database, as it does a planned cycle, and makes
supply's POST itself: supply runs the whole loop inline up to 25 pages, which outlasted a
Vercel request (a 504).

`GET /api/full-loop/{id}`: the request, supply's run read live (`supply.run`, or
`supply.read_error`), the cycle once created, and a three-step `strip`
(reference → study → scoring) for the console's status strip. A queued request reads as
`reference_pending` with `supply.run_id` `null`. A request with no progress for 60 minutes
(`FULL_LOOP_STALE_MINUTES`; the longest W&S cycle on record ran 56) reads as `failed` with
an `error` starting `timed_out:`, whether or not the worker has marked it yet, so the
button re-enables. The sequence is in `apps/pipeline/fullloop/coordinator.py`, the
staleness rule in `soa_shared/full_loop_staleness.py`.

### Me (2C-0)

`GET /api/console/me` is the list the scope is chosen from, so it takes no `?org=`: the
orgs come from `soa_shared/customers.selectable_orgs` (operators every linked org, members
their own; the Parleo staff org is never listed). `kind`, `hosting` and `domain` are the
org's first merchant in supply's record (`GET /api/truesync/tenant`, read with that org's
own token, as `/api/customers` does). `slug` is that merchant's slug, the value
`/accessibility?merchant=` takes. `tenant_slug`, `merchants` (every merchant) and `error`
ride beside: an org whose record read fails is still listed, with `kind/hosting/domain`
`null` and the error, rather than vanishing from the switcher.

### Latest full loop (2C-0)

`GET /api/console/full-loop/latest[?org=]`: the scope's newest `soa_full_loop_requests`
row (by `created_at`, then id) in exactly the shape `/full-loop/{id}` returns, or `null`
when the org has never run one. Scoped like every console read.

## Answer divergences

- Answer.verdict is not a console field: it carries the value outcome mapped exact->right, wrong->wrong, absent->missed, partial->partial; stale, unverifiable and unscoreable pass through verbatim with `tone`. Brand-direct rows leave it null and carry `brand_verdict`.
- Check.verdict uses the same mapping, so it can hold stale / unverifiable / unscoreable, which the console's union does not have yet (2C-0).
- Answer.agent can be 'claude', which the console's AgentId does not have yet (2C-0 adds it).
- Segment.mark 'miss' marks a partial or stale claim; the console labels miss 'left out'.
- Extra fields beside the typed ones: platform, answer_status, tier, verdict, tone, brand_verdict, flags, flag_details, cycle, reason (the outcome's rule code), variant_id, gtin, retailer (the True Value cell the answer is judged in).
- Check.reason (2C) is the classifier's rule code (other_brand, not_our_product, variant_clash, product_inferred, variant_swap); Check.note is prose only.
- Answer.surface (api | grounded_api | consumer_ui) and Answer.collector are typed from 2C.

## The studio.ts mirror, field by field

`studio.ts` says its operator shapes "mirror the soa service's tables". Checked field by
field against `soa_entities`, `soa_queries`, `soa_query_generation_jobs` and
`soa_cycles`; these do not mirror, and are mapped as stated:

- Entity.id is a slug string in studio.ts; soa_entities.id is an integer and slug is the string. Mapped id <- slug; soa_id carries the integer.
- EntityType: studio has 'product' and 'group'; soa has 'service' and 'aggregate'. Mapped aggregate -> group and service -> group (soa_entity_type keeps the original); 'product' has no soa value.
- Entity.domain: soa stores website_url, not a domain; the host is derived.
- Entity.parent, logo, tenant, note: no soa column.
- Category vocabularies differ: studio has Footwear, Apparel, Outdoor, Household Paper, Adult Care, Feminine Care, Laundry; soa has Makeup, Fragrance, Haircare, Cross-Category.
- Stage: studio spells 'Ready to buy', soa 'Ready to Buy'. Mapped.
- Prompt.branded has no soa column; derived from whether the text names the study's brand.
- Prompt.source ('ai'|'manual'|'csv') is not soa's provenance ('catalog'|'ai_from_catalog'|'ai'); mapped catalog->csv, the rest->ai, with provenance beside it.
- Study: soa has no studies table. A study is a study_type; its definition is its generation job. rivals, agents and runsPerPrompt live on cycles, not the study; cadence, shelfReads and crawl have no soa column.
- Study.status: soa's generation status (pending|running|complete|failed) is not the console's (active|draft|paused|done); mapped complete->done, failed->paused, else draft.
- Run: a soa cycle. status planned -> queued; usable = runs with answer_status 'answered'; elapsed is not stored. Run.agents can include 'claude'.
- Study patterns agree (retailer, brand_at_retail, brand_vs_brand); soa cycles also have 'mixed'.

## Samples, from the W&S fixture cycle

The fixture cycle (`apps/api/tests/fixtures/console/ws_fixture_cycle.json`, built by
`apps/pipeline/scripts/build_console_fixture.py`) is real Wiggle & Snug answers from the
extraction golden set, scored by the real classifier. Wiggle & Snug is Parleo's own test
store; no customer data. Arrays are cut to their first entries.

### GET /api/console/surfaces

```json
{
  "surfaces": [
    {
      "id": "chatgpt_api",
      "label": "ChatGPT (OpenAI API)",
      "surface": "api",
      "collector": "openai",
      "agent": "chatgpt",
      "fidelity": "OpenAI Responses API, no tools: answers from the model alone",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API, no tools"
    },
    {
      "id": "chatgpt",
      "label": "ChatGPT with web search (OpenAI API)",
      "surface": "grounded_api",
      "collector": "openai",
      "agent": "chatgpt",
      "fidelity": "OpenAI Responses API with the web_search tool available; the model decides whether to search",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    },
    {
      "id": "gemini_api",
      "label": "Gemini (Gemini API)",
      "surface": "api",
      "collector": "google_genai",
      "agent": "gemini",
      "fidelity": "Gemini API, no grounding tool: answers from the model alone",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API, no tools"
    },
    {
      "id": "gemini_grounded",
      "label": "Gemini with Google Search (Gemini API)",
      "surface": "grounded_api",
      "collector": "google_genai",
      "agent": "gemini",
      "fidelity": "Gemini API with the Google Search grounding tool",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    },
    {
      "id": "perplexity",
      "label": "Perplexity Sonar (Perplexity API)",
      "surface": "grounded_api",
      "collector": "perplexity",
      "agent": "perplexity",
      "fidelity": "Perplexity Sonar, grounded by nature, with its citations",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    },
    {
      "id": "claude",
      "label": "Claude with web search (Anthropic API)",
      "surface": "grounded_api",
      "collector": "anthropic",
      "agent": "claude",
      "fidelity": "Anthropic Messages API with the web_search tool available; the model decides whether to search",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    },
    {
      "id": "gemini_web",
      "label": "Gemini web app (consumer)",
      "surface": "consumer_ui",
      "collector": "-",
      "agent": "gemini",
      "fidelity": "gemini.google.com, logged out",
      "consumer": true,
      "available": false,
      "unavailable_reason": "no hosted provider we have verified; not built (no browser automation)",
      "surface_label": "Consumer UI, logged out"
    },
    {
      "id": "chatgpt_web",
      "label": "ChatGPT web app (consumer)",
      "surface": "consumer_ui",
      "collector": "-",
      "agent": "chatgpt",
      "fidelity": "chatgpt.com, logged out",
      "consumer": true,
      "available": false,
      "unavailable_reason": "no hosted provider we have verified; not built (no browser automation)",
      "surface_label": "Consumer UI, logged out"
    }
  ]
}
```

### GET /api/console/answers?cycle=WS-2B-FIXTURE (3 of 8)

```json
[
  {
    "id": "run-1004",
    "agent": "gemini",
    "query": "What does the Wiggle & Snug Snug-Fit Overnight Diapers Size 6 cost?",
    "queryType": "Catalog accuracy",
    "runAt": "2026-10-09T15:00:00+00:00",
    "runs": "run 1 of 1",
    "severity": "high",
    "summary": "stated 16.99; we have never published that (current: 29.99)",
    "paragraphs": [
      [
        {
          "t": "Wiggle & Snug is a Target-exclusive brand."
        }
      ],
      [
        {
          "t": "As of my last update, **Wiggle & Snug Snug-Fit Overnight Diapers Size 6 (52-count)** typically cost around **$16.99** at Target.",
          "mark": "wrong",
          "ann": 1
        }
      ],
      [
        {
          "t": "Prices can vary slightly, so it's always a good idea to check Target's website or app for the most current pricing and any available promotions."
        }
      ]
    ],
    "named": [
      "Wiggle & Snug"
    ],
    "first": "Wiggle & Snug",
    "checks": [
      {
        "claim": "$16.99 for Wiggle & Snug Snug-Fit Overnight Diapers Size 6 (52-count)",
        "agent": "Gemini",
        "live": "$29.99",
        "verdict": "wrong",
        "tone": "bad"
      }
    ],
    "cycle": "WS-2B-FIXTURE",
    "platform": "gemini_grounded",
    "surface": "grounded_api",
    "collector": "google_genai",
    "answer_status": "answered",
    "tier": "catalog_accuracy",
    "verdict": "wrong",
    "tone": "bad",
    "brand_verdict": null,
    "flags": [],
    "flag_details": [],
    "variant_id": "snug-fit-overnight-s6"
  },
  {
    "id": "run-1005",
    "agent": "chatgpt",
    "query": "What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack cost?",
    "queryType": "Catalog accuracy",
    "runAt": "2026-10-09T15:00:00+00:00",
    "runs": "run 1 of 1",
    "severity": "high",
    "summary": "stated 9.99; we have never published that (current: 22.99)",
    "paragraphs": [
      [
        {
          "t": "The **Size 3 small pack** costs **$9.99** — that’s **$0.40 per diaper** for the 25-count pack. ([target.com](https://www.target.com/p/-/A-94793999?utm_source=openai))",
          "mark": "wrong",
          "ann": 1
        }
      ]
    ],
    "named": [],
    "first": "",
    "checks": [
      {
        "claim": "$9.99 for Size 3 small pack",
        "agent": "ChatGPT",
        "live": "$22.99",
        "verdict": "wrong",
        "tone": "bad"
      },
      {
        "claim": "$0.40 for the 25-count pack",
        "agent": "ChatGPT",
        "live": "—",
        "verdict": "wrong",
        "note": "names a sibling variant, and the record has no such variant",
        "reason": "variant_clash",
        "tone": "bad"
      }
    ],
    "cycle": "WS-2B-FIXTURE",
    "platform": "chatgpt",
    "surface": "grounded_api",
    "collector": "openai",
    "answer_status": "answered",
    "tier": "catalog_accuracy",
    "verdict": "wrong",
    "tone": "bad",
    "brand_verdict": null,
    "flags": [],
    "flag_details": [],
    "variant_id": "snug-fit-diapers-s3-small"
  },
  {
    "id": "run-1007",
    "agent": "gemini",
    "query": "Does Wiggle & Snug sell a Snug-Fit Trial Pack?",
    "queryType": "Brand-direct",
    "runAt": "2026-10-09T15:00:00+00:00",
    "runs": "run 1 of 1",
    "severity": "high",
    "summary": "said it could not find Wiggle & Snug: 'Based on my most recent check, I **cannot find a product specifically named the \"Wiggle & Snug Snug-Fit Trial Pack\" available for purchase on their official website (wiggleandsnug.com).**'",
    "paragraphs": [
      [
        {
          "t": "Based on my most recent check, I **cannot find a product specifically named the \"Wiggle & Snug Snug-Fit Trial Pack\" available for purchase on their official website (wiggleandsnug.com).**"
        }
      ],
      [
        {
          "t": "Wiggle & Snug primarily sells individual swaddles and sleepwear products, often available in different sizes and materials (e.g., organic cotton, bamboo)."
        }
      ],
      [
        {
          "t": "It's possible that:"
        },
        {
          "t": "*   It was a limited-time offer that has since ended.\n"
        },
        {
          "t": "*   It was a product offered by a specific retailer or through a different platform in the past.\n"
        },
        {
          "t": "*   The name might have changed."
        }
      ],
      [
        {
          "t": "If you are looking to try different sizes or materials, you would likely need to purchase individual swaddles separately."
        }
      ],
      [
        {
          "t": "I recommend checking their official website (wiggleandsnug.com) directly or contacting their customer service if you have a specific memory of this pack and want to inquire further."
        }
      ]
    ],
    "named": [
      "Wiggle & Snug"
    ],
    "first": "Wiggle & Snug",
    "checks": [],
    "cycle": "WS-2B-FIXTURE",
    "platform": "gemini_grounded",
    "surface": "grounded_api",
    "collector": "google_genai",
    "answer_status": "answered",
    "tier": "brand_direct",
    "verdict": null,
    "tone": "warn",
    "brand_verdict": "acknowledged_unknown",
    "flags": [
      "fabricated_citation"
    ],
    "flag_details": [
      {
        "flag": "fabricated_citation",
        "domains": [
          {
            "domain": "wiggleandsnug.com",
            "resolves": false,
            "responds": null,
            "detail": "does not resolve ([Errno -2] Name or service not known)",
            "checked_at": "2026-10-09T15:00:00+00:00",
            "fabricated": true
          }
        ]
      }
    ]
  }
]
```

### GET /api/console/answers/summary?cycle=WS-2B-FIXTURE (2C)

The fixture has no `other_brand` answer, so `answered_with_other_brand` is 0 here; the
r30 verdict golden (`tests/test_console_read_models.py`) is the case that counts one.

```json
{
  "cycle": "WS-2B-FIXTURE",
  "surfaces": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "runs": 5,
      "answered": 5,
      "counts": {
        "exact": 1,
        "wrong": 4
      },
      "scored": 5,
      "accuracy": 0.2,
      "unverifiable": 0,
      "answered_with_other_brand": 0,
      "flags": {
        "fabricated_citation": 0,
        "fabricated_availability": 0,
        "variant_swap": 0
      }
    },
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out",
      "runs": 1,
      "answered": 0,
      "counts": {
        "absent": 1
      },
      "scored": 0,
      "accuracy": null,
      "unverifiable": 0,
      "answered_with_other_brand": 0,
      "flags": {
        "fabricated_citation": 0,
        "fabricated_availability": 0,
        "variant_swap": 0
      }
    }
  ],
  "tiers": [
    {
      "tier": "brand_direct",
      "label": "Brand-direct",
      "surfaces": [
        {
          "surface": "grounded_api",
          "label": "API with search grounding",
          "runs": 2,
          "answered": 2,
          "counts": {
            "grounded": 1,
            "acknowledged_unknown": 1
          },
          "scored": 0,
          "accuracy": null,
          "unverifiable": 0,
          "answered_with_other_brand": 0,
          "flags": {
            "fabricated_citation": 1,
            "fabricated_availability": 0,
            "variant_swap": 0
          }
        }
      ]
    },
    {
      "tier": "catalog_accuracy",
      "label": "Catalog accuracy",
      "surfaces": [
        {
          "surface": "grounded_api",
          "label": "API with search grounding",
          "runs": 5,
          "answered": 5,
          "counts": {
            "exact": 1,
            "wrong": 4
          },
          "scored": 5,
          "accuracy": 0.2,
          "unverifiable": 0,
          "answered_with_other_brand": 0,
          "flags": {
            "fabricated_citation": 0,
            "fabricated_availability": 0,
            "variant_swap": 0
          }
        },
        {
          "surface": "consumer_ui",
          "label": "Consumer UI, logged out",
          "runs": 1,
          "answered": 0,
          "counts": {
            "absent": 1
          },
          "scored": 0,
          "accuracy": null,
          "unverifiable": 0,
          "answered_with_other_brand": 0,
          "flags": {
            "fabricated_citation": 0,
            "fabricated_availability": 0,
            "variant_swap": 0
          }
        }
      ]
    }
  ]
}
```

### GET /api/console/true-value?cycle=WS-2B-FIXTURE

```json
{
  "columns": [
    {
      "id": "trueshopstore.com",
      "name": "trueshopstore.com",
      "you": true
    }
  ],
  "rows": [
    {
      "product": "Wiggle & Snug Bum Balm 4 oz",
      "sku": "bum-balm-4oz",
      "cells": {
        "trueshopstore.com": {
          "quoted": "$14.99",
          "live": "$12.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 3
        }
      }
    },
    {
      "product": "Wiggle & Snug Cloud Wipes 3-Pack",
      "sku": "cloud-wipes-3pack",
      "cells": {
        "trueshopstore.com": {
          "quoted": "$14.99",
          "live": "$11.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 1
        }
      }
    },
    {
      "product": "Wiggle & Snug Snug-Fit Overnight Diapers Size 6",
      "sku": "snug-fit-overnight-s6",
      "cells": {
        "trueshopstore.com": {
          "quoted": "$16.99",
          "live": "$29.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 1
        }
      }
    },
    {
      "product": "Wiggle & Snug Snug-Fit Diapers Size 3 small pack",
      "sku": "snug-fit-diapers-s3-small",
      "cells": {
        "trueshopstore.com": {
          "quoted": "$9.99",
          "live": "$22.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 1
        }
      }
    }
  ],
  "programs": [],
  "as_of": null,
  "divergences": [
    "TvCell.status is extended by 'unverifiable' (the page blocked both reference sources).",
    "A stale quote has status 'wrong' (it is wrong today); `outcome` carries 'stale'.",
    "`programs` is empty: soa scores no program terms per retailer here."
  ]
}
```

### GET /api/console/accessibility?merchant=wiggle-and-snug

```json
{
  "requests": [
    {
      "identity": "OAI-SearchBot",
      "vendor": "chatgpt",
      "agent": "chatgpt",
      "result": "1 of 1 pages answered",
      "ok": true,
      "code": "ok"
    },
    {
      "identity": "Googlebot",
      "vendor": "gemini",
      "agent": "gemini",
      "result": "1 of 1 pages answered",
      "ok": true,
      "code": "ok"
    },
    {
      "identity": "PerplexityBot",
      "vendor": "perplexity",
      "agent": "perplexity",
      "result": "1 of 1 pages answered",
      "ok": true,
      "code": "ok"
    },
    {
      "identity": "Claude-User",
      "vendor": "claude",
      "agent": "claude",
      "result": "not measured: no verified UA configured",
      "ok": false,
      "code": "—"
    },
    {
      "identity": "ParleoAuditBot (control)",
      "vendor": "other",
      "agent": null,
      "result": "1 of 1 pages answered",
      "ok": true,
      "code": "ok"
    }
  ],
  "summary": {
    "value": "11",
    "of": "11",
    "label": "answer-time robots tokens and agent probes passed"
  },
  "checks": [
    {
      "name": "ChatGPT",
      "value": "robots 2/2 · probes 1/1",
      "status": "ok"
    },
    {
      "name": "Gemini",
      "value": "robots 2/2 · probes 1/1",
      "status": "ok"
    },
    {
      "name": "Perplexity",
      "value": "robots 2/2 · probes 1/1",
      "status": "ok"
    }
  ],
  "grid": {
    "cols": [
      {
        "name": "ChatGPT"
      },
      {
        "name": "Gemini"
      },
      {
        "name": "Perplexity"
      },
      {
        "name": "Claude"
      }
    ],
    "rows": [
      {
        "name": "Snug-Fit Diapers Size 3 — Small Pack (84 ct)",
        "source": "trueshopstore.com",
        "cells": [
          {
            "v": "readable",
            "tone": "ok"
          },
          {
            "v": "readable",
            "tone": "ok"
          },
          {
            "v": "readable",
            "tone": "ok"
          },
          {
            "v": "not_measured",
            "tone": "neu"
          }
        ],
        "detail": {
          "variant_ref": "catalog_variant:5",
          "url": "https://trueshopstore.com/products/snug-fit-diapers?variant=s3-small",
          "summary": "readable"
        }
      }
    ]
  },
  "note": "robots.txt per AI token on each page's path; one GET per agent identity with that agent's published UA, from Parleo's network, plus a Parleo-UA control. A bot UA sent from a non-vendor IP can be treated differently from the real crawler.",
  "merchant": "wiggle-and-snug",
  "access_run": {
    "id": 12,
    "status": "done",
    "started_at": "2026-10-09T14:40:00+00:00",
    "finished_at": "2026-10-09T14:41:10+00:00",
    "counts": {
      "tokens_checked": 6,
      "tokens_allowed": 6,
      "probes_made": 5,
      "probes_ok": 5
    }
  },
  "divergences": [
    "AccessRow is one probe in the console; here it is one agent identity aggregated over every page probed (result 'n of m pages answered', code = status counts).",
    "AccessRow.vendor can be 'claude' (vendor 'claude', agent 'claude'); the console adds it to AgentId in 2C-0."
  ]
}
```

### GET /api/console/studies?cycle=WS-2B-FIXTURE (1 of 6)

```json
[
  {
    "id": "WIG_144",
    "q": "Is Wiggle & Snug Member Rewards still available?",
    "type": "Brand-direct",
    "cells": {
      "chatgpt": {
        "s": "ok",
        "pick": "Wiggle & Snug",
        "named": true,
        "at": "2026-10-09T15:00:00+00:00",
        "text": "Yes — **Wiggle & Snug Member Rewards is still available**. It’s described as **free to join**, with members earning **1 point per $1 spent** and access to member pricing/offers. ([trueshopstore.com](https://trueshopstore.com/loyalty))\n\nThe tiers are:\n\n1. **Member** — free to join",
        "note": "cited trueshopstore.com",
        "platform": "chatgpt",
        "surface": "grounded_api",
        "outcome": "grounded",
        "runs": 1
      }
    },
    "cells_by_platform": {
      "chatgpt": {
        "s": "ok",
        "pick": "Wiggle & Snug",
        "named": true,
        "at": "2026-10-09T15:00:00+00:00",
        "text": "Yes — **Wiggle & Snug Member Rewards is still available**. It’s described as **free to join**, with members earning **1 point per $1 spent** and access to member pricing/offers. ([trueshopstore.com](https://trueshopstore.com/loyalty))\n\nThe tiers are:\n\n1. **Member** — free to join",
        "note": "cited trueshopstore.com",
        "platform": "chatgpt",
        "surface": "grounded_api",
        "outcome": "grounded",
        "runs": 1
      }
    }
  }
]
```

### GET /api/console/accuracy?cycle=WS-2B-FIXTURE

```json
{
  "cycle": "WS-2B-FIXTURE",
  "surfaces": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "counts": {
        "wrong": 4,
        "exact": 1
      },
      "platforms": [
        {
          "platform": "chatgpt",
          "collector": "openai",
          "agent": "chatgpt",
          "counts": {
            "wrong": 2
          },
          "coverage": {
            "runs": 3,
            "results": 3,
            "answered": 3,
            "no_ai_answer": 0,
            "sign_in_wall": 0,
            "blocked": 0,
            "failed": 0
          },
          "scored": 2,
          "accuracy": 0.0,
          "partial_rate": 0.0,
          "stale_rate": 0.0,
          "wrong_rate": 1.0,
          "unverifiable": 0
        },
        {
          "platform": "gemini_grounded",
          "collector": "google_genai",
          "agent": "gemini",
          "counts": {
            "exact": 1,
            "wrong": 2
          },
          "coverage": {
            "runs": 4,
            "results": 4,
            "answered": 4,
            "no_ai_answer": 0,
            "sign_in_wall": 0,
            "blocked": 0,
            "failed": 0
          },
          "scored": 3,
          "accuracy": 0.3333,
          "partial_rate": 0.0,
          "stale_rate": 0.0,
          "wrong_rate": 0.6667,
          "unverifiable": 0
        }
      ],
      "coverage": {
        "runs": 7,
        "results": 7,
        "answered": 7,
        "no_ai_answer": 0,
        "sign_in_wall": 0,
        "blocked": 0,
        "failed": 0
      },
      "scored": 5,
      "accuracy": 0.2,
      "partial_rate": 0.0,
      "stale_rate": 0.0,
      "wrong_rate": 0.8,
      "unverifiable": 0
    },
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out",
      "counts": {
        "absent": 1
      },
      "platforms": [
        {
          "platform": "aimode",
          "collector": "serpapi",
          "agent": "aimode",
          "counts": {
            "absent": 1
          },
          "coverage": {
            "runs": 1,
            "results": 1,
            "answered": 0,
            "no_ai_answer": 1,
            "sign_in_wall": 0,
            "blocked": 0,
            "failed": 0
          },
          "scored": 0,
          "accuracy": null,
          "partial_rate": null,
          "stale_rate": null,
          "wrong_rate": null,
          "unverifiable": 0
        }
      ],
      "coverage": {
        "runs": 1,
        "results": 1,
        "answered": 0,
        "no_ai_answer": 1,
        "sign_in_wall": 0,
        "blocked": 0,
        "failed": 0
      },
      "scored": 0,
      "accuracy": null,
      "partial_rate": null,
      "stale_rate": null,
      "wrong_rate": null,
      "unverifiable": 0
    }
  ]
}
```

### GET /api/console/runs

```json
[
  {
    "id": "WS-2B-FIXTURE",
    "study": "ws-2b-fixture",
    "started": "2026-10-09T14:55:00+00:00",
    "finished": "2026-10-09",
    "status": "complete",
    "planned": 8,
    "collected": 8,
    "usable": 7,
    "agents": [
      "aimode",
      "chatgpt",
      "gemini"
    ],
    "elapsed": "",
    "platforms": [
      "chatgpt",
      "gemini_grounded",
      "aimode"
    ],
    "surfaces": [
      "consumer_ui",
      "grounded_api"
    ],
    "full_loop_run_id": 33
  }
]
```

### GET /api/console/studio/studies

```json
[
  {
    "id": "ws-2b-fixture",
    "name": "Wiggle & Snug 2B fixture",
    "entity": "wiggle-and-snug",
    "pattern": "brand_at_retail",
    "category": "Baby Care",
    "rivals": [
      "huggies"
    ],
    "retailers": [],
    "agents": [
      "aimode",
      "chatgpt",
      "gemini"
    ],
    "runsPerPrompt": 1,
    "cadence": "once",
    "prompts": [
      {
        "id": "WIG_144",
        "text": "Is Wiggle & Snug Member Rewards still available?",
        "stage": "Research",
        "branded": true,
        "persona": "Value-Conscious Parent",
        "source": "ai",
        "provenance": "ai_from_catalog",
        "tier": "brand_direct"
      },
      {
        "id": "WIG_148",
        "text": "Does Wiggle & Snug sell a Snug-Fit Trial Pack?",
        "stage": "Research",
        "branded": true,
        "persona": "Value-Conscious Parent",
        "source": "ai",
        "provenance": "ai_from_catalog",
        "tier": "brand_direct"
      },
      "… 4 more prompts"
    ],
    "shelfReads": [],
    "crawl": false,
    "status": "done",
    "created": "2026-10-08T12:00:00+00:00",
    "lastRun": "2026-10-09",
    "owner": "op@parleo.io",
    "platforms": [
      "chatgpt",
      "gemini_grounded",
      "aimode"
    ],
    "generation_status": "complete"
  }
]
```

### GET /api/console/studio/entities

```json
[
  {
    "id": "huggies",
    "name": "Huggies",
    "type": "brand",
    "domain": "huggies.com",
    "category": "Baby Care",
    "aliases": [],
    "soa_id": 2,
    "soa_entity_type": "brand"
  },
  {
    "id": "wiggle-and-snug",
    "name": "Wiggle & Snug",
    "type": "brand",
    "domain": "trueshopstore.com",
    "category": "Baby Care",
    "aliases": [
      "Wiggle and Snug"
    ],
    "soa_id": 1,
    "soa_entity_type": "brand"
  }
]
```

### GET /api/full-loop/{id} (and /api/console/full-loop/{id})

```json
{
  "id": 1,
  "status": "reference_pending",
  "merchant": "wiggle-and-snug",
  "study_type": "ws-2b-fixture",
  "platforms": [
    "chatgpt",
    "gemini_grounded"
  ],
  "surfaces": [
    {
      "id": "chatgpt",
      "label": "ChatGPT with web search (OpenAI API)",
      "surface": "grounded_api",
      "collector": "openai",
      "agent": "chatgpt",
      "fidelity": "OpenAI Responses API with the web_search tool available; the model decides whether to search",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    },
    {
      "id": "gemini_grounded",
      "label": "Gemini with Google Search (Gemini API)",
      "surface": "grounded_api",
      "collector": "google_genai",
      "agent": "gemini",
      "fidelity": "Gemini API with the Google Search grounding tool",
      "consumer": false,
      "available": true,
      "unavailable_reason": null,
      "surface_label": "API with search grounding"
    }
  ],
  "runs_per_query": 1,
  "error": null,
  "created_at": "2026-10-13 05:28:34.964828+00:00",
  "updated_at": "2026-10-13 05:28:34.964828+00:00",
  "supply": {
    "run_id": 33,
    "status": "access_done",
    "run": {
      "id": 33,
      "status": "access_done",
      "access_run_id": 12,
      "reference_run_id": null,
      "soa_cycle_id": null,
      "background": true,
      "target_count": 19,
      "error": null
    },
    "read_error": null
  },
  "cycle": null,
  "strip": [
    {
      "step": "reference",
      "label": "Access and reference reads",
      "state": "running"
    },
    {
      "step": "study",
      "label": "Study on the chosen surfaces",
      "state": "waiting"
    },
    {
      "step": "scoring",
      "label": "Scored and reported to TrueSync",
      "state": "waiting"
    }
  ]
}
```

### GET /api/console/me (2C-0)

From the test fixture, as the operator; the merchant records are the test's fake supply
answers, not a real tenant's.

```json
{
  "user": {
    "id": "op",
    "email": "op@test"
  },
  "is_operator": true,
  "orgs": [
    {
      "id": 20,
      "slug": "brandco",
      "name": "Brandco",
      "kind": "seller",
      "hosting": "external",
      "domain": "brandco.test",
      "tenant_slug": "brandco",
      "merchants": [
        {
          "slug": "brandco",
          "name": "Brandco",
          "domain": "brandco.test",
          "kind": "seller",
          "hosting": "external",
          "has_record": false
        }
      ],
      "error": null
    },
    {
      "id": 10,
      "slug": "wiggle-and-snug",
      "name": "Wiggle & Snug",
      "kind": "brand",
      "hosting": "parleo",
      "domain": "trueshopstore.com",
      "tenant_slug": "wiggle-and-snug",
      "merchants": [
        {
          "slug": "wiggle-and-snug",
          "name": "Wiggle & Snug",
          "domain": "trueshopstore.com",
          "kind": "brand",
          "hosting": "parleo",
          "has_record": true
        }
      ],
      "error": null
    }
  ]
}
```

### GET /api/console/full-loop/latest (2C-0)

The `/full-loop/{id}` shape above, for the newest request; `null` before the first run.
