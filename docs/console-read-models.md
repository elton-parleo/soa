# Console read models (2B, 2C, 2C-1, 2C-2, 2C-2a, 2C-2b, 2C-2c, 2C-3, 2C-3a, 2D, 2E, 2E-2, 2G, 2H, 2I-8)

soa's results in the shapes the console reads (parleohq/truesync, branch
`console-demo`, `apps/console/src/data/types.ts` and `studio.ts`). The console
is the product UI from 2C-0 on; the soa web app's existing report endpoints are
untouched and stay linked from the console until they are ported.

Code: `apps/api/app/routers/console.py`, `apps/api/app/routers/full_loop.py`,
`apps/api/app/services/console_read_models.py` (every mapping), `apps/api/app/services/console_parity.py`
(2C-2: the demo blocks, every sentence a template in `TEMPLATES`), `apps/api/app/console_scope.py`
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
| `GET /api/console/answers/summary?cycle=<code>` | per tier, every agent together (`all`, 2I-8) and per surface: every outcome, `unverifiable`, `answered_with_other_brand` (2C) | — (soa) |
| `GET /api/console/true-value?cycle=<code>` | variants x retailers | `TrueValue` |
| `GET /api/console/programs?merchant=<slug>[&cycle=<code>]` | the merchant's owned incentives, with how the cycle's value answers did (2C) | `TrueValue.programs` |
| `GET /api/console/accessibility?merchant=<slug>` | supply's access payload | `Accessibility` |
| `GET /api/console/truesync?merchant=<slug>` | the TrueSync matrix, assembled from supply (2C) | `TrueSyncData` (products, channels, lastVerified) |
| `GET /api/console/catalog?merchant=<slug>`, `/catalog/versions`, `/catalog/template.{csv,xlsx}`, `POST /catalog/validate`, `POST /catalog/commit` | Setup › Catalog over supply's 1B feed loader; **operator only** (2C) | — (soa) |
| `GET /api/console/studies/options`, `POST /studies/preview`, `POST /studies/generate`, `POST /studies/{study_type}/regenerate`, `GET /studies/{study_type}/status`, `POST /api/console/cycles` | the Create Study modal and "start a cycle"; **operator only** (2C) | — (soa) |
| `GET /api/console/studies?cycle=<code>` | question x agent | `StudyRow[]` |
| `GET /api/console/accuracy?cycle=<code>` | per-surface accuracy, never pooled | — (soa) |
| `GET /api/console/visibility?cycle=<code>` | who the answers name and who they name first, every agent together (`all`, the default, 2I-8) and per surface, each with a per-agent split, from the stored mention coding (2C-1) | `Ranking` / `RankRow`, and one `VisibilityRow` per run |
| `GET /api/console/record/list?merchant=<slug>` | the merchant's products for the record list, each with its status (2C-1) | — (the record list) |
| `GET /api/console/record?merchant=<slug>&product=<sku>` | one product's record, read-only: fields with provenance, page disagreements, issues, variants, the schema.org artifact (2C-1) | `Record_` |
| `GET /api/console/overview?cycle=<code>[&merchant=<slug>]` | This week, every agent together (`all`, the default, 2I-8) and per surface: agents, products, signals, the week in short, changes, Visibility's ranking (2C-2) | `AgentWeek[]`, `ProductWeek[]`, `Signal[]`, `WeekChange[]` |
| `GET /api/console/runs` | the tenant's cycles | `Run[]` (studio.ts) |
| `GET /api/console/studio/studies` | the tenant's studies with prompts | `Study[]` + `Prompt` (studio.ts) |
| `GET /api/console/studio/entities` | entities the tenant's cycles compare | `Entity[]` (studio.ts) |
| `GET /api/console/full-loop/{id}`, `GET /api/full-loop/{id}` | the full loop's combined status | — (soa) |
| `POST /api/full-loop` | queues a full loop for the worker (202 `{full_loop_id, status: 'queued'}`) | — (soa) |
| `GET /api/console/me` | who is signed in and the orgs they may select (2C-0) | — (the console's workspace switcher) |
| `GET /api/console/full-loop/latest` | the scope's most recent full loop, or `null` (2C-0) | — (soa) |
| `GET /api/console/score?cycle=<code>[&merchant=<slug>]` | the Share of Algorithm: per surface, pooled as the mean of the surface scores, stored with its scorer version (2C-3) | `Score` (beside) |

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
| `surfaces[]` | 2I-8: `all` ("All agents", every run whatever its surface) first, then one entry per surface kind (`api`, `grounded_api`, `consumer_ui`) across the value tiers. Brand-direct outcomes are not a price verdict and are only under `tiers` |
| `tiers[].surfaces[]` | the same entry per tier (`brand_direct`, `catalog_accuracy`, `value_incentives`, `category_control`) and surface |
| `runs`, `answered` | runs, and runs whose `answer_status` is `answered` |
| `counts` | every outcome verbatim (`exact`, `wrong`, `partial`, `stale`, `absent`, `unverifiable`, `unscoreable`, the brand outcomes, `not_scored`) |
| `scored`, `accuracy` | exact + partial + stale + wrong, and exact / scored (`null` when nothing was scored). `unverifiable`, `absent` and `unscoreable` are outside it |
| `unverifiable` | its own count, never in a denominator |
| `answered_with_other_brand` | `absent` with `reason_code: other_brand` |
| `flags` | runs carrying `fabricated_citation`, `fabricated_availability`, `variant_swap` |

2I-8: `all` pools **counts**, never accuracies: its `counts` are the surfaces' counts summed and
its accuracy is exact over scored on those sums (a mean of the surfaces' accuracies is never
taken). `unverifiable` stays outside it. Before 2I-8 there was no all-surfaces entry; since 2I no
cycle runs the ungrounded `api` surface, so `all` adds grounded APIs and consumer UIs, the agents
the demo counts together.

### TrueValue

| console field | from |
|---|---|
| `columns` | the retailers in the record: the domains in the cycle's cached retailer-prices (2A). A cycle scored against the record (a hosted seller) has one column, its own domain |
| `rows` | one per variant (`sku` = GTIN, or the record's variant id) |
| `TvCell.live` | the 2A reference row's price, `unverifiable` when supply says `verifiable: false`; the record's price when no reference is cached |
| `TvCell.quoted` | 2C-2: the deciding run's stated price (most common among the runs with that outcome); `—` when no run quoted one |
| `TvCell.status` | 2C-2, `TV_CELL_RULE`, on `surface` (2I-8: `all`, every agent's quotes together; each surface's own cell in `by_surface`): the **worst** outcome among the runs that **quoted a price** (wrong, then stale, then partial, then exact); a run that quoted nothing, or priced another brand's product (absent), does not vote; no quoting run → `missed` (left out). Mapped exact → `exact`, wrong → `wrong`, partial → `partial`, absent → `missed`, stale → `wrong` (`outcome` says `stale`), unverifiable → **`unverifiable`** (extension), no question → `none`. A cell never reads WRONG with nothing quoted |
| `programs` | `[]` without `merchant`; with it (2C-2) the owned incentives as `/programs` maps them |

Extras on each cell: `outcome` (the raw soa outcome), `runs`, and (2C) `reference_source`
(`honest_fetch` or `hosted_render` from supply's reference row; `record` when the cycle was
scored against the record), `method` and `observed_at` (the read's time; the record's
publication time for `record`), so a reader can tell an honest fetch from a hosted render.

### Programs (2C)

`GET /api/console/programs?merchant=<slug>[&cycle=<code>]` proxies supply's
`GET /api/truesync/merchants/{slug}/incentives/owned` with the tenant token and maps each
incentive to `TrueValue.programs` (`name`, `terms`, `agentsRight`, `tone`). With `cycle`,
`agentsRight` (2C-2) is `quoted right by N of M agents` on the highest-fidelity surface that
asked about the program: M agents answered a scored question about it (matched by code, else
tier name; absent, unscoreable and unverifiable are outside it) and N got every such answer
exact. `by_surface` beside has each surface's `{asked, right}` agents. A program no question
asked about reads `not asked this cycle`, never 0. Extras: `mechanic, code, tier_name,
valid_until, asked, scored, right, surface, by_surface`.

### Accessibility

Proxied from supply's `GET /api/truesync/merchants/{slug}/access` with the tenant
token. Supply already returns the console's `Accessibility`; soa adds `claude` to the
agent vocabulary: a request row with `agent: "claude"` gets `vendor: "claude"`
(supply sends `"other"` because `AgentId` has no claude; 2C-0 adds it). Supply's other
divergences are passed through in `divergences`.

### TrueSync matrix (2C)

`GET /api/console/truesync?merchant=<slug>`, `build_truesync`. Supply has no single Command
Center payload: the soa web app assembles the matrix in the browser
(`MerchantCommandCenter.jsx`, `verificationModel.js`). soa now does the same server-side, with
the tenant token, from `GET /channels`, `GET /publications?limit=500`,
`GET /merchants/{slug}/catalog`, `GET /merchants/{slug}/provenance` and one
`GET /merchants/{slug}/verifications?channel=` per active channel.

| console field | from |
|---|---|
| `channels[]` | supply's channel list in its order (`id` = slug, `spec` = `spec_version`); `verification_surface`, `extension_status`, `connected`, `depth_label` beside. Never a hardcoded list: `manufacturer_center` appears when supply lists it |
| `products[]` | one per published catalog listing (`sku` = product id, `name` = title, `variants`); `listing_id`, `variant_ids`, `gtins`, `product_url`, `provenance` (`published` or `scrape`) and `provenance_basis` beside |
| `TsCell.s` | the newest publication per listing x channel: `published`; `compiled` (compiled, validated, withdrawn); `blocked` (failed, its error in `note`); `not_published` (none); `na` when the channel says `connected: false` (`note: "not connected"`) |
| `TsCell.d`, `n`, `at` | the newest `fetch_probe` at or after the publish: `drift` with `n` findings, `none`, else `unverified`. `at` = the newest fresh verification. A record older than the publish counts for nothing |
| `acceptance` (beside) | Merchant Center from `gmc_diagnostics` (404 → `not_found`, approved, else `disapproved` with issues or `pending`); Manufacturer Center from `mc_acceptance` `drift.acceptance` (`approved / pending / disapproved / not_found / unavailable`) |
| `origin` (beside) | Manufacturer Center only: `drift.origin`, `parleo` or `gmc_sync` (the product came into MC through Merchant Center's sync) |
| `validator[channel]` | validation errors as `conflict`; expressiveness flags `dropped` → `dropped`, `approximated` → `approx`, `checkout_scope`/`info` → `info`; one `ok` line for a valid record with no flags |
| `payload[channel]` | the publication's artifact, pretty-printed JSON |
| `lastVerified` | the newest fresh verification across the matrix |

This is the soa follow-up supply's MC-1 doc asks for (`docs/truesync/manufacturer-center-lane.md`):
`mc_acceptance` read as acceptance, `drift.acceptance` preferred, and "not connected" from
`channel.connected === false`. There is no MC-2 or MC-3 in supply yet; the column is MC-1's.

### Setup › Catalog (2C)

`app/routers/console_ops.py`, **operator only** (a member is 403 `operator only: …`), scoped
with `?org=` and the tenant token like every console read.

| endpoint | does |
|---|---|
| `GET /catalog?merchant=` | `source: "hosted"` for a Parleo-hosted merchant (its published catalog, `read_only: true`, from the store config); `source: "feed"` (current version and rows) or `"none"` (no feed yet) for an external one, with every version |
| `GET /catalog/versions?merchant=` | supply's feed history, newest first |
| `GET /catalog/template.{csv,xlsx}` | supply's template |
| `POST /catalog/validate?merchant=` | supply's validate, which is the preview (every row `ready / warning / error` with its messages, staged under `upload_id`), plus one soa warning per row: `multipack_suggested`, "page shows a count but multipack is empty", when the latest reference read's `pack_differs` finding shows a count that only a multipack explains and the row's multipack is empty. Advisory: commit writes supply's staged preview |
| `POST /catalog/commit` | `{merchant, upload_id, mode}`, mode `all_valid_rows` or `require_clean` |

### Studies & Audits: Create Study and cycles (2C)

`app/routers/console_ops.py`, `app/services/console_studies.py`; **operator only**. The
studio reads (`/runs`, `/studio/studies`, `/studio/entities`) stay readable by members: they are
the tenant's own rows, and Answers and the full-loop strip read `/runs` and `/studio/studies`.
They already apply the studio.ts mapping below; 2C changes none of it.

- **`GET /studies/options`**: the `soa_queries` constraints, the surface list (as
  `/api/console/surfaces`, the two not available entries included), the scope's merchants
  (supply's `/tenant`; one with `has_record: false` cannot be grounded in), `max_questions` 100,
  `default_brand_direct_count` 12, `default_variant_cap` 20.
- **`POST /studies/preview`** `{merchant, tiers, stage_total, brand_direct_count?, variant_cap?,
  allowed_categories?, personas?, study_pattern?}`: the catalog-built tiers **as the generation
  worker builds them**. The generator's catalog-tier code moved into
  `soa_shared/catalog_tiers.py` (with the snapshot builder, `soa_shared/catalog_snapshot.py`, and
  the retailer enum, `soa_shared/retailers.py`) so the API runs the same module the worker does;
  the pipeline's `generation/catalog_tiers.py` is that module under its old name. Each question
  carries its typed `expected_answer` and the mock's chips (`Expected: $22.99`, `GTIN …`,
  `84 count`); `catalog_accuracy` reports `sampled`, `variants_available` and `variant_cap` (the
  variant cap, 20 by default); brand-direct is a count and one example marked `illustrative`
  (a model writes its wording at generation time); `tally` is the modal's
  (`{stage} + brand-direct AI-written + {accuracy + value} from the catalog`) against 100. The
  catalog line is `merchant.readback`.
- **`POST /studies/generate`**: `POST /api/studies/generate`'s body plus the modal's `tiers`. With
  a syndicated merchant the grand total is checked against 100 **server-side** (422 with the
  tally's words), then the web app's own route queues the job, `customer_organization_id` = the
  scope. The worker generates it as it always has, brand-catalog mode, the validator and the
  review passes included.
- **`POST /studies/{study_type}/regenerate`**, **`GET /studies/{study_type}/status`**: the web
  app's routes, unchanged.
- **`POST /api/console/cycles`** `{study_type, platforms, runs_per_query?, cycle_code?, notes?}`:
  a surface that cannot run here (`soa_shared/surfaces.unavailable_reason`) is refused before
  anything is written; the comparison set is `soa_shared/comparison_sets.py`'s (2I-5, below);
  then the web app's `create_cycle`. The code defaults to `YYYYMMDD-HHMMSS-<study_type>`.

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

### Visibility (2C-1)

`GET /api/console/visibility?cycle=<code>`, `build_visibility` / `load_visibility`. Who the
answers name and who they name first, from the coding already stored per answer. Nothing is
re-read from the answer text and no model is called.

Two codings are read, as stored:

| coding | table | what it holds |
|---|---|---|
| Layer 1 | `soa_coded_mentions` | one row per run x the cycle's entities (ours is `role: primary`, the comparison set `competitor`): `mentioned`, and **`position`**, the ordinal of the entity's first mention among *every* brand the answer names (`parser/prompts.py`, POSITION RULES) |
| Layer 2 | `soa_expectation_outcomes.extraction` | `other_brands_named` (name, `presented_as`, `relation`) and the stored `spans`. **No order field.** Only scored runs have one: an unprompted (untiered) question has no Layer 2 |

**First pick** (`first`, and `first_basis` beside it):

1. The brand Layer 1 coded at **position 1** (`layer1_position`).
2. Layer 1 ranks every brand the answer names, so when its lowest position is 2 or more, a brand
   outside the comparison set came first. Layer 2 has no order field, so its brands are read by
   **span position**: the one found in the earliest stored span (`span_position`), else the first
   listed (`coded_order`). A Layer 1 brand is a candidate here only when Layer 1 coded no position
   at all.
3. When neither coding names that brand (in practice: an unprompted answer, which has no Layer 2),
   `first` is `null`, `first_basis` is `uncoded`, and the answer is counted in
   `ranking.first_uncoded` (per surface) and `agent_first_uncoded` (per surface and agent). No
   brand is credited with a pick nobody coded.

In cycle 229 (`FL3-wiggle-and-snug-20261014`, 514 answered runs) that is 256 answers by position
1, 6 by span position and 27 uncoded: 26 unprompted answers whose Layer 1 positions start at 2, 3
or 4, and one catalog answer whose only other brands were sources. 225 answers name no brand.

Prompted questions name the brand in the question, so read Visibility by tier: in cycle 229 Wiggle
& Snug is named in 170 of the 214 prompted answers and in **0 of the 300 unprompted** ones, where
Pampers takes the first pick in 38 and Huggies in 24.

**Named**: Layer 1's mentioned entities in position order, then Layer 2's other brands. Layer 2
names are rolled up: a name that starts with a comparison-set brand or alias is that brand
(`Huggies Snug & Dry`, `HUGGIES` are Huggies), and a name that starts with another Layer 2 name
is that name (`Millie Moon Overnight Diapers` is Millie Moon; the display is its most common
spelling). Entries named only as a source (`presented_as: source` or `relation: citation_only`:
cited sites, publishers) are left out and counted in `sources_left_out`.

| field | from |
|---|---|
| `byQuestion[]` | one per run (not per question): `q`, `type` (tier label, else the stage), `tier` (`unprompted` for a question with none), `surface`, `agent`, `named [{name, you}]`, `first {name, you} \| null`; `run`, `platform`, `query_code`, `stage`, `answered`, `first_basis` beside |
| `ranking.rows[]` | every brand named in an answered run, plus ours: `name`, `you`, and `surfaces {<surface>: {named, first, agents {<agent>: {named, first}}}}`. `named` / `first` are the counts on `ranking.surface` |
| `ranking.surface`, `denom` | the highest-fidelity surface with answered runs (consumer_ui > grounded_api > api), and its answered runs |
| `ranking.denoms`, `agent_denoms` | answered runs per surface, and per surface and agent |
| `surfaces[]`, `tiers[]` | what the console's selectors offer |

A run that did not answer (`no_ai_answer`, a wall) is in `byQuestion` with `answered: false` and
in no denominator. There is no total across surfaces. `RankRow.series` is not sent; the console
draws a sparkline only from two or more cycles it reads itself.

### Offer record (2C-1)

`GET /api/console/record/list?merchant=<slug>` and `GET /api/console/record?merchant=<slug>&product=<sku>`,
`build_record_list` / `build_record`. Read-only. Proxied from supply with the org's tenant token, in
parallel: `GET /tenant` (the merchant's kind and hosting, as `/me` reads them),
`/merchants/{slug}/catalog` (the record: a hosted merchant's published listings, an external
merchant's current feed), `/publications`, `/channels`, `/merchants/{slug}/provenance`,
`/merchants/{slug}/reference` (the latest 2A reference read) and, for one record,
`/merchants/{slug}/incentives`. The catalog is required: a 404 is "no record yet" (an empty list;
404 for one product). Every other read degrades: its part is left out and the failure is named in
`read_errors`.

**Provenance** (`Field.prov`, `RECORD_PROVENANCE`), stated once:

| the value's source | merchant kind | prov |
|---|---|---|
| `published` | seller | `retail` |
| `published` | brand | `brand` |
| `scrape` | any | `parleo` (our observation) |
| taken from an agent answer | any | `agent` |
| anything else (a published listing whose merchant kind is unknown, no basis) | | `unknown`, rendered neutral |

A listing's source is supply's provenance mix (`/provenance`, which counts listing rows): the
merchant's when all its listings are one source; mixed, a listing with a publication is
`published` and the rest `scrape`. An external merchant's feed has no listing rows; its record is
what the merchant published (`source_basis: feed`). Every field of one record has the same
provenance today; no record field is taken from an answer yet, so `agent` does not occur.

| console field | from |
|---|---|
| `kind` | `offer` for a seller, `product` for a brand |
| `sku` | the listing's `product_id` (the TrueSync matrix's `sku`), else the listing id; `product=` takes either |
| `title`, `sub` | the listing's title; brand, variant count, the merchant's domain |
| `status` | `Fails validation on …` (bad) for a compiled publication with validation errors; `n page differences` (warn); `Published to n channels` (ok); `From your feed` or `Not published yet` (neu) |
| `fields[]` | Name, Brand, Product page, Price (one price, or the range), Member price (when the record's incentives state one), GTIN, Count, Published (spec version in `note`); then one field per disagreement |
| `Field.was`, `diff`, `note` | a 2A finding about what the product is (`name_differs`, `pack_differs`, `gtin_mismatch`, `gtin_missing_on_page`, `brand_missing_on_page`) on the latest reference read of one of the variant's pages: `k` = `<Name / Pack count / GTIN / Brand> · <variant>`, `v` = the record's value, `was` = what the page showed, `note` = which page, when and how it was read, and for a name the words only on one side. Price findings are True Value's, an unreadable page Accessibility's |
| `issues[]` | the validator and expressiveness lines of the publications that compiled: conflict → bad, dropped and approximated → warn, info → neu. Failed publishes are one `Not published to …` issue (warn) with the error, as the matrix shows them blocked |
| `json` | the schema_org publication's artifact, pretty-printed; `""` when there is none (an external merchant's feed is not compiled here) |
| `variants[]` | `id` (variant id, else GTIN), `name`, `price` (`$22.99`, `$12.99 · member $10.99`, or `not carried`), `status` from the reference rows (`Matches the page`, `Page differs: name, pack count`, `Page not read`, `Not read yet`) and its tone; `gtin`, `list_price`, `member_price`, `count`, `pages` beside |

A price the record does not carry reads `not carried` wherever a price would show, never blank.
Extras: `merchant, listing_id, product_url, merchant_kind, hosting, source, source_basis,
json_channel, channels, reference_run, read_errors, divergences`. `/record/list` returns
`{merchant, kind, hosting, products: [{sku, listing_id, title, sub, variants, status, diffs}], read_errors}`.

## 2C-2: the demo's blocks from stored data

`console_parity.py`. Pivots and summaries over what the read models above already read: per-run
outcomes, the mention coding, the True Value cells, the 2A reference and access reads, the
publication journal and the owned incentives. Nothing new is measured, nothing is modeled, and
no model is called: every sentence is a template from `TEMPLATES`, filled from counts. Two
rules hold everywhere: counts are shown for every agent together by default, as the demo shows
them, with each surface's own count beside it as a filter (2I-8; before, per surface and never
pooled), a per-agent split beneath each; and `unverifiable` never sits in an accuracy. The score
pools surfaces by score, not by count (2C-3, unchanged).

### Two fixes first

- **Record variants and their reads.** supply's reference rows carry `variant_ref`
  (`catalog_variant:<n>`, `feed_sku:<n>`, `listing:<n>`), the variant key as `variant_label`,
  the merchant SKU and the page URL. `reference_matches` joins on the variant id (any of
  those), then the SKU, then, for a listing with one variant, its page or `listing:<id>`; the
  GTIN is a second key. The GTIN-only join left GTIN-less variants `Not read yet` although
  their pages were read.
- **True Value cells.** `TV_CELL_RULE` (above, in TrueValue) replaces "most common, ties to
  the worse", per surface, and the quote shown is the deciding run's. The same rule is written
  again in the console's adapter (`aggregateCell`) and pinned by tests on both sides.

### Overview (2C-2)

`GET /api/console/overview?cycle=<code>[&merchant=<slug>]`, `build_overview`. Per surface
(`by_surface.<surface>`), with `surface` the one Visibility ranks by:

| field | from |
|---|---|
| `agents[]` (`AgentWeek`) | per agent on the surface: `answers` (answered runs), `named` / `first` (from the mention coding, as Visibility reads it, over unprompted answers when the cycle asked any, `named_of` beside), `pricesRight` = exact of scored (catalog and value tiers, 2B), `wrong`; beside: `exact, scored, stale, unverifiable, answered_with_other_brand, did_not_know`. `note` is the agent's highest-count problem (`agent.*` rules). `delta` / `dir` are first picks against the previous scored cycle, empty on a first cycle |
| `products[]` (`ProductWeek`) | one per True Value row asked about on the surface: `named` / `first` from the coding of the runs about it; `quoted` = each agent's most common quote with its run count; `live` = the reference with its source and date; `status` from the cell (`TV_CELL_RULE`, stale and wrong are `wrong`, left out and unverifiable are `none`; the cell's own status beside); `issue` (`product.*` rules). Worst first |
| `signals[]` (`Signal`, at most 4) | fixed rules in priority order: another brand's price on 5 or more answers (Lost pool), fabricated brand-direct verdicts on 5 or more (Missed pool, with the sources caveat for a cycle that started before Oct 14), one product wrong in 3 or more runs (Missed pool), any unverifiable (Access), any measured access problem (Access, from the last access run when `merchant` is given) |
| `summary` | three sentences: visibility, accuracy, the top signal |
| `changes[]` (`WeekChange`) | only with an earlier scored cycle of the same org: named, first, prices right, another brand's price, wrong prices, now against then, with `dir` and a tone that knows which way is good. Else `[]` and `changes_note` says "First cycle. Changes appear from the next one." |
| `ranking` | Visibility's ranking, as `/visibility` sends it (reused, not recomputed) |

### Visibility additions (2C-2)

`headline` (and `headlines` per surface): the gap sentence, over unprompted answers when the
cycle asked any (`headline.*` rules). `matrix.<surface>`: prompt x agent, a cell being the
first pick most of the question's runs gave (ties to ours), with every pick counted beside;
prompts in stage order (Awareness, Research, Comparison, Ready to Buy). `by_stage.<surface>`:
per stage and per tier, answered runs, ours named and first, and the brand first most often.

### True Value additions (2C-2)

`surface`, `surfaces`, and on every cell `by_surface` and `quotes` (each run's agent, surface,
outcome and stated price). `by_agent.<surface>.<agent>`: `exact, scored, wrong, stale, partial,
unverifiable, left_out, other_brand` over the catalog tier. With `merchant`: `programs` (as
`/programs`), `ladder` and `receipt` for the primary product (the variant this cycle asked about
most): the record's list price, then every lower price the record states for it (supply's per-
variant `member_prices`, else its member-price offers, plus a first-order price the record
states as `effective_net_price`) and the owned incentives' member prices. A discount stated
without a price gets no step and is named in `ladder.unpriced`: nothing is computed or modeled.
A failed supply read leaves its part out and is named in `read_errors`.

### Accessibility additions (2C-2)

`checks` are the merchant-level checks from the latest reference read (one row per page read);
supply's per-agent robots and probe lines move to `agent_checks`. Each request carries
`measured` (an identity with no verified UA is not measured, never a problem), and `problems`
counts the measured ones that did not get through.

| check | value | basis |
|---|---|---|
| robots.txt names answer-time agents | `not checked` | supply's access payload does not carry each token's rule source (an explicit group or the wildcard) |
| Product markup on product pages | n of pages read | reads with `method == json_ld` |
| GTIN in markup | n of pages | pages whose record carries a GTIN, read with structured data, without a `gtin_missing_on_page` finding |
| Program price in markup | n of pages read | reads with `member_price` present |
| Needs a hosted render | n of pages, 0 is good | reads from the hosted renderer |
| Edge lets signed agents in | `not checked` | not probed yet |
| Protocol profile (UCP, MCP, llms.txt) | `not checked` | not read yet |

`status` is `ok` / `partial` / `bad`, or `not_checked` (an extension of the console's union).

### Offer record additions (2C-2)

`offer_fields`: each owned incentive that applies to the product (name, terms, mechanic, end),
availability when a read or the record states it, last verified (the newest reference read or
channel check); shipping and returns only when the record carries them (never a placeholder).
`history`: the publication journal, the channel checks and the reference reads of the product,
newest first. `surfaces`: the TrueSync matrix's cells for this product (`build_truesync` on its
listing, reused). `issue_groups`: every issue kept, grouped by channel with a count and a
readable `label`; `expanded` names the three with most impact (a dropped mechanic on a channel
the merchant publishes to, then a failed publish, a conflict, an approximation).

### Catalog and studies additions (2C-2)

`/catalog` rows gain `stage` / `stages`: `measured` when the latest scored cycle quoted the
variant (on its highest-fidelity surface with a quote), `published` when a channel published its
listing, `verified` when published and every scored price for it was exact. `retailers_read`:
per domain of the latest reference read, pages, how they were read, hosted renders, the last
read and a note from the read statuses (`catalog.read`). `stage_cycle` names the cycle.
`/studio/studies` gains `prompt_counts` `{branded, unbranded, prompts}`.

### The templates

Every sentence above, by rule, with an example filled from counts (house rules: no dashes, no
semicolons, pinned by a test). The product quote detail (2C-2a) is not a sentence template: it
lists every distinct quote with the runs behind it and their agents, a sibling variant's price
named, then the runs with no price, for example
`$6.99 for Snug-Fit Trial Pack, 3 of 5 runs (ChatGPT 2, Gemini 1). $12.99, 1 of 5 runs (Gemini 1)`.

| rule | when | example |
|---|---|---|
| `agent.other_brand` | the agent's highest-count problem is another brand's price | Answered 6 price questions with another brand's price. |
| `agent.wrong` | its highest-count problem is wrong prices | Wrong on 4 prices. |
| `agent.unknown` | its highest-count problem is "did not know" on brand-direct | Did not know the brand 2 times. |
| `agent.right` | no problem counted, prices scored | Right on 3 of 3 prices. |
| `agent.none` | nothing scored | No price scored. |
| `product.other_brand` | the product's highest-count problem: another brand's product priced | Priced another brand's product in 2 of 6 runs. |
| `product.wrong` | wrong or stale quotes | Quoted a wrong price in 1 of 2 runs. |
| `product.left_out` | no price quoted | No price quoted in 3 of 3 runs. |
| `product.unverifiable` | the page could not be read | The page could not be read, so 2 of 2 runs are not scored. |
| `product.right` | no problem | Right in 3 of 3 runs. |
| `product.not_asked` | no run on this surface | Not asked on this surface this cycle. |
| `signal.other_brand` | another brand's price on 5 or more answers | Answered 6 price questions with another brand's price. / 6 of 12 price answers on the grounded API. ChatGPT 6. |
| `signal.fabricated` | fabricated brand-direct verdicts on 5 or more answers | 5 brand answers stated facts Wiggle & Snug never published. / 5 of 6 brand-direct answers on the grounded API. Gemini 5. |
| `signal.fabricated_caveat` | appended when the cycle started before Oct 14 2026 | Sources were not captured before Oct 14, so some of these may rest on a page we did not see. |
| `signal.wrong_product` | one product wrong in 3 or more runs | Wrong price on Bum Balm 4 oz in 4 runs. / Quoted $14.99 against $12.99. $14.99 (Gemini, 4 of 5 runs). |
| `signal.unverifiable` | any unverifiable price | 1 price could not be checked. / The page blocked both readers. These are counted on their own and never in an accuracy. ChatGPT 1. |
| `signal.access` | any measured identity that did not get through | 1 agent identity could not read the pages. / PerplexityBot. From the last access run. |
| `summary.visibility_named` | sentence 1, ours not first | Named in 0 of 300 unprompted answers and first in 0. |
| `summary.visibility_lead` | sentence 1, ours first and ahead of every rival | First in 6 of 7 answers, ahead of every other brand. |
| `summary.rivals` | after sentence 1 or the headline, the two rivals with most first picks | Pampers first in 38, Huggies in 24. |
| `summary.accuracy` | sentence 2 | Prices right in 1 of 5 scored answers, 6 answered with another brand's price. |
| `summary.accuracy_unverifiable` | sentence 2 with unverifiable answers | Prices right in 1 of 5 scored answers, 6 answered with another brand's price, 1 not checked. |
| `summary.no_price` | sentence 2, nothing scored | No price was scored on this surface. |
| `summary.no_signal` | sentence 3, no signal fired | No signal crossed its threshold this cycle. |
| `changes.first_cycle` | fewer than two scored cycles | First cycle. Changes appear from the next one. |
| `headline.gap` | Visibility's headline, ours not first | Named in 0 of 300 unprompted answers. Pampers first in 38, Huggies in 24. |
| `headline.lead` | Visibility's headline, ours first | First in 6 of 7 answers. |
| `catalog.read` | Retailers read, per domain | 1 of 3 pages read, 1 challenged, 1 not read. |
| `changes.not_comparable_subset` | the previous cycle ran a subset of this cycle's agents on the surface | Not comparable: 20260915-113207-wiggle-snug-full ran ChatGPT only on this surface. |
| `changes.not_comparable` | the agent sets differ otherwise | Not comparable: C178 ran Gemini on this surface, this cycle ran ChatGPT and Gemini. |
| `changes.not_comparable_tier` | this cycle reads unprompted answers, the previous asked none | Not comparable: C178 asked no unprompted questions on this surface. |
| `changes.detail` | a compared metric | 34 of 59 this cycle against 30 of 59 in C178. |

### 2C-2a: eight fixes from the first live walk (cycle 229)

| # | what the live data showed | cause | fix |
|---|---|---|---|
| 1 | Changes: "34 of 59 against 38 of 25" | another brand's price was over `scored` (those runs are absent, never scored), and the previous cycle's named/first used its own tier and surface rule | one surface (the run's own, as Visibility reads it), the current cycle's tier for both, one denominator per metric (below); "Not comparable: …" with no delta when the agent sets differ |
| 2 | "0 of 13 scored cells exact" with 9 exact runs | one retailer, so both agents collapsed into one worst-wins cell | with fewer than two retailers the columns are the agents on the surface (`column_kind: 'agent'`, `columns_by_surface`), each cell still worst-wins; the one-retailer cell rides beside as `retailer_cells` |
| 3 | "Program price quoted 0 of 0" with 36 Member+ questions | programs came from the owned incentives only, whose display name never matched the question's `tier_name` | programs from the record first (`record_programs`: the generator's source), joined on the folded tier name, the code or the question's `source_ref.offer_id`; each surface carries `scored` and `exact` answers |
| 4 | "Member+ 5% off, stated without a price" | the ladder read only supply's `member_prices` list and the offers | the variant's own member price first (`member_prices`, `entitled_member_price`, a catalog variant's `member_price`), the offers only when it states none; the receipt reads the same steps |
| 5 | "GTIN in markup 6 of 6" with 19 pages | its denominator was pages whose record carries a GTIN | every markup check is over the pages read |
| 6 | By stage counted prompted rows under Unprompted | one stage table for every tier | `by_stage.<surface>.stages_by_tier.<tier>` (and `all`); the console picks the reader's tier |
| 7 | "wrong in 4 of 6 runs" beside one wrong quote; reference "the record, Sep 4" | a sibling variant's quote (`target: swap`) was dropped from the quote; the cycle cached no reference | the swap claim that decided a run is its quote, named (`swap_product`); with `merchant`, the newest readable page read is the reference, the record only when none exists (`live_basis`) |
| 8 | the week in short said the other-brand count twice | the top signal was appended whatever the sentences before had said | the last sentence is the first signal not already stated, and is dropped when every signal is |

**Changes denominators** (`CHANGE_METRICS`, both cycles on the same surface and agent set):

| metric | count | over |
|---|---|---|
| Named, First pick | answered runs naming ours / with ours first | answered runs of the current cycle's tier (unprompted when it asked any) |
| Prices right | exact | scored (exact, partial, stale, wrong) |
| Wrong prices | wrong | scored |
| Answered with another brand's price | absent with reason `other_brand` | answered price questions (catalog and value tiers) |

`changes_status` per surface: `first_cycle` (no earlier scored cycle), `not_comparable` (the
agents differ, or this cycle reads unprompted answers and the previous asked none), `compared`.
`changes_note` says which in one line; only `compared` carries deltas.

### 2C-2b: four fixes from the second live walk, on a fixture shaped like production

Two 2C-2a fixes passed on a fixture that held data where production does not. The W&S test
fixture is now production's shape: `supply_reference_ws.json` is supply's `/reference` payload
with one row per record variant (19; `variant_ref` `catalog_variant:<n>`, the variant key as
`variant_label`, `method: json_ld`, no `price_observed` findings), 7 of them with a
`member_price` from the page markup; the record's variants state no member price (the console
tests strip the pipeline fixture's `member_prices` / `entitled_member_price`); swap rows are the
entries `scoring/expectation_comparator.py` writes and `rescore_cycle` stores unchanged, in both
shapes below.

| # | what the live data showed | cause | fix |
|---|---|---|---|
| 1 | "Stated without a price, so not drawn: Member+ 5% off" beside an Oct 14 read of $12.09 | the ladder read member prices only from the record, which states none | one source order (`member_price_source`): the record's variant, else the newest readable page read with a `member_price` (its tier is the one the record's offers name), else "stated without a price". Each ladder step and the receipt say which ("from the record" / "from the page read Oct 14"); the record's `variants[]` (`member_source`, `member_note`) and its Member price field use the same order |
| 2 | "wrong in 4 of 6 runs" beside "No price, 5 of 6" | cycle 229 was scored before `b3c5a29`: a swap claim then kept the sibling's own verdict in `outcome` (`exact`, the Trial Pack's own price) and the question's in `question_outcome`. The quote was in `claim_results[].stated` either way; the read model matched the swap claim on `outcome` only | `deciding_swap` matches on `question_outcome`, else `outcome`, else the first swap with a stated price. Products carry `quote_groups` (every run in exactly one group); tested: the groups sum to the row's runs and every wrong run shows a value |
| 3 | "Not comparable" above an agent row "First, change: -2" | the agent table took a delta whatever the block said | `build_agents` follows `changes_status`: a delta only when `compared`, over the block's denominator (`named_of`), with `delta_detail`; else `delta_status` says why |
| 4 | 514 answers, a tier table summing to 516, an agent table to 514 | an errored run has no `answer_status`, and `/answers/summary` counted a missing status as answered | one rule, below |

**Run counts** (every count on the Overview): **runs** are the rows the cycle executed, an
errored run included (`coverage.runs`); **answers** are the runs whose `answer_status` is
`answered` (`coverage.answers`); the tier table (`/answers/summary` `answered`) and the agent
table (`agents[].answers`) count answers. An errored or walled run is a run, never an answer.

### 2C-2c: the member price, the readback verdicts, and four leftovers

**The member price (item 1), diagnosed from code.** Three causes were possible; one applies.
- (a) **Yes.** `/reference` (supply `views.reference` over `prices.retailer_prices`) returns one
  row per variant x retailer: the best read of the *newest* reference run that read the page
  (`latest_run_reads`). When the newest read of a page states no member price and an older one
  did, the rule could not see it. Supply #20 (`feature/2a2-followups`, merged as `febc447`) adds
  `GET /merchants/{slug}/retailer-prices?history=1&limit=`: every readable read per variant x
  retailer, newest first, answered with `history: true`. Before #20 the handler takes only
  `as_of`; FastAPI ignores the unknown parameter and the answer has no `history` key.
- (b) No. The ladder (`_read_member_price`), the receipt (the ladder's steps) and the record's
  `variants[]` (`_reference_rows`) all join with `reference_matches` (variant id, `variant_label`,
  SKU, then GTIN), so a GTIN-less variant finds its read.
- (c) No. Accessibility's "Program price in markup" counts `member_price` on the same `/reference`
  rows the ladder read.

Fix: `_member_reads` asks for `retailer-prices?history=1&limit=10`; when the answer says
`history: true`, the member-price rule walks those reads newest first to the first that states
one (the ladder, the receipt and the record's variants); otherwise it reads `/reference` as
before. **Deploy:** soa is safe on either supply. The older read's price appears only once supply
#20 is deployed with its migration (`e8b1d4f7a2c5`, own domains and the run reason) applied.

**The readback verdict rule (item 2).** A check is one claim. For a claim about a sibling
(`target: swap`) or a variant the record lacks (`clash`): the verdict is the question's,
`question_outcome` first (rows scored before `b3c5a29`), then `outcome`, the same rule the
products table and True Value read; the "said" cell keeps the claim ("$6.99 for Snug-Fit Trial
Pack"); "judged against" is the **asked** variant's reference (its expected amount), never the
sibling's; `reason` is `variant_swap` (or `variant_clash`) and `note` says "priced Snug-Fit Trial
Pack instead" (the sibling's record name, from the study's catalog questions). Any other claim
keeps its own outcome and reference.

| # | cause | fix |
|---|---|---|
| 3 | a run with no stored claim whose expectation has no `amount` (a code or points question) printed a dash for the reference, so the row read "— — Wrong" | the check says what was expected (`describe`); the console also leaves out any row blank on both sides, with a caption |
| 4 | the console read the full record per product (sixteen supply reads) to draw a timeline | `/truesync` products carry `timeline` from the publications and channel checks the matrix already read; the console's API client times out every read (45 s) into an error state |
| 5 | swap quotes were grouped by the answer's words for the sibling | grouped by the resolved sibling variant id, named once by its record name |
| 6 | branded came from a text match on the brand; the Overview counted questions asked, Studies the study's; status came from generation | branded = questions in a tier that names the brand (brand-direct, catalog, value), unbranded the rest; the Overview's `questions` is the study's count with `asked` beside; status is Draft with no cycle, Active while one is planned or running, Done otherwise |
| 7 | the Answers strip read `surfaces`, the value tiers only (516 minus 66 brand-direct) | `/answers/summary` adds `all_tiers` per surface, by the run-count rule; the strip shows runs and answers over every tier and says its accuracy is over price questions |

### What the stored data cannot fill

- **robots.txt explicit groups**: supply's access payload keeps each agent's allow/disallow but
  not `tokens[].rule_source`, so "names answer-time agents" is `not checked`, never guessed.
- **Shipping and returns**: neither the hosted catalog nor the feed carries them; left out.
- **Availability**: supply's reference payload does not project the read's availability, and
  the hosted catalog has none; the field shows only when one of them states it.
- **A competitor grid**: needs a comparison-set domain list on supply (a separate prompt).
- **Revenue, the Fix and Prove workflow**: out of scope (Preview). The Share of Algorithm score is 2C-3 (below).

## 2C-3: the Share of Algorithm score

`GET /api/console/score?cycle=<code>[&merchant=<slug>]`, `app/services/console_score.py`. The Audit's
formula over loop data: the Audit's registry (`soa_shared/scan_dimensions.py`: weights, seen/said
splits, `dimension_max`, the readiness bar), the Audit's per-dimension scoring functions
(`lite_pillars.py`, `cycle_scoring_full.py`), called, never changed. The console only adapts loop
counts into those functions' inputs. No model is called.

### The weights, as the scorer has them

Read from `soa_shared/scan_dimensions.py`. The weights are the ones the 2C-3 prompt lists as v4; in the
code they are `SCORER_VERSION = "5"` (its docstring: v5 replaced v4's own weights, True Value 40 to 50):

| pillar | dimension | weight | seen / said |
|---|---|---|---|
| Visibility 32 | Share of Mentions | 22 | |
| | Recommendation Strength | 10 | |
| Accessibility 18 | Agent Access | 5 | |
| | Catalog & Context | 8 | |
| | Protocol & Feed Presence | 5 | |
| True Value 50 | Price Truth | 16 | 7 / 9 |
| | Value Protocols | 14 | 14 / none (encode only) |
| | Deal Citability | 12 | 7 / 5 |
| | Member Value | 8 | 5 / 3 |

Readiness bar: `VERDICT_COMPOSITE_THRESHOLD = 60`, with `VERDICT_TRUE_VALUE_RATIO_THRESHOLD = 0.25`
beside it (`compute_verdict`: AGENT-READY needs both).

**Which scorer version.** The file holds two constants. `SCORER_VERSION = "5"` is the lite Audit's
(24 questions, one surface). `FULL_CYCLE_SCORER_VERSION = "7"` (2I: grounded surfaces only; "6" before) is the same registry and weights for a
full cycle: the one difference is Deal Citability's said half, banded as a rate
(`apply_deal_citability_rate_band`) because a citation count saturates at full-cycle volume. A loop is
a full cycle, and its value-tier half is a rate by construction (right ÷ scored), so the console
scores under **`FULL_CYCLE_SCORER_VERSION`** and stores that value as `scorer_version`. Reused, not
forked: a re-weight of either bumps it and every stored console score reads stale.

### Mapping, one row per Audit dimension

Per surface unless the row says otherwise. "Pages read" is the latest 2A reference read of the
merchant, `read_status` `ok` or `empty`, the same rows and predicates Accessibility's merchant
checks count (`console_parity.build_access_checks`).

| dimension | scorer input | loop source | denominator | state |
|---|---|---|---|---|
| Share of Mentions | `som_pct`, `total_mentions` (`score_share_of_mentions_full`) | Layer 1 (`soa_coded_mentions`) on answered **unprompted** runs: mentions of ours ÷ mentions of every cycle entity, as `MetricsCalculator` counts `soa_pct` | mentions of the cycle's entities in answered unprompted runs | `measured` when the surface has an answered unprompted run, else `not_measured` |
| Recommendation Strength | `rsi_score` (`score_recommendation_strength_full`) | Layer 1 `strength` on our unprompted mentions, Primary +3 / Positive +1 / Neutral 0 / Negative −1, mean over our mentions, as `MetricsCalculator` counts `rsi_score` | our mentions in answered unprompted runs | as above |
| Agent Access | `crawl_dimensions.agent_access` `{score, max}` | supply's access run: measured identities that got through; Claude-User (no verified UA) and the Parleo control are not agents measured | measured agent identities | `measured`, else `not_measured` when no identity was measured. One value for every surface |
| Catalog & Context | `crawl_dimensions.catalog_context` | pages read with `method == json_ld` **and** a GTIN in markup (Accessibility's GTIN predicate) | pages read | `measured`, else `not_measured` with no page read. One value for every surface |
| Protocol & Feed Presence | `crawl_dimensions.protocol_feed` | **2E:** the cycle's domain checks (`soa_cycles.domain_checks`): the Audit's `score_protocol_feed` on the merchant's own site, run on the worker | the Audit's own (verifiable sub-checks) | `measured` with a record; the Audit's `na` (brand-only site) stays `na`; no record: `not_measured`. One value for every surface |
| Price Truth, seen | `crawl_dimensions.price_truth_seen` | pages read with a price | pages read | as Catalog & Context |
| Price Truth, said | `run_signals` (`score_price_truth_said`) | catalog tier: one signal per scored run, cited = `exact` | scored (exact, partial, stale, wrong); `unverifiable`, `absent`, `unscoreable` outside it | `measured`; fewer than `MIN_OPPORTUNITY_SET_MENTIONS` (2) scored is the scorer's own `na`, and the dimension rescales onto its seen half |
| Value Protocols | `crawl_dimensions.value_protocols_seen` | **2E:** the cycle's domain checks: the Audit's `score_value_protocols` (its five manifest checks) | the Audit's own | as Protocol & Feed |
| Deal Citability, seen | `crawl_dimensions.deal_citability_seen` | **2E:** pages read whose supply `incentive_in_markup` has any flag true (`member_price`, `promo`, `subscription`, `code`) | pages read with `json_ld_scanned: true` (an unscanned read is out of both counts, never a false) | `measured`; from a supply before #21, or with no read scanned yet, `not_measured`, and with it the whole dimension |
| Deal Citability, said | `run_signals` (`score_deal_citability_said_full`) | value tier, `code` and `points` questions: cited = `exact` (unchanged in 2E) | scored | counted with the seen half; computed and shown, not counted, while the seen half is unmeasured |
| Member Value, seen | `crawl_dimensions.member_value_seen` | pages read with `member_price` | pages read | as Catalog & Context |
| Member Value, said | `run_signals` (`score_member_value_said`) | value tier, `member_price` (Member+) questions: cited = `exact` | scored | `measured`; fewer than 2 scored is `na`, onto the seen half |

Member Value's applicability is the scorer's (`member_value_applicable`): the record states a program
(the study asked a `member_price` question, standing in for the Audit's membership probe) or the
member-price half earned credit. Neither: `na`, and its 8 points leave the applicable max, as in the Audit.

**Rows changed from the prompt's table, and why.**

- **Share of Mentions**: the prompt had named ÷ answered. The scorer's input is a share of mentions
  across tracked brands (`soa_pct`, capped at 50 for full marks), not a presence rate; named ÷ answered
  fed into it would give full marks to any brand named in half the answers. The loop has the
  honest input (Layer 1 counts every cycle entity), so the row uses it. Named ÷ answered stays as a metric row.
- **Recommendation Strength**: the prompt had first pick ÷ answered. The scorer's input is `rsi_score`,
  Layer 1's strength coding, which the loop stores (`soa_coded_mentions.strength`). First pick ÷ answered
  stays as a metric row.
- **Deal Citability, seen**: the prompt had reads carrying an incentive or code in markup. Supply's
  reference read stores `offer_text` but `/reference` and `/retailer-prices` do not serve it, so the loop
  has no source. `not_measured`.
- **Deal Citability, said**: computed, but by the Audit's own rule an unmeasurable seen half takes the
  whole dimension out of the applicable max (`build_pillars_payload` / `build_full_cycle_pillars`,
  `seen_blocked`: "the WHOLE dimension leaves the applicable max"), said shown, uncounted.
- **Price Truth, said**, **Member Value, said**: the scorer counts "cited a price" / "cited member
  value" over mentions; the loop has a stronger fact, the price judged exact against the record, so
  `exact` is the citation and `scored` the opportunity set. The value-tier signals are placed in a
  purchase-intent stage so the scorer's own opportunity-set filter keeps them.

### Not measured, and the applicable max

A `not_measured` dimension leaves the applicable max by its full weight; a said half the scorer calls
`na` rescales its dimension onto the seen half (`dimension_max`); Member Value `na` leaves by 8. The
score is `round(earned ÷ applicable max × 100)`, as `compute_composite` does for the Audit's /92. One
departure: `compute_composite` only shrinks its basis for Member Value, so the Audit scores an
unmeasured Protocol & Feed (`na`) and Value Protocols as zeros in the composite. The console cannot
call it for that reason, and sums the scorer's own dimension rows over the measured ones instead. A
`not_measured` dimension is never 0.

### The read model

`GET /api/console/score?cycle=<code>[&merchant=<slug>][&rescore=true]`, tenant-scoped like every
console read (operator `?org=`; `rescore` is operator only, a member is 403).

| field | meaning |
|---|---|
| `scorer_version` | `FULL_CYCLE_SCORER_VERSION`, stored with the score. `adapter_revision` beside is the adapter's own cache key, never shown as a version |
| `score` | the equal-weight mean of `surfaces[].score`, rounded once, at the end. `null` with nothing measured |
| `earned`, `applicable_max` | the mean of the surfaces' points and applicable maxes: "N of M applicable" on the tile when M < 100 |
| `readiness_bar` | `VERDICT_COMPOSITE_THRESHOLD`, 60 |
| `verdict`, `verdict_note` | `compute_verdict` on the pooled score and True Value, **only when no dimension is `not_measured`** (the Audit gives one only in its `scored` state). Otherwise `null`, and the note says how many points are not measured. Member Value `na` does not withhold it |
| `surfaces[]` | each pooled surface: `score` (unrounded: earned ÷ applicable max × 100), `earned`, `applicable_max`, its three pillars |
| `surfaces_left_out[]` | a surface the cycle ran with no answer on it: not pooled, with the reason |
| `pillars[].dimensions[]` | one row per Audit dimension in registry order: `score` and `applicable_max` (pooled means, 0 where a surface did not count it), `state` (`measured`, `not_measured`, `na`, or `partial` when the surfaces differ), `reason`, `numerator` / `denominator` **only when every surface reads the same one** (a crawl-side count), `source`, `parts` (the seen and said halves, each with its own state and counts, and the `line` its gap reads as) and `by_surface` |
| `biggest_gap` | the counted dimension with the most points left (pooled), ties to the registry's order; `line` is its part with the most left, on the surface where it leaves the most |
| `metrics[]` | the demo's five rows on the highest-fidelity pooled surface (`metric_surface`), `by_surface` beside, `surface_note` naming the surface and the tier. `delta` only when `previous.comparable`, else `null` with `delta_reason` |
| `coverage` | pooled surfaces, questions asked on them, agents, runs, and `line` |
| `previous` | the newest earlier scored cycle's **stored** score: `{cycle, scorer_version, score, comparable, reason, delta}`. Comparable only with the same scorer version, the same pooled surfaces and the same agents on each (2C-2a's rule). `null` on a first cycle |
| `inputs` | what the stored score was computed from: `merchant`, `reference_run`, `access_run`, `scored_at` |
| `stored`, `read_errors` | whether the row holds this score. A failed supply read is served and never stored, so the next read tries again |

**The five rows.**

| row | count | over |
|---|---|---|
| First recommendation | answered runs with ours first (Visibility's first pick) | answered runs of the Overview's tier (unprompted when the cycle asked any, else every answered run) |
| Share of answers | answered runs naming ours | the same |
| Program named when the brand is named | runs whose Layer 1 mention of ours is coded `deal_cited` or `member_value_cited` | answered runs of that tier naming ours |
| Prices quoted exactly | exact, catalog tier | scored, catalog tier |
| Program terms right | exact, value tier | scored, value tier |

Named and first are the Overview's counts (`parity.surface_metrics`), not recomputed. The two price rows
split the Overview's "prices right" by tier so they do not overlap.

**Stored, versioned.** The score is stored on `soa_cycles.share_of_algorithm` (JSON) with
`share_of_algorithm_version`, and served from there: a stored read makes no supply call. It is
recomputed on the next read when its `scorer_version` or `adapter_revision` is not the current one, when
`merchant` names another merchant than the stored one, or on an operator's `rescore`. A previous cycle is
read as stored and never recomputed under it (its crawl side would be today's), so one stored under
another version reads "Scored under v5, re-score to compare." where a delta would go.

**Pooled.** A surface's score is its own earned ÷ applicable max. The pooled score is the mean of those.
Every count stays per surface: a dimension's `numerator` / `denominator` exist on the pooled row only
for a crawl-side count every surface shares; a per-surface count lives in `by_surface` and `parts`.

**Grounded only (2I, scorer 7).** The pooled score is the mean over grounded surfaces only: an `api`
surface (the model alone, no search tool) is listed in `surfaces_left_out` as "ungrounded · not scored"
and never pooled. `FULL_CYCLE_SCORER_VERSION` went from 6 to 7 for it, so every stored score recomputes
on its next read. Where the number moved, the history entry reads "scorer 6 → 7: ungrounded surfaces
excluded from pooling"; otherwise it reads "scorer 6 → 7". A cycle whose runs are all grounded (229) scores
the same. FL4 (Oct 16, the store) is a one-surface cycle under it, scored on ChatGPT's grounded surface
alone. New cycles cannot include an ungrounded surface: every dispatch refuses one with
`ungrounded_surface_not_allowed` (see Surfaces, below).

### Deploy note (migration `f3b8d2a6c4e1`, not applied)

`apps/pipeline/alembic/versions/f3b8d2a6c4e1_add_share_of_algorithm_to_soa_cycles.py` adds two nullable
columns to `soa_cycles`: `share_of_algorithm JSON`, `share_of_algorithm_version TEXT`. Additive, so safe
to apply ahead of the deploy. **This branch does not apply it.** Round-tripped on a throwaway local
Postgres (`scripts/migration_roundtrip.py --from e1a7c3f9b2d4`: upgrade, downgrade, upgrade, then a
row written and read back, the downgrade keeping the row).

Either order works. Deployed before the migration, the endpoint reads and writes the columns inside a
try: it serves the score, stores nothing (`stored: false`) and recomputes on every read. The columns are
deliberately **not** mapped on the `SoaCycle` model: a mapped column is in every ORM select of the table,
which would break those reads on a database the migration has not reached. Apply with

```
cd apps/pipeline && alembic upgrade f3b8d2a6c4e1
```

against the target only when deploying. After a `rescore_cycle`, re-score the cycle (`?rescore=true`,
operator) or clear its row's `share_of_algorithm`: the stored score does not see a reclassification.

### Sample: GET /api/console/score?cycle=WS-2B-FIXTURE&merchant=wiggle-and-snug (cut)

With the W&S access sample (`supply_access_ws.json`) and the Oct 14 reference read (19 pages). The
`rules` and the not-measured rows' `parts` and `by_surface` are cut.

```json
{
  "cycle": "WS-2B-FIXTURE",
  "scorer_version": "6",
  "adapter_revision": 1,
  "score": 60,
  "earned": 20.3,
  "applicable_max": 34.0,
  "total_max": 100.0,
  "readiness_bar": 60,
  "verdict": null,
  "verdict_note": "No readiness verdict while 63 of 100 points are not measured. The Audit gives one only when every dimension is.",
  "surfaces": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "score": 59.705882352941174,
      "earned": 20.3,
      "applicable_max": 34.0,
      "pillars": [
        {
          "code": "visibility",
          "score": null,
          "applicable_max": 0.0
        },
        {
          "code": "accessibility",
          "score": 7.5,
          "applicable_max": 13.0
        },
        {
          "code": "true_value",
          "score": 12.8,
          "applicable_max": 21.0
        }
      ]
    }
  ],
  "surfaces_left_out": [
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out",
      "reason": "no answer on this surface"
    }
  ],
  "pillars": [
    {
      "code": "visibility",
      "name": "Visibility",
      "max": 32.0,
      "score": null,
      "applicable_max": 0.0,
      "dimensions": [
        {
          "code": "share_of_mentions",
          "name": "Share of Mentions",
          "pillar": "visibility",
          "max": 22.0,
          "score": null,
          "applicable_max": 0.0,
          "state": "not_measured",
          "reason": "no unprompted question answered on this surface",
          "numerator": null,
          "denominator": null,
          "source": "soa_coded_mentions, answered unprompted runs",
          "parts": "… (cut)",
          "by_surface": "… (cut)"
        },
        {
          "code": "recommendation_strength",
          "name": "Recommendation Strength",
          "pillar": "visibility",
          "max": 10.0,
          "score": null,
          "applicable_max": 0.0,
          "state": "not_measured",
          "reason": "no unprompted question answered on this surface",
          "numerator": null,
          "denominator": null,
          "source": "soa_coded_mentions, answered unprompted runs",
          "parts": "… (cut)",
          "by_surface": "… (cut)"
        }
      ]
    },
    {
      "code": "accessibility",
      "name": "Accessibility",
      "max": 18.0,
      "score": 7.5,
      "applicable_max": 13.0,
      "dimensions": [
        {
          "code": "agent_access",
          "name": "Agent Access",
          "pillar": "accessibility",
          "max": 5.0,
          "score": 5.0,
          "applicable_max": 5.0,
          "state": "measured",
          "reason": null,
          "numerator": 3,
          "denominator": 3,
          "source": "access run: measured agent identities",
          "parts": [
            {
              "half": null,
              "score": 5.0,
              "max": 5.0,
              "state": "measured",
              "numerator": 3,
              "denominator": 3,
              "source": "access run: measured agent identities",
              "reason": null,
              "line": "Agent identities through 3 of 3"
            }
          ],
          "by_surface": "… (cut)"
        },
        {
          "code": "catalog_context",
          "name": "Catalog & Context",
          "pillar": "accessibility",
          "max": 8.0,
          "score": 2.5,
          "applicable_max": 8.0,
          "state": "measured",
          "reason": null,
          "numerator": 6,
          "denominator": 19,
          "source": "reference read: json_ld with a GTIN",
          "parts": [
            {
              "half": null,
              "score": 2.5,
              "max": 8.0,
              "state": "measured",
              "numerator": 6,
              "denominator": 19,
              "source": "reference read: json_ld with a GTIN",
              "reason": null,
              "line": "Product markup with a GTIN 6 of 19 pages"
            }
          ],
          "by_surface": {
            "grounded_api": {
              "score": 2.5,
              "applicable_max": 8.0,
              "state": "measured",
              "reason": null,
              "parts": [
                {
                  "half": null,
                  "score": 2.5,
                  "max": 8.0,
                  "state": "measured",
                  "numerator": 6,
                  "denominator": 19,
                  "source": "reference read: json_ld with a GTIN",
                  "reason": null,
                  "line": "Product markup with a GTIN 6 of 19 pages"
                }
              ]
            }
          }
        },
        {
          "code": "protocol_feed",
          "name": "Protocol & Feed Presence",
          "pillar": "accessibility",
          "max": 5.0,
          "score": null,
          "applicable_max": 0.0,
          "state": "not_measured",
          "reason": "no domain checks on this cycle yet",
          "numerator": null,
          "denominator": null,
          "source": null,
          "parts": "… (cut)",
          "by_surface": "… (cut)"
        }
      ]
    },
    {
      "code": "true_value",
      "name": "True Value",
      "max": 50.0,
      "score": 12.8,
      "applicable_max": 21.0,
      "dimensions": [
        {
          "code": "price_truth",
          "name": "Price Truth",
          "pillar": "true_value",
          "max": 16.0,
          "score": 11.0,
          "applicable_max": 16.0,
          "state": "measured",
          "reason": null,
          "numerator": null,
          "denominator": null,
          "source": "reference read: a price; catalog tier, exact of scored",
          "parts": [
            {
              "half": "seen",
              "score": 7.0,
              "max": 7.0,
              "state": "measured",
              "numerator": 19,
              "denominator": 19,
              "source": "reference read: a price",
              "reason": null,
              "line": "Price in markup 19 of 19 pages"
            },
            {
              "half": "said",
              "score": 4.0,
              "max": 9.0,
              "state": "measured",
              "numerator": 1,
              "denominator": 5,
              "source": "catalog tier, exact of scored",
              "reason": null,
              "line": "Prices quoted exactly 1 of 5 scored"
            }
          ],
          "by_surface": {
            "grounded_api": {
              "score": 11.0,
              "applicable_max": 16.0,
              "state": "measured",
              "reason": null,
              "parts": [
                {
                  "half": "seen",
                  "score": 7.0,
                  "max": 7.0,
                  "state": "measured",
                  "numerator": 19,
                  "denominator": 19,
                  "source": "reference read: a price",
                  "reason": null,
                  "line": "Price in markup 19 of 19 pages"
                },
                {
                  "half": "said",
                  "score": 4.0,
                  "max": 9.0,
                  "state": "measured",
                  "numerator": 1,
                  "denominator": 5,
                  "source": "catalog tier, exact of scored",
                  "reason": null,
                  "line": "Prices quoted exactly 1 of 5 scored"
                }
              ]
            }
          }
        },
        {
          "code": "member_value",
          "name": "Member Value",
          "pillar": "true_value",
          "max": 8.0,
          "score": 1.8,
          "applicable_max": 5.0,
          "state": "measured",
          "reason": null,
          "numerator": null,
          "denominator": null,
          "source": "reference read: member_price; value tier, member price questions, exact of scored",
          "parts": [
            {
              "half": "seen",
              "score": 1.8,
              "max": 5.0,
              "state": "measured",
              "numerator": 7,
              "denominator": 19,
              "source": "reference read: member_price",
              "reason": null,
              "line": "Member price in markup 7 of 19 pages"
            },
            {
              "half": "said",
              "score": null,
              "max": 3.0,
              "state": "na",
              "numerator": null,
              "denominator": null,
              "source": "value tier, member price questions, exact of scored",
              "reason": "fewer than 2 mentions in the relevant opportunity set",
              "line": null
            }
          ],
          "by_surface": {
            "grounded_api": {
              "score": 1.8,
              "applicable_max": 5.0,
              "state": "measured",
              "reason": null,
              "parts": [
                {
                  "half": "seen",
                  "score": 1.8,
                  "max": 5.0,
                  "state": "measured",
                  "numerator": 7,
                  "denominator": 19,
                  "source": "reference read: member_price",
                  "reason": null,
                  "line": "Member price in markup 7 of 19 pages"
                },
                {
                  "half": "said",
                  "score": null,
                  "max": 3.0,
                  "state": "na",
                  "numerator": null,
                  "denominator": null,
                  "source": "value tier, member price questions, exact of scored",
                  "reason": "fewer than 2 mentions in the relevant opportunity set",
                  "line": null
                }
              ]
            }
          }
        },
        {
          "code": "deal_citability",
          "name": "Deal Citability",
          "pillar": "true_value",
          "max": 12.0,
          "score": null,
          "applicable_max": 0.0,
          "state": "not_measured",
          "reason": "its markup half is not measured, so the dimension is out of the applicable max",
          "numerator": null,
          "denominator": null,
          "source": "value tier, code and points questions, exact of scored",
          "parts": [
            {
              "half": "seen",
              "score": null,
              "max": 7.0,
              "state": "not_measured",
              "numerator": null,
              "denominator": null,
              "source": "reference read: incentive_in_markup (supply), json_ld_scanned pages",
              "reason": "supply serves no incentive in markup on its page reads (a supply before #21)",
              "line": null
            },
            {
              "half": "said",
              "score": null,
              "max": 5.0,
              "state": "na",
              "numerator": null,
              "denominator": null,
              "source": "value tier, code and points questions, exact of scored",
              "reason": "fewer than 2 mentions in the relevant opportunity set",
              "line": null
            }
          ],
          "by_surface": "… (cut)"
        },
        {
          "code": "value_protocols",
          "name": "Value Protocols",
          "pillar": "true_value",
          "max": 14.0,
          "score": null,
          "applicable_max": 0.0,
          "state": "not_measured",
          "reason": "no domain checks on this cycle yet",
          "numerator": null,
          "denominator": null,
          "source": null,
          "parts": "… (cut)",
          "by_surface": "… (cut)"
        }
      ]
    }
  ],
  "biggest_gap": {
    "dimension": "Catalog & Context",
    "code": "catalog_context",
    "points": 5.5,
    "line": "Product markup with a GTIN 6 of 19 pages",
    "surface": null,
    "numerator": 6,
    "denominator": 19
  },
  "metric_surface": "grounded_api",
  "metric_counts": {
    "grounded_api": {
      "tier": "all",
      "agent_set": [
        "chatgpt",
        "gemini"
      ],
      "first": {
        "value": 6,
        "of": 7
      },
      "share": {
        "value": 6,
        "of": 7
      },
      "program": {
        "value": 0,
        "of": 6
      },
      "exact": {
        "value": 1,
        "of": 5
      },
      "terms": {
        "value": 0,
        "of": 0
      }
    }
  },
  "coverage": {
    "surfaces": 1,
    "questions": 6,
    "agents": 2,
    "runs": 7,
    "line": "1 surface, 6 questions, 2 agents · pooled across surfaces, equal weight"
  },
  "inputs": {
    "merchant": "wiggle-and-snug",
    "reference_run": {
      "id": 7,
      "status": "done",
      "started_at": "2026-10-14T17:00:00+00:00",
      "finished_at": "2026-10-14T17:02:00+00:00",
      "counts": {},
      "allow_hosted_render": true
    },
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
    "scored_at": "2026-10-15T21:23:36.733873+00:00"
  },
  "read_errors": {},
  "rules": "… console_score.TEMPLATES (cut)",
  "stored": false,
  "previous": null,
  "metrics": [
    {
      "key": "first",
      "name": "First recommendation",
      "value": 6,
      "denominator": 7,
      "surface": "grounded_api",
      "surface_note": "on the grounded API, every answered question",
      "delta": null,
      "delta_reason": "First cycle. Changes appear from the next one.",
      "by_surface": {
        "grounded_api": {
          "value": 6,
          "of": 7
        }
      }
    },
    {
      "key": "share",
      "name": "Share of answers",
      "value": 6,
      "denominator": 7,
      "surface": "grounded_api",
      "surface_note": "on the grounded API, every answered question",
      "delta": null,
      "delta_reason": "First cycle. Changes appear from the next one.",
      "by_surface": {
        "grounded_api": {
          "value": 6,
          "of": 7
        }
      }
    },
    {
      "key": "program",
      "name": "Program named when the brand is named",
      "value": 0,
      "denominator": 6,
      "surface": "grounded_api",
      "surface_note": "on the grounded API, every answered question",
      "delta": null,
      "delta_reason": "First cycle. Changes appear from the next one.",
      "by_surface": {
        "grounded_api": {
          "value": 0,
          "of": 6
        }
      }
    },
    {
      "key": "exact",
      "name": "Prices quoted exactly",
      "value": 1,
      "denominator": 5,
      "surface": "grounded_api",
      "surface_note": "on the grounded API, catalog tier, exact of scored",
      "delta": null,
      "delta_reason": "First cycle. Changes appear from the next one.",
      "by_surface": {
        "grounded_api": {
          "value": 1,
          "of": 5
        }
      }
    },
    {
      "key": "terms",
      "name": "Program terms right",
      "value": 0,
      "denominator": 0,
      "surface": "grounded_api",
      "surface_note": "on the grounded API, value tier, exact of scored",
      "delta": null,
      "delta_reason": "First cycle. Changes appear from the next one.",
      "by_surface": {
        "grounded_api": {
          "value": 0,
          "of": 0
        }
      }
    }
  ]
}
```

### The W&S fixture, by hand

One pooled surface, the grounded API (the consumer UI's one run is `no_ai_answer`: left out).

| pillar | dimension | from the fixture | points | applicable |
|---|---|---|---|---|
| Visibility | Share of Mentions | no unprompted question asked | not measured | 0 of 22 |
| | Recommendation Strength | the same | not measured | 0 of 10 |
| Accessibility | Agent Access | OAI-SearchBot, Googlebot, PerplexityBot through; Claude-User has no verified UA, the Parleo control is not an agent: 3 of 3, 3/3 × 5 | 5.0 | 5 |
| | Catalog & Context | 19 pages, all `json_ld`, 6 with a GTIN: 6/19 × 8 = 2.53 | 2.5 | 8 |
| | Protocol & Feed | no probe | not measured | 0 of 5 |
| True Value | Price Truth | seen 19/19 × 7 = 7.0. Said: 5 scored catalog runs, 1 exact, 20%, rate band 0.40 × 9 = 3.6, the scorer's round: 4 | 11.0 | 16 |
| | Member Value | 7 pages with a member price, so `member_value_applicable`. Seen 7/19 × 5 = 1.84. Said: no value question, the scorer's `na`, so `dimension_max` is the seen 5 | 1.8 | 5 |
| | Deal Citability | no seen source, the whole dimension out | not measured | 0 of 12 |
| | Value Protocols | no probe | not measured | 0 of 14 |
| | | | **20.3** | **34** |

20.3 ÷ 34 × 100 = 59.7, rounded once: **60**. Not measured: 32 + 5 + 12 + 14 = 63 points (and 3 more
rescaled away with Member Value's thin said half), so 100 − 63 − 3 = 34, and no readiness verdict.
Biggest gap: Catalog & Context, 8 − 2.5 = 5.5 points, "Product markup with a GTIN 6 of 19 pages".

The two-surface case (`tests/test_console_2c3.py::test_the_pooled_score_is_the_mean_of_the_surface_scores`)
adds unprompted and value-tier runs on both surfaces: the grounded API earns 45.3 of 69 (65.65), the
consumer UI 48.3 of 69 (70.0), and the pooled score is (65.65 + 70.0) ÷ 2 = 67.8, **68**. Its docstring
has every dimension.

### 2C-3a: the 500 on cycle 229, and the rules it left

**What it was.** `GET /api/console/score` on production cycle 229 (`FL3-wiggle-and-snug-20261014`)
answered 500 before any supply call. The cause was a query, not the cycle's data: `load_score_runs`
read the questions' expectation types with `SELECT DISTINCT q.query_code, q.expected_answer`, and
`soa_queries.expected_answer` is a Postgres `json` column. `json` has no equality operator, so Postgres
refuses `DISTINCT` over it, on any cycle and even on an empty table:
`sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedFunction) could not identify an equality
operator for type json`. The console tests run on sqlite, where the column is TEXT, so the W&S fixture
never saw it. Every cycle was a 500 in production, not only 229. Fix: one row per question the cycle
asked, by `WHERE q.id IN (SELECT r.query_id FROM soa_runs r WHERE r.cycle_id = :c)`, no `DISTINCT`.

**The 229-shaped fixture.** `tests/console_fixture_229.py` builds a cycle shaped like 229 in every way
the W&S fixture is not, and a test pins each count:

| | |
|---|---|
| questions | 87 in the study, 86 asked, 3 runs each on ChatGPT and Gemini: 516 runs, 514 answered |
| tiers | unprompted 300 runs, brand-direct 66, catalog 114, value 36 |
| surfaces | the grounded API answered; the consumer UI ran 2 runs, both errored: no answer on it |
| unprompted Layer 1 | ours named 0 times (no mention to code), Pampers 80 named / 38 first, Huggies 71 / 24, Pull-Ups 3 / 3, 26 first picks outside the comparison set |
| catalog | 9 exact of 41 scored, 34 `absent` with `other_brand`, 0 unverifiable |
| value | Member+ 9 of 18, codes 6 of 6, points 3 of 6 |
| brand-direct | 26 fabricated, 12 echoed, 8 misattributed, 14 acknowledged_unknown, 5 absent, 1 grounded |
| previous | `20260915-113207-wiggle-snug-full`, ChatGPT only, no stored score (or one stored under v5) |
| score columns | present, both NULL |

`tests/test_console_2c3a.py` runs every test on sqlite and, when `SOA_TEST_PG_URL` names a local
Postgres, on the same schema with production's types (`seed_console_db(engine, pk=..., json='JSON')`).
The Postgres run reproduces the 500 on `main`; the sqlite run never did.

**The rules, each tested on that fixture.**

- **A surface with no answers** is left out of the pool and named in coverage: `coverage.ran_no_answers`,
  and the line ends "· the consumer UI ran, no answers". The pooled score is the mean over the surfaces
  that scored.
- **A brand named zero times** scores Visibility as a measured 0 (0 of 22, 0 of 10): the Audit's own
  functions score absence as the failure, not as unmeasured.
- **First read** on a cycle with NULL score columns computes, stores and returns in one request; the
  second read serves the row without computing.
- **`previous.comparable`** is false, with the reason, when the earlier cycle has no stored score or was
  stored under another scorer version.
- **Never a 500 for a cycle in scope.** A failure while scoring is a 422 whose detail is one line the
  tile shows: `Score unavailable: <step> failed (<exception type>)`.

**Logging.** One JSON line per event, logger `app.services.console_score`: `score.start` (cycle,
cycle_id, org, why: first read, stale or rescore), `score.end` (cycle, org, surfaces scored, score,
stored, read errors, `ms`) and `score.failed` (cycle, cycle_id, org, the step, the exception type and
its message, at most 200 characters, no row data). A read served from the stored row logs nothing.

**Deploy.** A redeploy of soa only: no migration (`f3b8d2a6c4e1` is already applied), no console change
(the tile already shows the 422's detail as its error).

## 2D: three fixes before the next full loop

### 2D-1: Postgres in CI, and the json-column sweep

**CI.** `.github/workflows/ci.yml` (the repo had no workflow) runs the api and pipeline suites on every
push and PR, each beside a `postgres:17` service container, with `SOA_TEST_PG_URL` pointing at it.
Production's Postgres version is not recorded in the repo docs, so the image is the current Supabase
major; change it if production's differs. `DATABASE_URL` is a dead local port, so a test that forgot to
swap in its own engine fails rather than reaching anything. No secrets.

**The harness.** `packages/testing/soa_pg_harness.py`, imported by both suites' conftests:
`sqlite_engine()`, `postgres_engine()`, `model_schema(engine)` (every soa_shared model's table with
production's types), and the fixtures `any_engine` (each test on sqlite, then Postgres) and `pg_engine`.
`SOA_TEST_PG_URL` unset: the Postgres runs skip locally and **fail under GitHub Actions**. Set to a host
that is not local: fail (each test drops the public schema). Set and unreachable: fail, never skip.

**The sweep.** Every `json` column in the soa_shared models (41, none `jsonb`), against every
`DISTINCT`, `GROUP BY`, `UNION`, `IN (subquery)` and `=` in `apps/api/app` (read models and routers),
`soa_shared` and the rescore script. Each hit has a test in `apps/api/tests/test_pg_json_sweep.py` that
calls the real function on both databases over the full model schema.

| statement | where | lands on json? | Postgres |
|---|---|---|---|
| `SELECT DISTINCT e.* FROM soa_entities e JOIN soa_cycle_entities ...` | `GET /api/console/studio/entities` | **yes, `soa_entities.aliases`** | **failed** (`UndefinedFunction`), fixed: `WHERE e.id IN (SELECT ce.entity_id ...)` |
| `SELECT q.query_code, q.expected_answer ... WHERE q.id IN (SELECT r.query_id ...)` | `console_score.load_score_runs` (#111's fix) | selected, not compared | passes |
| `SELECT DISTINCT study_pattern FROM soa_queries` | `POST /api/cycles` | no (text) | passes |
| `COUNT(DISTINCT cm.run_id)` | `public_lite._fetch_live_progress_counts` | no (integer) | passes |
| `SELECT DISTINCT query_id`, `COUNT(DISTINCT query_id)` | `transcript_pick._fetch_query_index_map` | no (integer) | passes |
| `GROUP BY r.platform`, `COUNT(DISTINCT r.id)` | `full_analysis_extras._fetch_platform_signals` | no | passes |
| `GROUP BY ce.comparison_code, cm.position` | `GET /api/cycles/{code}/positions` | no | passes |
| `GROUP BY q.study_type, q.category, q.study_pattern`, `GROUP BY c.study_type`, `GROUP BY study_pattern` | `GET /api/studies`, `GET /api/studies/{type}/queries` | no | passes |
| `GROUP BY r.id` (twice each) | `cycle_scoring._fetch_run_signals`, `lite_score_batch._fetch_run_signals_batch` | no (aggregates only) | passes |
| `GROUP BY tier, platform, outcome`, `... source_attribution`, `GROUP BY q.tier, r.platform`, `GROUP BY tier` | `tier_accuracy` | no | passes |
| `GROUP BY COALESCE(o.surface, r.surface), o.platform, o.outcome`, `GROUP BY surface, platform, status, answer_status` | `soa_shared.surface_accuracy` | no | passes |
| ORM `group_by(entity_id, platform)` | `finding_detector.detect_vis_01` | no | passes |
| `GROUP BY tier, outcome` | `scripts/rescore_cycle.outcome_counts` | no | passes (2D-3's fixture, both databases) |

No `UNION` and no `=` against a json column anywhere in those paths; the only `IN (subquery)` is
#111's. **CI goes red on #111's `DISTINCT`**: proven with a throwaway commit on the 2D branch that put
it back (the PR body has the run), then dropped.

### 2D-2: surface aliases

**The resolution table before 2D** (read from `main` at 376d7d5, before any change). A *name* is what a
caller sends; the *runner* is the class that runs it; *stored* is what lands on the cycle and on each run.

| where a name is resolved | `gemini` | `gemini_grounded` | `gemini_api` | unknown name | stored |
|---|---|---|---|---|---|
| runner registry, `runners/run_orchestrator._RUNNER_CLASSES` | not a key | `GeminiGroundedRunner` | `GeminiApiRunner` | not a key | - |
| `run_orchestrator.PLATFORM_ALIASES` / `normalize_platforms`, applied when a cycle **runs** | **`gemini_grounded`** (grounded) | itself | itself | passed through, then `ValueError` "Unknown platforms" | `soa_runs.platform` = the aliased id, `surface` = its surface |
| `RunOrchestrator` default (no platforms) | - | in the default four | - | - | - |
| `worker.py` cycle with NULL `platforms` | - | `[chatgpt, gemini_grounded]` | - | - | - |
| `POST /api/cycles`, `CreateCycleRequest.ground_gemini` | **`gemini_grounded`** | itself | itself | **accepted as sent** | `soa_cycles.platforms` |
| `POST /api/console/cycles` | via `CreateCycleRequest`: `gemini_grounded` | itself | itself | 422 from `surfaces.unavailable_reason` ("unknown surface") | `soa_cycles.platforms` |
| `POST /api/full-loop`, `/api/console/full-loop` | **accepted and stored as `gemini`** (`surfaces.LEGACY` has no unavailable reason) | itself | itself | 422 ("unknown surface") | `soa_full_loop_requests.platforms` as sent |
| `fullloop/coordinator._create_cycle` | **passed through: `soa_cycles.platforms = ["gemini"]`** | itself | itself | passed through | `soa_cycles.platforms` as the request had it |
| lite worker cycle creation | - | - | - | - | `["chatgpt"]` |
| `GET /api/console/surfaces`, `/api/console/studies/options` `surfaces` (`surfaces.modal_list`) | never listed | listed, "API with search grounding" | listed, "API, no tools" | - | - |
| reading a stored row: `surfaces.get` / `surface_of` / `agent_of` | `LEGACY`: `api`, agent gemini | `grounded_api` | `api` | `None` | - |
| console read models' surface grouping, `console_parity._surface_of` | the row's stored `surface`, else `surface_of(platform)`: `api` | `grounded_api` | `api` | `unlabelled` | - |

So the alias was resolved at **run** time, not at creation, and in two different places to the same
grounded runner. Cycle 229 was created by the full loop with `["gemini"]` stored on the cycle, and its
runs landed on `gemini_grounded` / `grounded_api`. The September cycle's `gemini` runs predate the alias
(`platform = 'gemini'`, `surface = 'api'`). Same stored cycle name, two surfaces.

**After 2D.** One resolver, `soa_shared/surfaces.resolve` (`ALIASES = {"gemini": "gemini_api"}`, explicit
and complete), used at creation by every path and by the orchestrator:

| where | `gemini` | `gemini_grounded` | `gemini_api` | unknown name | stored |
|---|---|---|---|---|---|
| `soa_shared/cycle_creation.create_cycle_with_comparison_set` (every caller) | `gemini_api` | itself | itself | `UnknownSurface`, nothing written | `soa_cycles.platforms` = resolved ids, `soa_cycles.surfaces` = `{id: surface}` (migration `a7d2c9e4b1f6`) |
| `POST /api/cycles` (`CreateCycleRequest.resolve_surfaces`) | `gemini_api` | itself | itself | **422** | as above |
| `POST /api/console/cycles` | `gemini_api` | itself | itself | **422** | as above |
| `POST /api/full-loop`, `/api/console/full-loop` | `gemini_api` | itself | itself | **422** | `soa_full_loop_requests.platforms` = resolved ids |
| `fullloop/coordinator._create_cycle` | `gemini_api` (a pre-2D request) | itself | itself | the request fails, with the reason | as above |
| `run_orchestrator.normalize_platforms` (`PLATFORM_ALIASES` is gone) | `gemini_api`, logged as an alias | `GeminiGroundedRunner` | `GeminiApiRunner` | `ValueError` | `soa_runs.platform` = the id, `surface` = its surface |
| `GET /api/console/surfaces`, `/studies/options` | never listed | listed with its fidelity | listed with its fidelity | - | - |
| reading stored rows (`surfaces.get`, `_surface_of`) | unchanged: `LEGACY` `gemini` is `api` | unchanged | unchanged | unchanged | - |

There is no fallthrough from a bare name to a grounded runner. **The next W&S full loop lands where 229
did only if it asks for `gemini_grounded` by name**; `gemini` now runs the ungrounded API, which is where
the September rows are. The Create Study picker (truesync `apps/console/src/screens/Studio.tsx`) already
renders `/api/console/surfaces` as served, id, label, surface label and fidelity, so it needs no change.

`soa_cycles.surfaces` is not mapped on `SoaCycle`, and `store_surfaces` writes it only when the column
exists (a warning otherwise), so the deploy does not depend on the migration; apply it to record the
surface on new cycles. Existing rows are not rewritten.

**Where the drift is: `scripts/report_surface_drift.py`.** Read only (one SELECT, one GROUP BY, a READ
ONLY transaction on Postgres). Per cycle: the stored names, what each means now, and the
`(platform, surface, runs)` its rows carry under the name, under what it means now, and under what it
meant before 2D. On the 229-shaped fixture as built (it stores the resolved `gemini_grounded`):

```
cycle FL3-wiggle-and-snug-20261014 (id 229)   DRIFT
  stored platforms: ["chatgpt", "gemini_grounded"]   stored surfaces: (none, created before 2D)
  chatgpt          means now: chatgpt (grounded_api)
      rows: chatgpt on grounded_api x 258   ok
  gemini_grounded  means now: gemini_grounded (grounded_api)
      rows: gemini_grounded on consumer_ui x 2   DRIFT: on consumer_ui, the name now means grounded_api
      rows: gemini_grounded on grounded_api x 256   ok
```

(the 2 consumer_ui rows are the fixture's two errored runs, labelled consumer_ui under the API id). With
229 as production stores it, `["chatgpt", "gemini"]`, the same rows print:

```
  gemini           means now: gemini_api (api)
      rows: gemini_grounded on consumer_ui x 2   DRIFT: on consumer_ui, the name now means api
      rows: gemini_grounded on grounded_api x 256   DRIFT: on grounded_api, the name now means api
```

and a September-shaped cycle's `gemini` rows print `rows: gemini on api x N   ok`. Relabelling 229 is a
separate decision; nothing here rewrites it.

### 2D-3: the brand's own domains, tenant-wide

**The rule.** A brand-direct answer is `grounded` when it cites one of *ours*, or a claim it asserts is
backed by a platform grounding support whose source is one of ours or a listed retailer. Since 2D, *ours*
is the merchant's own domains (its record's `own_domains`, else its one domain, else the expectation's)
**plus every own domain of every merchant in its tenant**. Wiggle & Snug's store (trueshopstore.com) and
its brand site (wiggleandsnug.com) are two supply merchants, so the store's list holds only the store, and
cycle 229 run 12979, which cited wiggleandsnug.com, scored `echoed` on the store's cycle.

- **The set.** `TrueSyncCatalogClient.tenant_own_domains`: one `GET /tenant`, then
  `GET /merchants/{slug}/retailers` per merchant, its `own_domains` list, else the deprecated single
  `own_domain`. Normalized (`www.`, scheme and path dropped), in tenant order, each once. Read with the
  study's customer's token, so "the tenant" is that customer's.
- **Once per scoring pass, cached on the cycle.** `expectation_scorer.TenantDomainsCache.for_cycle`, by
  cycle id, for the life of the scorer (one live batch, or one rescore). It rides on the brand facts as
  `tenant_own_domains`, for the brand-direct tier only.
- **Degrading.** A merchant whose `/retailers` read fails is left out and named in a warning; a failed
  `/tenant` read gives the rule before 2D (the merchant's own list). A refusal raises, as every catalog read.
- **Every ownership check.** `brand_direct_classifier.ours` is read by all of them: the ownership claim
  ("their official website is X") and the no-source check in `contradicted_claims` (through
  `grounding_domains`), and the two grounded checks in `classify_with_code`. So a claim backed by a
  support at the tenant's other site is sourced, not `fabricated`, and an answer citing that site is
  `grounded`. The rule can move `echoed` and `fabricated` rows to `grounded`. (First landed with the
  grounded checks only; widened in the fourth 2D commit.)
- **Reason codes.** `tenant_own_domains` when the site that grounds the answer (cited, or a support's
  source) is another merchant's; `own_domains`, `grounding_support` or none, as before, when it is the
  merchant's own or a listed retailer. `rescore_cycle.py` names `tenant_own_domains`, so the
  unattributed-moves guard passes it.
- **Not the classifier.** `expectation_comparator`'s `source_split` (own / listed retailer / other, a
  report field) still splits on the merchant's own list.

**Golden gates.** Both untouched and passing. No verdict golden row depends on the single-merchant rule:
r43 *is* run 12979, and expects `grounded` / `own_domains` because its `record_facts` list both domains on
the store's own record; with no `tenant_own_domains` on a golden row, the classifier reads it exactly as
before.

**The rescore, on the 229-shaped fixture** (`tests/test_tenant_own_domains.py`: golden rows r40-r45, 229's
Gemini answers with their grounding, and two ChatGPT rows, stored with the outcomes the store-only record
gives; supply's `/tenant` and `/retailers` recorded, the store answering with the deprecated single field):

```
cycle FL3-wiggle-and-snug-20261014 (id 229) — classify-only: no model call; Layer 1 and the stored Layer 2 extraction are read as they are
before:
    brand_direct            8  (acknowledged_unknown 1, echoed 1, fabricated 4, grounded 2)

classified 8 stored row(s) twice; both passes agree

rows whose outcome moved: 2 of 8
    WIG_141 · gemini_grounded · run 1: fabricated -> grounded   [brand-direct: every own domain of every merchant in the tenant is ours (2D)]   [run 12975]
    WIG_144 · gemini_grounded · run 1: echoed -> grounded   [brand-direct: every own domain of every merchant in the tenant is ours (2D)]   [run 12979]

unattributed moves: 0

dry run — nothing written.
```

The write on the same fixture moves only those two (`reason_code = tenant_own_domains` on both).
Fabricated goes from 4 to 3; the three left are r41 (support at huggies.com), r42 (a redirect that never
resolved) and r45 (tiers the record does not publish).

**For production (Elton runs these; nothing here touched production).** From `apps/pipeline`, on this
branch's code, dry run first:

```
python3 scripts/rescore_cycle.py --cycle FL3-wiggle-and-snug-20261014 --tier brand_direct --classify-only --dry-run
```

Expected: runs 12979 (`echoed -> grounded`) and 12975 (`fabricated -> grounded`) move under "every own
domain of every merchant in the tenant is ours (2D)", with `unattributed moves: 0`; fabricated drops by
one. Any other row that moves under the same rule is the same case (a wiggleandsnug.com citation, support
or ownership claim on the store's cycle) and is expected. If a row moves under any other rule, or is
unattributed, stop. Then the write, which still refuses while any move is
unattributed and re-checks that two passes agree:

```
python3 scripts/rescore_cycle.py --cycle FL3-wiggle-and-snug-20261014 --tier brand_direct --classify-only
```

If the dry run moves nothing, the store and the brand site are not both in the study's customer's tenant
(`GET /tenant` with that token lists the merchants it reads).

## 2E: the three dimensions 2C-3 left unmeasured

Cycle 229's Share of Algorithm was 20.3 of 69 applicable: Protocol & Feed Presence (5), Value Protocols
(14) and Deal Citability (12), 31 points, read "not measured", and the readiness verdict was withheld. 2E
measures all three. Two come from the Audit's own domain checks, run from the worker against the
merchant's own domains; one from supply #21's incentive-in-markup flags. One implementation of each
check, the Audit's: nothing under `apps/pipeline/scan/`, `lite_pillars.py` or `scan_dimensions.py`
changed, and their tests have no diff.

### The Audit functions, and how the loop supplies their inputs

| dimension | Audit function, called | the input it reads | how the loop supplies it |
|---|---|---|---|
| Protocol & Feed Presence (5) | `scan/scorer.score_protocol_feed(pages, site_type_result, short_circuited)` (v2's `score_f3_protocol_feed_presence`, rescaled onto 5) | the `llms_txt` and `mcp_well_known` pages (status, body, content type), every page's `agentic_protocol_hints`, the site type, the short-circuit flag | `apps/pipeline/scoring/domain_checks.py` fetches `/llms.txt` and `/.well-known/mcp.json` on the merchant's own domain, the store root and one product page (from the reference read the cycle was scored against), extracts the hints with `structured_data.extract`, types the site with `site_typing.classify_site` |
| Value Protocols (14, seen only) | `scan/scorer.score_value_protocols(pages, short_circuited)` | the `mcp_well_known` page | the same fetch |
| Deal Citability, seen (7) | none: the Audit's `score_deal_citability_seen` reads v4 value-rails markup on the pages it crawled | | supply #21's `incentive_in_markup` on the reference read (below) |
| Deal Citability, said (5) | `cycle_scoring_full.score_deal_citability_said_full` | | unchanged from 2C-3 |
| Agent Access (5) | `scan/scorer.score_f1_agent_access(discovery, pages, divergence_evidence)` | a robots.txt fetch and its parser, the product pages, the matrix's divergence lines: **not** a per-token roll-up | unchanged. `robots_names_agents` feeds the Accessibility row only |

**Called, not forked.** Every fetch is the scan's own `fetcher.fetch`: the honest UA, robots.txt honoured
(a product page robots.txt disallows is not fetched and the probe says so), the SSRF guard on every hop,
challenge detection, and Web Bot Auth signing when the worker has its key. The adapter fetches only what
the two checks read (no sitemap walk: `discover_pages` is not called), and keeps one of discovery's
policies as it has it: when robots.txt and the store root both answer 403/429, nothing more is requested
and both checks score that as the Audit's short circuit.

**Where it runs.** On the worker, at scoring time: orchestrator stage 2d (`_run_domain_checks`), after
Layer 2 scoring, once per cycle, for a cycle whose questions name a merchant. Its own domains are supply
`/retailers`' `own_domains` (#20), else the deprecated `own_domain`, else the tenant record's domain; for a
brand merchant that is the brand site. Every own domain is checked and recorded; the first (the
merchant's own site, as the Audit scans one store) is the one scored. A cycle that already holds a record
keeps it, and the stage never raises.

**The record**, `soa_cycles.domain_checks` (JSON, migration `b4e8f1c3a9d2`), is the raw input, not only
the result, so the score of record is reproducible:

```jsonc
{
  "version": {"scan": "5", "extraction_rev": "2", "adapter_revision": 1},  // scan_dimensions.SCORER_VERSION, as engine.py stamps a scan
  "checked_at": "2026-10-16T09:00:00+00:00",
  "merchant": "wiggle-and-snug", "own_domains": ["trueshopstore.com"], "scored_domain": "trueshopstore.com",
  "reference_rows_from": "cycle",                 // soa_cycles.reference_prices, else supply's current read
  "domains": [{
    "domain": "trueshopstore.com", "origin": "https://trueshopstore.com", "short_circuited": false,
    "fetches": [                                   // kind, url, status, http_status, content_type, body, ...
      {"kind": "llms_txt", "status": "not_found", "http_status": 404, "body": "nf", "...": "..."},
      {"kind": "mcp_well_known", "status": "not_found", "http_status": 404, "...": "..."},
      "… robots, homepage, product, product_unsigned (bodies never stored for a page we read)"
    ],
    "agentic_protocol_hints": [], "site_type": {"site_type": "commerce_normal", "reason": "…", "signals": ["…"]},
    "protocol_feed": {"score": 0.0, "max": 5, "coverage": "partial", "evidence": ["/llms.txt not found (404)", "…"]},
    "value_protocols": {"score": 0.0, "max": 14, "coverage": "full", "evidence": ["no protocol profile found"]},
    "signed_probe": {"outcome": "both_in", "url": "…", "signed": {"status": "fetched", "http_status": 200}, "unsigned": {"…": "…"}}
  }],
  "protocol_feed": "… the scored domain's", "value_protocols": "…", "signed_probe": "…", "errors": []
}
```

Bodies are kept for the two protocol files only (llms.txt cut to 2,000 characters, which keeps every
fact its check reads: non-empty, not an HTML document, the content type; a manifest whole up to 64 KB).
`domain_checks.score_entry` rebuilds the scan's pages from the record and calls the two functions; the
live run scores through the same function, so a stored record re-scores to the stored numbers
(`test_a_stored_record_rescores_to_the_same_numbers`, on every Audit fixture case).

**The signed-agent probe** is not an Audit dimension and never enters the score. The product page is
fetched twice, the same UA: signed (the worker's Web Bot Auth key) and unsigned (the signing module's
own `WEB_BOT_AUTH=off` switch, for that one request, restored after; sent once, a refusal is not
retried). Outcomes: `both_in`, `signed_only`, `unsigned_only`, `neither`, or `not_checked` with the reason
(no key on the worker, no product page on the own domain in the reference read, robots.txt disallows it,
the short circuit, or the page did not answer).

### Supply #21's fields, read tolerantly

`apps/api/clients/truesync_client.py`: `incentive_in_markup(row)`, `carries_incentive_fields(rows)`,
`robots_by_domain(payload)`, `token_rules(grid_row)`. A row or payload without the fields (a supply before
#21), with them null, or malformed reads as None, "not measured", never an error and never a false.

**Deal Citability, seen** = reads whose page carries any flag true ÷ pages read whose markup supply
scanned (`json_ld_scanned: true`), × 7. A read stored before 2A-3 and not backfilled
(`json_ld_scanned: false`) is out of both counts. No row carries the field: `not_measured`, "supply serves
no incentive in markup on its page reads (a supply before #21)". Rows carry it but none was scanned:
`not_measured`, "no page read has had its markup scanned for incentives yet". Either way the Audit's
`seen_blocked` rule still takes the whole dimension out, said shown and uncounted. Its parts carry the four
flags' counts as `checks` ("promo 3 of 19 pages").

### Measured, the applicable max and the verdict

With a domain-check record on the cycle and a supply that serves the fields, all three dimensions are
`measured`, the applicable max reaches 100, and the readiness verdict is the Audit's `compute_verdict`, as
is. The Audit's own `na` on a domain check (Protocol & Feed on a brand-only site) leaves its points as
Member Value's `na` does and does not withhold the verdict. The dimension rows of the two domain checks
carry the Audit's sub-checks by name (`lite_pillars._protocol_feed_checks`, `_value_protocols_checks`: the
labels are `scan_dimensions`' `how_measured`) in `parts[].checks`, with `parts[].evidence` the scorer's lines.

On the 229-shaped fixture (`tests/test_console_2e.py`):

| case | applicable | earned | score | verdict |
|---|---|---|---|---|
| everything measured: the "full" record (3.8 + 14), supply #21 rows with 10 of 19 pages flagged | **100** | 22.3 + 3.8 + 14 + (3.7 + 5.0) = 48.8 | 49 | NOT AGENT-READY |
| the same record, supply before #21 (Deal Citability not measured) | **88** | 40.1 | 46 | withheld, 12 points |
| no domain checks yet, supply #21 rows | 81 | | | withheld, 19 points |

### The score of record: a second recompute trigger

2C-3 recomputes a stored score when its `scorer_version` (or the adapter's revision) is not the current
one. 2E adds: **the set of measured dimensions changed**. The stored body carries `measured` (the codes it
counted) beside the score. On each read, the cycle row says which of the two domain-check dimensions its
record makes measured, with no supply call; when that differs from the stored set, the read recomputes
(`needs_recompute`: `first read`, `stale`, `measured set changed`; the log's `score.start` names it). The
value it replaces is kept in the row's `history` (newest last, ten at most: score, earned, applicable
max, measured, scorer version, adapter revision, `scored_at`, `pillars` (2I-2: each pillar's code, score
and applicable max), `replaced_because`), so the report can show both. Deal Citability's set moves with
supply, which the cycle row cannot see: a supply deploy is picked up by the next recompute, or an
operator's `?rescore=true`.

2I-2: across a scorer version, `replaced_because` is "scorer 6 → 7: ungrounded surfaces excluded from
pooling" only when the new score's `coverage.ungrounded` is non-empty and the score moved. Otherwise it is
"scorer 6 → 7", plus " · domain checks changed", " · reference read changed" or " · incentive flags
changed" for each input the two stored bodies show differs (`inputs.domain_checks.revision`,
`inputs.reference_run`'s `read_at` else `finished_at`, Deal Citability's seen half and its flag checks).
An input the old body does not carry is not compared. 229 (every run grounded) reads "scorer 6 → 7 ·
reference read changed" when its stored score used an older reference read, never the ungrounded line.

`ADAPTER_REVISION` is 2 (the three mappings changed), so every score stored under 2C-3 recomputes once on
its first read after the deploy, keeping the old value in its history.

### Comparability: applicable points changed

Two cycles stay comparable on 2C-2a's rule (the same pooled surfaces, the same agents on each, the same
scorer version). When they are comparable but their applicable max differs, `previous` carries
`applicable_note`, "applicable points changed from N to M", beside the delta, and
`previous.dimension_deltas` lists a delta only for a dimension measured in both. With the same applicable
max the note is null and every dimension measured in both has its delta. Tested both ways: 69 against 100
(the six measured in both, each 0, and the line) and 100 against 100 (nine deltas, no line).

### Accessibility and Catalog

| row | value | source | not checked when |
|---|---|---|---|
| robots.txt names answer-time agents | "N of M" (", wildcard only" when no agent has its own group); ok at M, bad at 0 | supply #21 `robots_by_domain` on the merchant's own domain (the record's `own_domains`, else `/retailers`) | a supply before #21; no access run; the own domain not in the roll-up; N null (robots.txt challenged or errored) |
| Edge lets signed agents in | "signed and unsigned both read" / "signed read, unsigned refused" (ok), "signed refused, unsigned read" / "signed and unsigned both refused" (bad) | the newest in-scope cycle's domain checks for this merchant | no record; the probe's own reason |
| Protocol profile (UCP, MCP, llms.txt) | "UCP yes, MCP no, llms.txt yes" ("not verified" for the Audit's unverifiable sub-check) | the Audit's Protocol & Feed sub-checks on the record | no record; "not applicable" on a brand-only site |

`GET /api/console/accessibility` reads `/retailers` beside `/access` and `/reference` (three supply calls)
and returns `domain_checks: {cycle, checked_at, scored_domain}`. All seven checks carry a value or "not
checked" with the reason.

Catalog, "Retailers read for the study": each domain gains `incentive_in_markup: {pages, of}` (reads with
any flag over the reads supply scanned) and `incentive_note`, "Incentive in markup: N of M pages", or "not
checked, no read scanned yet", or "not measured, supply does not serve it yet".

### source_split, tenant-wide

`expectation_comparator`'s `source_split` (own domain / listed retailer / other, a report field on every
tier) now reads the tenant's own domains, the set 2D gave the brand-direct classifier: `classify` puts
`tenant_own_domains` on the facts for every tier, and `_decorate` adds them to the owned list. Off the
brand-direct tier a refused tenant read degrades to the merchant's own list (a report field, not a reason
to fail a price outcome); on it, a refusal still raises. No verdict moves (`test_source_split_tenant.py`;
both golden gates untouched and passing).

### Deploy note (migration `b4e8f1c3a9d2`, not applied)

`apps/pipeline/alembic/versions/b4e8f1c3a9d2_add_domain_checks_to_soa_cycles.py` adds one nullable column,
`soa_cycles.domain_checks JSON`, after `a7d2c9e4b1f6`. Additive, so safe to apply ahead of the deploy.
**This branch does not apply it.** Round-tripped on a throwaway local Postgres: the schema built from the
models at `a7d2c9e4b1f6` and stamped, then `scripts/migration_roundtrip.py --from a7d2c9e4b1f6` (upgrade,
downgrade, upgrade), a row written and read back, the downgrade dropping the column and keeping the row.

Either order works. Not mapped on `SoaCycle`: the worker writes it only when the column exists (stage 2d
logs that it skipped, otherwise), the console reads it off the row `cycle_in_scope` already selects, and
Accessibility reads it inside a try. Before the migration the two dimensions read "not measured", as
before 2E. Apply with

```
cd apps/pipeline && alembic upgrade b4e8f1c3a9d2
```

The worker's signed probe uses the key it already has (`BOT_SIGNING_KEY`); without one the row reads "not
checked: no Web Bot Auth key on the worker". The console needs no change to deploy in either order.

### Cycle 229: `scripts/run_domain_checks.py`

For a cycle scored before 2E. It runs `domain_checks.run_for_cycle` for one cycle, fetching the merchant's
live domains with the honest UA, journals every run (JSON lines, `./domain_checks_journal/<cycle>.jsonl`:
start, the record as it would be stored, the record it replaces, end), refuses a cycle that already
holds a record without `--replace`, and refuses to write before the migration. `--dry-run` fetches and
prints and writes nothing to the database. This session did not run it against anything but the fixture.

On the recorded Acme Baby store (`tests/fixtures/domain_checks/`, the Audit's own llms.txt and manifest
fixtures served at its paths, signing on):

```
cycle FL3-acme-baby-20261014 (id 229) — the Audit's domain checks, live fetches with the honest UA; no model call
merchant acme-baby   own domains: acmebaby.test   reference read from: cycle
  acmebaby.test   (scored)   site type commerce_normal
    robots            fetched           200  https://acmebaby.test/robots.txt
    homepage          fetched           200  https://acmebaby.test
    llms_txt          fetched           200  https://acmebaby.test/llms.txt
    mcp_well_known    fetched           200  https://acmebaby.test/.well-known/mcp.json
    product           fetched           200  https://acmebaby.test/products/overnight-diapers-size-3
    product_unsigned  fetched           200  https://acmebaby.test/products/overnight-diapers-size-3
    protocol_feed     3.8 / 5  coverage partial
      · /llms.txt present and non-empty
      · MCP endpoint declaration discoverable (well-known path)
      · UCP/UIP capability markup present
      · no agentic-commerce hints found in structured data
    value_protocols   9.0 / 14  coverage full
      · the manifest's capabilities list and specVersion resolve to the expected shape
      · declared protocol manifest version is current ('2025-01')
      · declares a UCP shopping-discount capability ('dev.ucp.shopping.discount')
      · does not declare a loyalty/member protocol extension
      · does not declare an ACP promotions capability
    signed probe      both_in

protocol_feed and value_protocols join the measured set on the next read of the score (not measured before); the previous value stays in the score's history.
dry run — nothing written.
journal: domain_checks_journal/FL3-acme-baby-20261014.jsonl
```

**For production (Elton runs these; nothing here touched production).** With the migration applied, from
`apps/pipeline` on this branch's code, with production's `DATABASE_URL`, `SOA_SECRET_KEY` (the study's
customer token is read as every catalog read reads it) and `BOT_SIGNING_KEY`, dry run first:

```
python3 scripts/run_domain_checks.py --cycle FL3-wiggle-and-snug-20261014 --dry-run
```

Expected: one own domain, trueshopstore.com, scored; robots.txt, the store root, `/llms.txt`,
`/.well-known/mcp.json` and one trueshopstore.com product page from 229's stored reference read, each with
its status; the two scores with the Audit's evidence lines; the probe's outcome. If the own domains are
not the store, or a fetch is refused where a browser is not, stop. Then the write:

```
python3 scripts/run_domain_checks.py --cycle FL3-wiggle-and-snug-20261014
```

and open the cycle's score: the read recomputes ("measured set changed") and keeps the previous value in
`history`. For Deal Citability's seen half the Oct 14 reads must have been scanned: they were stored
before 2A-3, so run supply's own backfill first (parleo-supply-app, #21:
`scripts/backfill_incentive_markup.py --merchant wiggle-and-snug --dry-run`, then without `--dry-run`).

### Cycle 229, expected after the checks

From the stored 20.3 of 69 (the six dimensions 2C-3 measured; this session read nothing from production,
and the 229-shaped fixture, built from counts, gives 22.3), adding:

- **Protocol & Feed Presence**: the Audit's checks on trueshopstore.com. The demo store's source in this
  workspace (truesync-demo-store) serves no `/llms.txt`, no `.well-known` route and no UCP/MCP markup; if
  that is what trueshopstore.com serves, all four sub-checks are verifiable and absent: **0 of 5**. Each one
  present is worth 5 ÷ (verifiable checks).
- **Value Protocols**: no manifest: **0 of 14** ("no protocol profile found").
- **Deal Citability**: said **5.0 of 5** (codes 6 of 6, points 3 of 6: 9 of 12, 75%, the v6 rate band's
  top). Seen = N ÷ 19 × 7 over the 19 Oct 14 reads once backfilled, N the reads whose page carries a flag:
  at least the 7 with a member price in JSON-LD, so **at least 2.6**.

| supply | applicable | earned | score | verdict |
|---|---|---|---|---|
| #21 deployed, the Oct 14 reads backfilled, only the member-price pages flagged | 100 | 20.3 + 0 + 0 + 2.6 + 5.0 = **27.9** | **28** | NOT AGENT-READY (28 < 60) |
| each further flagged read | 100 | about + 0.37 | | |
| #21 deployed, not backfilled (`json_ld_scanned: false` on every read), or not deployed | 88 | 20.3 | **23** | withheld, 12 points not measured |

Previous cycle: the September cycle has no stored score (2C-3a), so there is no delta to show; when a
comparable one has 69 applicable, the tile reads "applicable points changed from 69 to 100" beside it.

## 2E-2: two score-tile fixes from cycle 229

### Deal Citability's seen evidence

**What 229 showed.** "member price 19 of 19 pages: yes · promo 19 of 19 pages: yes".

**Why.** soa read each flag's value, not its presence. On #114's `prices[]` shape it reports exactly what
supply serves (`tests/test_console_2e2.py`). Supply serves each flag as its **JSON-LD half OR a text half** read from the
read's `offer_text` (`truesync/fullloop/incentive.incentive_in_markup`). `offer_text` is the first incentive-shaped
sentence on the page (`parse.offer_text`), and on trueshopstore.com that is the announcement bar on every page (the store's
`SiteChrome.tsx`): "Free shipping on orders of $35 or more · 30-day returns · Members earn …". Supply's text rules read
"free shipping" as `promo` and "Members earn" as `member_price`. So with a JSON-LD half of `member_price` only, supply serves
`promo: true` on every page, and soa printed it. The fixture `tests/fixtures/console/supply_retailer_prices_229_bar.json`
is #114's row builder with each row's `offer_text` and `incentive_in_markup` computed by supply's own two functions
(ef3c267) from that bar: it serves `{member_price: true, promo: true, source: json_ld}`. This session read nothing from
production. If 229's served rows say `promo: false`, the other cause is that the stored score predated the supply
response; the adapter revision below recomputes it either way.

**The fix.**
- **Seen count.** A page carries an incentive in markup only when a flag is true **and** supply's `source` is
  `json_ld` (the flag came from structured data). A page whose flags come from its text alone (`source: text`) is not
  counted, and stays in the denominator.
- **Per-flag checks.** Each flag reads its served value (false is `fail`). A flag that is true on pages that also carry
  `offer_text` says "the page text included", because there the served flag may be the text half. Supply serves the two
  halves only combined, so soa cannot split them per flag without restating supply's rules. A per-half field is a supply
  change.
- **Recompute.** `ADAPTER_REVISION` is 3, so every stored score recomputes once and keeps the old value in its history.

**229's seen half after the fix.** 19 of 19 pages, 7 of 7, if the 19 reads carry `member_price` in JSON-LD (supply's
`source: json_ld`), which is the 2E rule, "member price in markup" counts. Unchanged in points. `promo` still reads 19
of 19 "the page text included". If a read's member price is not in its markup (`source: text`), that read drops out.

### The readiness verdict in the measured case

soa computed it (`verdict()`, which calls `scan_dimensions.compute_verdict` as is: AGENT-READY at or above 60 with True
Value at or above 25% of its applicable points, else NOT AGENT-READY) whenever no dimension is not measured. The console
tile never rendered `verdict`, only `verdict_note`. Fixed in the console (parleohq/truesync, 2E-2): the verdict sits in
the readiness legend, "Readiness bar 60, 28 to go, NOT AGENT-READY". All three paths are tested on both sides. **229:**
32 is under the bar, so NOT AGENT-READY, whatever True Value is.

### robots.txt names answer-time agents: 9 of 9

There is one token list on both sides. Supply's M is the answer-time tokens of the access run's agents, each once
(`robots.ANSWER_TIME_TOKENS`): 7 for the default five agents (chatgpt, gemini, aimode, perplexity, copilot), and 9 with
`claude` (Claude-SearchBot, Claude-User), which W&S's runs include. The store's `robots.ts` gives all nine their own
group, so 9 of 9 is the live file naming nine tokens. Supply's fixtures use the five-agent run, so they say 7. No label
change.

### api mode matches the demo (console)

The console no longer renders the Overview's "Dimension by dimension" table or the Measure screens' Share of Algorithm
row. Neither is on the demo. This endpoint still serves `pillars[].dimensions`, their parts, checks and
`previous.dimension_deltas`.

## 2G: seven demo-parity leftovers (soa's half)

Api mode shows what the demo shows. soa serves what the console needs to render each item the demo's way. Tests:
`tests/test_console_2g.py`, on the 229-shaped fixture with its 2G layer (`tests/console_fixture_229_2g.py`), on both
databases.

| item | the demo | soa |
|---|---|---|
| 1. Answers header | "N answers from M surfaces" counts answers | No change. `/answers/summary` `all_tiers` already gives runs and answered per surface under 2C-2b's rule. 229: 516 runs, 514 answered (grounded API 514 of 514, consumer UI 2 of 0) |
| 2. TrueSync readback | "N of M priced it right" is about prices | Each answer carries `expected_type` (its outcome's expectation, else its question's): `price`, `member_price`, `code`, `points`, `brand_mention`. On 229 Snug-Fit Diapers has 72 price, 6 code and 12 points answers |
| 3. True Value program tile | "Program price quoted, The first-order or member price that decides who wins" | No change (the console counts the `member_price` programs) |
| 4. Visibility footer | "Also named but not tracked: Target 36, Tractor Supply 27, Costco 17 (all 420 answers)." | `ranking.untracked[surface]`: brands named outside the comparison set (never ours, never a comparison-set brand, never a source), each `{name, named}`, over the surface's answered runs, most named first, ten at most. 229 layer: Target 34, Costco 17, Hello Bello 9 of 514 |
| 5. True Value row caption | "First Autoship $47.99 (Purina ladder). Quoted by 0 of 5 agents." | `program_lines[variant_id]` (`parity.program_lines`). The program price follows the ladder's rule, `member_price_source`: the record's, else the newest page read with a member price. Per surface, the agents asked a value-tier member-price question about the variant and the ones with an exact answer, plus the sentence: "Member+ $15.49 (from the page read Oct 14). Quoted by 1 of 2 agents.", or "Not asked this cycle." when there is a price and no question. A variant with neither gets no caption. Rows carry `variant_id` |
| 6. Offer record | Shipping "Free over $39", Returns "60 days", Availability "In stock" | **Supply carries no shipping or returns.** The W&S store config has a free-shipping *deal* (`kind: free_shipping`, `spend_min: 35`), merchant-wide; no listing in `/incentives` carries it, and nothing carries a returns policy. `offer_fields` keeps its rule: shipping and returns only when the listing carries them, so nothing renders. **Availability**: the record's variant, else the newest page read. `/reference` rows drop `availability`, so the record also reads supply `/retailer-prices` (`prices`), whose rows carry it. The value is put in words ("In stock") with provenance `parleo` and "as the newest page read found it, Oct 14". The Oct 14 recording predates the field, so production's record shows availability only after a newer read |
| 7. Catalog stage ladder | "0 Not measured · 1 Measured (you are here) · 2 Published · 3 Verified", each with a line, and modeled rankings | `stage_ladder`: the four stages with the demo's lines and the products that reached each, from the per-product stages (a product counts at each stage it reached; Not measured is one no scored cycle quoted), `here` the highest stage any product reached. No rankings: the demo's are modeled. 229 layer: 19 published, 13 measured, 0 verified, 6 not measured, here = Published |

**The 2G layer** is applied on top of 229's base fixture in 2G's tests only. It doesn't change the base, and 2C-3a's
counts are untouched.
- Questions name their variants: catalog in record order; Member+ on Overnight Size 3, Cloud Wipes and the Trial Pack;
  code and points on Snug-Fit Diapers.
- The catalog runs that state a price carry it: every exact and wrong run, and every run answered with another brand's
  price. That covers 13 variants.
- One run moves from exact to wrong: the sixth of the first catalog question. Without it that variant would be verified,
  and production's 229 has none.
- Layer 2 names Target, Costco and Hello Bello, plus 43 sources.

`tests/fixtures/console/supply_retailer_prices_ws_availability.json` is the recorded W&S retailer-prices payload with
each readable row's availability as supply's own reader stores it (`parse._availability` on the store's
`https://schema.org/InStock`).

## 2H: one org, several merchants

The Wiggle & Snug org (10) holds two supply merchants: the store (`wiggle-and-snug`, seller, Parleo-hosted,
trueshopstore.com) and the brand (`wiggle-and-snug-brand`, brand, customer-hosted, wiggleandsnug.com). The console picks
one, and every read names it with `?merchant=`. Code: `app/console_merchants.py`. Tests: `tests/test_console_2h.py` (both
databases) and `apps/pipeline/tests/test_full_loop_coordinator.py` (the worker).

**The merchants.** `GET /api/console/me` gives each org `merchants`, in supply's `/tenant` order (the Command Center's,
by slug), read with that org's own token. The own domain comes from `/merchants/{slug}/retailers` (`own_domains[0]`, else
`own_domain`, else the tenant record's domain). The first merchant is `primary`: the one 2C-0 used for everything, so a
call that names no merchant behaves as before. The org's own `slug`/`kind`/`hosting`/`domain` stay the primary's.

```json
"merchants": [
  {"slug": "wiggle-and-snug", "name": "Wiggle & Snug", "kind": "seller", "hosting": "parleo",
   "domain": "trueshopstore.com", "primary": true},
  {"slug": "wiggle-and-snug-brand", "name": "Wiggle & Snug Brand", "kind": "brand", "hosting": "external",
   "domain": "wiggleandsnug.com", "primary": false}
]
```

**`?merchant=`.** A slug that is not one of the org's is a 404 ("merchant 'x' not found"), like a cross-tenant read. When
the tenant cannot be read, a named merchant passes unverified, and supply refuses one that is not the token's.

| endpoint | before 2H | 2H |
|---|---|---|
| `/accessibility`, `/truesync`, `/record`, `/record/list`, `/catalog` | took `merchant` (required) | the 404 check |
| `/overview`, `/score` | took `merchant` (optional; the cycle's own otherwise) | the 404 check when named |
| `/true-value`, `/programs` | took `merchant` | unchanged |
| `/runs` | per org | **gained** `?merchant=`: that merchant's cycles, else the primary's |
| `/full-loop/latest` | per org | **gained** `?merchant=`: that merchant's latest loop, else the primary's |
| `/studio/studies` | per org | **gained** `?merchant=`: that merchant's studies, each with `merchant: {slug, name}` |
| `POST /api/full-loop` | `merchant_slug` in the body, unchecked | must be the merchant the study was generated for (404 otherwise), checked from the study's job, so starting a loop still makes no supply call |
| cycle-scoped reads (`/answers`, `/visibility`, `/true-value?cycle=` …) | by cycle | unchanged: a cycle is one merchant's |

**A cycle belongs to one merchant.** It's the one its study was generated for: `soa_query_generation_jobs.syndicated_merchant`,
else the merchant in its `tier_config`. A cycle whose study names none predates 2H and belongs to the primary. A merchant
with no cycle gets an empty list, never another merchant's cycles.

**The worker.** The coordinator already keys every step on the request's `merchant_slug` (2A, #101): supply's POST, the
poll, the cycle code (`FL<run>-<merchant>-<date>`) and the PATCH. The new test runs a brand request end to end. Nothing in
2H runs the brand's first loop.

**Studies.** Create Study already lists the org's merchants (`/studies/options`) and takes `syndicated_merchant`; the
console defaults it to the selected merchant.

## 2I-8: every agent together, a surface is a filter

The console demo counts all five agents together and never names a surface ("Pampers is named
in 25 of 29 category answers and put first in 5", one "Who each agent picks first" grid with
ChatGPT, Gemini, AI Mode, Perplexity and Copilot as columns). The api console, by a rule 2B
introduced and 2C to 2C-2 carried, counted per surface and defaulted to the highest-fidelity
surface with answered runs, so FL12's Overview showed the consumer UI's 34 of 102 unprompted
answers and hid the four grounded agents. Decision (Oct 20): match the demo.

**The rule now.** Counts are shown for every agent together by default, as the demo shows them.
Each surface's own count sits beside it, as a filter. The score pools surfaces by score, not by
count (`console_score.py`, unchanged, scorer 9).

**One mechanism.** A pseudo-surface `all` (`soa_shared/surfaces.py` `ALL`, label "All agents",
helpers `with_all` and `on_surface`), computed over every run in the cycle, listed first in every
surface list and the default wherever a read model picked "the highest-fidelity surface with
answered runs". Each surface's entry is unchanged: `tests/test_console_2i8.py` pins every
per-surface value on four fixtures (W&S, W&S on two surfaces, 229/FL8, the FL12-shaped
`console_fixture_2i8`) to main's output, byte for byte, with `all` taken out. `all` is a
read-model key only: it is no surface kind and no surface id, so `resolve` refuses it and no
cycle, full loop or runner can carry it.

| where | what `all` holds |
|---|---|
| `parity.ordered_surfaces` | ranks `all` first (`_SURFACE_RANK`) |
| `visibility_headline` | the gap sentence over every agent's unprompted answers: FL12-shaped, "First in 33 of 102 unprompted answers." (22 of 68 grounded plus 11 of 34 consumer) |
| `visibility_matrix` | one column per agent across the surfaces, in the demo's order (ChatGPT, Gemini, AI Mode, Perplexity, Copilot, then Claude); a question an agent did not run has no cell, one it ran with no answer has `answered: 0` and no pick. Each surface's matrix keeps its columns by name, as before |
| `visibility_by_stage` | stages and tiers over every answered run |
| `extend_visibility` | `headline` = `headlines.all`, `matrix.all`, `by_stage.all` |
| `build_visibility` | `ranking.surface = 'all'`, `denom`, `denoms.all`, `agent_denoms.all` (demo order), `first_uncoded.all`, `agent_first_uncoded.all`, each row's `surfaces.all` with the full agent split and its typed `named`/`first`, `untracked.all` (the 2G footer over every answered run), `surfaces[0]` |
| `surface_metrics`, `build_agents` | the agent table over every agent, six rows in the demo's order on FL12 |
| `build_products` | ProductWeek named, first, quoted, live over every agent's quotes; `cell_status` is the cell's `by_surface.all` |
| `build_signals` | the counts over every agent; the detail reads "across every agent" where a surface reads "on the grounded API" |
| `build_summary` | the same sentences over every agent; no price scored reads "No price was scored by any agent." |
| `changes_status`, `build_changes` | compared on `all` when the same agents answered in both cycles, whatever their surfaces |
| `build_overview` | `surface: 'all'`, `surfaces` begins with it, `by_surface.all` |
| `build_answers_summary` | `all_tiers`, `surfaces` and each tier's `surfaces` begin with `all`: counts summed, accuracy exact ÷ scored over the sums |
| `build_true_value` | `surface: 'all'`; each cell's typed `quoted`/`status`/`outcome`/`runs` by TV_CELL_RULE over every agent's quotes, `by_surface.all` beside the surfaces; `by_agent.all` and `columns_by_surface.all` with every agent (demo order); `columns` is `all`'s |
| `_program_agents`, `build_programs` | `by_surface.all`; `agentsRight` over every agent |
| `program_lines` (2G caption) | `by_surface.all`: "Quoted by N of M agents." over every agent asked |
| `/catalog` stage counts (`console_ops.get_catalog`) | "measured" counts every agent's quotes, as True Value's typed cell does |
| `console_score.metric_counts`, `build_metrics` (2I-8a) | the score block's five rows on `all` (`metric_surface`), every pooled agent: on the FL12 shape first 33 of 102, share 51 of 102, program 0 of 51, prices exact 22 of 42, terms 24 of 30, noted "across every agent, unprompted answers" / "across every agent, catalog tier, exact of scored"; each row's `by_surface` keeps the pooled surfaces' value and denominator, as before. A delta compares `all` to `all`; a previous score whose counts have no `all` gives none, with "Not comparable: {code} was scored before metric rows counted every agent" |

**2I-8a: scorer 10.** The rows are counts beside the score, not the score: its dimensions stay per surface and pool
by score. The stored score carries the rows' counts (`metric_counts`, `metric_surface`) and the rows are built from them
on each read, so a stored cycle would keep its single-surface rows: `SCORER_VERSION` goes from 9 to 10
(`SCORER_CHANGES['10']`, "metric rows count every agent"), and each cycle re-scores on its next read. The score, earned,
applicable max, dimensions and verdict do not move (`tests/test_console_2i8a.py` pins the body on 229, 229 with the
brand box on and the six-agent FL12 shape), so the history line reads plain "scorer 9 → 10". A previous cycle still at
v9 reads "Scored under v9, re-score to compare." until it is read again. The worker carries no console scorer version.

Left per surface: `/api/console/accuracy` (2B, `soa_shared/surface_accuracy.py`, which the console
does not read), the Studies grid (`build_study_rows`, a cell per agent, not per surface), and the
score.

**Templates.** New, for `all`: `summary.no_price_all` "No price was scored by any agent.",
`changes.not_comparable_subset_all` "Not comparable: {code} ran {agents} only.",
`changes.not_comparable_all` "Not comparable: {code} ran {prev}, this cycle ran {now}.",
`changes.not_comparable_tier_all` "Not comparable: {code} asked no unprompted questions.".
Changed, same output on a surface: `signal.other_brand` and `signal.fabricated` details read
"{n} of {asked} price answers {on}." (`on` is "on the grounded API", or "across every agent").
Visibility's `lede` reads "… Every agent together, as the demo counts them. Pick a surface to count
one alone." The samples below were taken before 2I-8 and do not carry `all`.

**`?surface=`.** No console endpoint takes a surface parameter: each returns every surface keyed,
and the console picks. `?surface=all` and no parameter are the same response (pinned for
answers, answers/summary, true-value, visibility and overview).

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
          "runs": 3,
          "reference_source": "record",
          "method": null,
          "observed_at": "2026-08-28T18:03:06.090934+00:00"
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
          "runs": 1,
          "reference_source": "record",
          "method": null,
          "observed_at": "2026-08-28T18:58:45.042456+00:00"
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
          "runs": 1,
          "reference_source": "record",
          "method": null,
          "observed_at": "2026-08-28T18:01:14.698561+00:00"
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
          "runs": 1,
          "reference_source": "record",
          "method": null,
          "observed_at": "2026-09-04T20:49:40.991623+00:00"
        }
      }
    }
  ],
  "programs": [],
  "as_of": null,
  "divergences": [
    "TvCell.status is extended by 'unverifiable' (the page blocked both reference sources).",
    "A stale quote has status 'wrong' (it is wrong today); `outcome` carries 'stale'.",
    "`programs` is empty: soa scores no program terms per retailer here.",
    "Each cell carries reference_source (honest_fetch | hosted_render | record), method and observed_at beside the typed fields (2C)."
  ]
}
```

### GET /api/console/true-value, an external brand (2C)

The W&S fixture is scored against the record, so it has no `unverifiable` cell. This is
`build_true_value` over a 2A reference with one blocked page (the case in
`test_true_value_for_an_external_brand_reads_the_2a_reference`).

```json
{
  "columns": [
    {
      "id": "target.com",
      "name": "Target",
      "you": false
    },
    {
      "id": "walmart.com",
      "name": "Walmart",
      "you": false
    }
  ],
  "rows": [
    {
      "product": "Size 3",
      "sku": "00012345678905",
      "cells": {
        "target.com": {
          "quoted": "$22.99",
          "live": "$21.49",
          "status": "wrong",
          "outcome": "stale",
          "runs": 1,
          "reference_source": "honest_fetch",
          "method": "fetch",
          "observed_at": "2026-10-09T11:58:00+00:00"
        },
        "walmart.com": {
          "quoted": "$17.00",
          "live": "unverifiable",
          "status": "unverifiable",
          "outcome": "unverifiable",
          "runs": 1,
          "reference_source": "hosted_render",
          "method": "hosted",
          "observed_at": "2026-10-09T11:59:00+00:00"
        }
      }
    }
  ],
  "programs": [],
  "as_of": "2026-10-09T12:00:00+00:00",
  "divergences": [
    "TvCell.status is extended by 'unverifiable' (the page blocked both reference sources).",
    "A stale quote has status 'wrong' (it is wrong today); `outcome` carries 'stale'.",
    "`programs` is empty: soa scores no program terms per retailer here.",
    "Each cell carries reference_source (honest_fetch | hosted_render | record), method and observed_at beside the typed fields (2C)."
  ]
}
```

### GET /api/console/programs?merchant=wiggle-and-snug&cycle=WS-2B-FIXTURE (2C)

The owned incentives are the test's (`OWNED`); the fixture cycle asks no value question.

```json
{
  "merchant": "wiggle-and-snug",
  "programs": [
    {
      "name": "Member Rewards",
      "terms": "$16.84 member price, on all",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "member_price",
      "code": null,
      "tier_name": "Member+",
      "valid_until": null,
      "asked": 0,
      "scored": 0,
      "right": 0
    },
    {
      "name": "SNUG3",
      "terms": "$3.00 off, code SNUG3, on Diapers, until 2026-12-31",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "code",
      "code": "SNUG3",
      "tier_name": null,
      "valid_until": "2026-12-31",
      "asked": 0,
      "scored": 0,
      "right": 0
    }
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

### GET /api/console/truesync?merchant=wiggle-and-snug (2C, 1 of 5 products)

Supply's answers are the web app's real W&S captures (Aug 2026) and the pipeline's W&S catalog,
with `manufacturer_center` listed as supply's seed has it and `connected: false` (no MC
account yet). Payloads cut.

```json
{
  "merchant": "wiggle-and-snug",
  "channels": [
    {
      "id": "schema_org",
      "name": "Schema.org Product/Offer",
      "short": "Schema.org Product/Offer",
      "spec": "schemaorg-merchant-listing-2026-08-18",
      "verification_surface": "fetch_probe",
      "extension_status": null,
      "connected": null,
      "depth_label": "Fully live on demo store"
    },
    {
      "id": "merchant_center",
      "name": "Google Merchant Center feed",
      "short": "Google Merchant Center feed",
      "spec": "gmc-products-v1-2026-08-18",
      "verification_surface": "acceptance",
      "extension_status": null,
      "connected": null,
      "depth_label": "Live at API layer; accepted + passing diagnostics (not \"surfaced\")"
    },
    {
      "id": "manufacturer_center",
      "name": "Google Manufacturer Center",
      "short": "Google Manufacturer Center",
      "spec": "manufacturers-v1-2026-10-05",
      "verification_surface": "acceptance",
      "extension_status": null,
      "connected": false,
      "depth_label": "Acceptance read back"
    },
    {
      "id": "acp",
      "name": "Agentic Commerce Protocol",
      "short": "Agentic Commerce Protocol",
      "spec": "acp-feed-stable-2026-08-18",
      "verification_surface": "fetch_probe",
      "extension_status": "deferred",
      "connected": null,
      "depth_label": "Spec-conformant, self-hosted, validated (not enrolled)"
    },
    {
      "id": "ucp_uip",
      "name": "UCP / Universal Incentive Protocol",
      "short": "UCP / Universal Incentive Protocol",
      "spec": "ucp-2026-04-08",
      "verification_surface": "none",
      "extension_status": "not_applicable",
      "connected": null,
      "depth_label": "Spec-conformant, self-hosted (not enrolled)"
    },
    {
      "id": "deals_api",
      "name": "Parleo Deals API",
      "short": "Parleo Deals API",
      "spec": "parleo-internal",
      "verification_surface": "none",
      "extension_status": null,
      "connected": null,
      "depth_label": "Live today"
    },
    {
      "id": "mcp",
      "name": "Model Context Protocol server",
      "short": "Model Context Protocol server",
      "spec": "parleo-internal",
      "verification_surface": "none",
      "extension_status": null,
      "connected": null,
      "depth_label": "Live today"
    },
    {
      "id": "deal_directory",
      "name": "Deal directory / affiliate listing",
      "short": "Deal directory / affiliate listing",
      "spec": "parleo-internal",
      "verification_surface": "none",
      "extension_status": null,
      "connected": null,
      "depth_label": "Exists"
    }
  ],
  "products": [
    {
      "sku": "catalog_product:27",
      "name": "Snug-Fit Diapers",
      "sub": "Wiggle & Snug · 12 variants",
      "variants": "12 variants",
      "gtin": "884400137609",
      "cells": {
        "schema_org": {
          "s": "published",
          "d": "none",
          "at": "2026-08-24T22:35:04.189910Z",
          "publication_id": 330,
          "status": "published",
          "published_at": "2026-08-21T20:16:03.128053Z",
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": null
        },
        "merchant_center": {
          "s": "blocked",
          "d": "unverified",
          "at": "2026-08-24T21:52:05.863831Z",
          "note": "not implemented in Step 2",
          "publication_id": 331,
          "status": "failed",
          "published_at": null,
          "acceptance": "not_found",
          "origin": null,
          "connected": null,
          "external_ref": null
        },
        "manufacturer_center": {
          "s": "na",
          "d": "unverified",
          "note": "not connected",
          "publication_id": null,
          "status": null,
          "published_at": null,
          "acceptance": null,
          "origin": null,
          "connected": false,
          "external_ref": null
        },
        "acp": {
          "s": "blocked",
          "d": "unverified",
          "note": "not implemented in Step 2",
          "publication_id": 332,
          "status": "failed",
          "published_at": null,
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": null
        },
        "ucp_uip": {
          "s": "blocked",
          "d": "unverified",
          "note": "not implemented in Step 2",
          "publication_id": 333,
          "status": "failed",
          "published_at": null,
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": null
        },
        "deals_api": {
          "s": "published",
          "d": "unverified",
          "publication_id": 334,
          "status": "published",
          "published_at": "2026-08-21T20:16:03.549556Z",
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": "deals_api:listing:90"
        },
        "mcp": {
          "s": "published",
          "d": "unverified",
          "publication_id": 335,
          "status": "published",
          "published_at": "2026-08-21T20:16:03.718651Z",
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": "mcp:listing:90"
        },
        "deal_directory": {
          "s": "published",
          "d": "unverified",
          "publication_id": 336,
          "status": "published",
          "published_at": "2026-08-21T20:16:03.869094Z",
          "acceptance": null,
          "origin": null,
          "connected": null,
          "external_ref": "deal_directory:listing:90"
        }
      },
      "validator": {
        "schema_org": [
          {
            "field": "amount_off",
            "verdict": "approx",
            "note": "schema.org: the resulting price is expressible; the amount off itself is only a hint (specs §4)."
          },
          {
            "field": "percent_off",
            "verdict": "approx",
            "note": "schema.org: price and priceSpecification carry the resulting price; the percentage itself is only a hint (specs §4)."
          },
          {
            "field": "new_customer",
            "verdict": "dropped",
            "note": "schema.org: no new-customer eligibility structure (specs matrix)."
          },
          {
            "field": "subscribe_and_save",
            "verdict": "approx",
            "note": "schema.org: disclosure only — no subscription pricing structure (specs matrix)."
          },
          {
            "field": "subscription",
            "verdict": "approx",
            "note": "schema.org: subscription eligibility is disclosure text, not structured (specs matrix)."
          },
          {
            "field": "mfr_coupon",
            "verdict": "approx",
            "note": "schema.org: coupon codes are a hint, not a structured field (specs matrix)."
          },
          {
            "field": "gift_with_purchase",
            "verdict": "approx",
            "note": "schema.org: a gift with purchase is a disclosure hint, not a structured benefit (specs matrix)."
          },
          {
            "field": "effective_net_price",
            "verdict": "approx",
            "note": "The calculator's net price includes a member-only offer, so the public Offer.price quotes list; the member price is carried in priceSpecification, gated by tier."
          },
          {
            "field": "stacking",
            "verdict": "info",
            "note": "schema.org has no stacking vocabulary; combinability is stated in the description only (specs matrix)."
          }
        ],
        "merchant_center": [
          {
            "field": "record",
            "verdict": "conflict",
            "note": "not implemented in Step 2"
          },
          {
            "field": "amount_off",
            "verdict": "approx",
            "note": "GMC: no amount-off field; carried as sale_price, so the mechanic is lost (specs §3)."
          },
          {
            "field": "percent_off",
            "verdict": "approx",
            "note": "GMC: no percentage field; carried as sale_price, so the mechanic is lost (specs §3)."
          },
          {
            "field": "new_customer",
            "verdict": "dropped",
            "note": "GMC: no new-customer eligibility field (specs §3)."
          },
          {
            "field": "subscribe_and_save",
            "verdict": "dropped",
            "note": "GMC: no subscribe-and-save representation in product data or loyalty_program (specs §3)."
          },
          {
            "field": "subscription",
            "verdict": "dropped",
            "note": "GMC: loyalty_program expresses program and tier, not subscription (specs §3)."
          },
          {
            "field": "mfr_coupon",
            "verdict": "approx",
            "note": "GMC: only via the separate promotions feed, whose current fields are unverified (specs §3)."
          },
          {
            "field": "gift_with_purchase",
            "verdict": "approx",
            "note": "GMC: only via the separate promotions feed, whose current fields are unverified (specs §3, matrix)."
          }
        ],
        "manufacturer_center": [],
        "acp": [
          {
            "field": "record",
            "verdict": "conflict",
            "note": "not implemented in Step 2"
          },
          {
            "field": "tier",
            "verdict": "dropped",
            "note": "ACP: promotions have no eligibility fields, so tier gating is not expressible (specs §2)."
          },
          {
            "field": "points_earn",
            "verdict": "dropped",
            "note": "ACP: no loyalty points representation (specs §2)."
          },
          {
            "field": "member",
            "verdict": "dropped",
            "note": "ACP: promotions have no eligibility fields, so membership gating is not expressible (specs §2)."
          },
          {
            "field": "new_customer",
            "verdict": "dropped",
            "note": "ACP: no new-customer eligibility field (specs §2)."
          },
          {
            "field": "subscribe_and_save",
            "verdict": "dropped",
            "note": "ACP: no subscribe-and-save fields; effective price plus disclosure is the best available (specs §1)."
          },
          {
            "field": "subscription",
            "verdict": "dropped",
            "note": "ACP: no subscription eligibility field (specs §2)."
          },
          {
            "field": "mfr_coupon",
            "verdict": "dropped",
            "note": "ACP: promotions carry no redemption code (specs §2)."
          },
          {
            "field": "gift_with_purchase",
            "verdict": "dropped",
            "note": "ACP: promotions benefits are amount_off, percent_off and free_shipping only (specs §2)."
          }
        ],
        "ucp_uip": [
          {
            "field": "record",
            "verdict": "conflict",
            "note": "not implemented in Step 2"
          },
          {
            "field": "amount_off",
            "verdict": "approx",
            "note": "UCP: catalog carries list_price vs price only; the discount itself is a checkout-time UIP concern (specs §5, §6)."
          },
          {
            "field": "percent_off",
            "verdict": "approx",
            "note": "UCP: catalog carries list_price vs price only; the discount itself is a checkout-time UIP concern (specs §5, §6)."
          },
          {
            "field": "tier",
            "verdict": "info",
            "note": "UCP: tier status is a checkout-time UIP concern; the catalog payload has no tier scope (specs §5, §6)."
          },
          {
            "field": "points_earn",
            "verdict": "info",
            "note": "UCP catalog has no points; UIP expresses them at checkout, not on the catalog payload (specs §5, §6)."
          },
          {
            "field": "member",
            "verdict": "info",
            "note": "UCP: eligibility is a checkout-time UIP concern; the catalog payload has no member scope (specs §5, §6)."
          },
          {
            "field": "new_customer",
            "verdict": "dropped",
            "note": "UCP/UIP: no new-customer eligibility field (specs §6)."
          },
          {
            "field": "subscribe_and_save",
            "verdict": "info",
            "note": "UCP: UIP covers subscription promotions partially, and only at checkout (specs §6)."
          },
          {
            "field": "subscription",
            "verdict": "info",
            "note": "UCP: subscription eligibility is checkout-scoped in UIP (specs §6)."
          },
          {
            "field": "mfr_coupon",
            "verdict": "info",
            "note": "UCP: UIP carries the code at checkout; the catalog payload cannot (specs §6)."
          },
          {
            "field": "gift_with_purchase",
            "verdict": "info",
            "note": "UCP: UIP carries a gift with purchase at checkout; the catalog payload cannot (specs matrix)."
          }
        ],
        "deals_api": [
          {
            "field": "record",
            "verdict": "ok",
            "note": "valid against parleo-internal"
          }
        ],
        "mcp": [
          {
            "field": "record",
            "verdict": "ok",
            "note": "valid against parleo-internal"
          }
        ],
        "deal_directory": [
          {
            "field": "record",
            "verdict": "ok",
            "note": "valid against parleo-internal"
          }
        ]
      },
      "payload": {
        "schema_org": "… 33630 chars of the published artifact (JSON), cut",
        "merchant_center": "… 4 chars of the published artifact (JSON), cut",
        "acp": "… 4 chars of the published artifact (JSON), cut",
        "ucp_uip": "… 4 chars of the published artifact (JSON), cut",
        "deals_api": "… 151 chars of the published artifact (JSON), cut",
        "mcp": "… 151 chars of the published artifact (JSON), cut",
        "deal_directory": "… 151 chars of the published artifact (JSON), cut"
      },
      "listing_id": 90,
      "product_url": "https://trueshopstore.com/products/snug-fit-diapers",
      "published_at": "2026-09-04T20:49:40.991623+00:00",
      "variant_ids": [
        "snug-fit-diapers-s1-small",
        "snug-fit-diapers-s1-big",
        "snug-fit-diapers-s2-small",
        "snug-fit-diapers-s2-big",
        "snug-fit-diapers-s3-small",
        "snug-fit-diapers-s3-big",
        "snug-fit-diapers-s4-small",
        "snug-fit-diapers-s4-big",
        "snug-fit-diapers-s5-small",
        "snug-fit-diapers-s5-big",
        "snug-fit-diapers-s6-small",
        "snug-fit-diapers-s6-big"
      ],
      "gtins": [
        "884400137609",
        "884400528827",
        "884400046246",
        "884400937353"
      ],
      "provenance": "published",
      "provenance_basis": "merchant"
    }
  ],
  "lastVerified": "2026-08-24T22:35:04.189910Z",
  "provenance": {
    "merchant_source": "published",
    "listings": {
      "scrape": 0,
      "published": 5
    }
  },
  "divergences": [
    "Assembled by soa from supply's channels, publications, catalog, per-channel verifications and provenance; supply has no single Command Center payload.",
    "Products are the published catalog's listings: a listing never published is not a row (the web app's schema-org spine has the same limit).",
    "TsCell.s: published, compiled (compiled, validated, withdrawn), blocked (failed), not_published (no publication), na (a channel this tenant is not connected to, with connected: false beside).",
    "TsCell.d comes from the newest fetch_probe at or after the publish only: drift when it has findings, none when it has none, unverified otherwise (and on every acceptance channel).",
    "acceptance (merchant_center from gmc_diagnostics, manufacturer_center from mc_acceptance) and origin ('parleo' | 'gmc_sync', manufacturer_center only) ride beside the typed cell.",
    "provenance per product is the merchant's mix when it is all one source; mixed, a listing with a publication is 'published' and the rest 'scrape' (provenance_basis says which).",
    "ValidatorLine.verdict: validation errors are 'conflict'; expressiveness dropped -> dropped, approximated -> approx, checkout_scope and info -> info; a valid record with no flags is one 'ok'."
  ]
}
```

### GET /api/console/catalog?merchant=wiggle-and-snug (2C, hosted, 2 of 19 rows)

```json
{
  "merchant": "wiggle-and-snug",
  "source": "hosted",
  "read_only": true,
  "note": "Hosted on Parleo: this catalog comes from the store config. Edit it there. No feed upload applies.",
  "version": null,
  "rows": [
    {
      "gtin": null,
      "variant_id": "snug-fit-diapers-s1-small",
      "product_name": "Snug-Fit Diapers",
      "brand_name": "Wiggle & Snug",
      "variant_label": "Snug-Fit Diapers Size 1 — Small Pack (96 ct)",
      "size": "Size 1",
      "pack_count": 96,
      "multipack": null,
      "price": "17.99",
      "currency": "USD",
      "published_at": "2026-09-04T20:49:40.991623+00:00",
      "product_url": "https://trueshopstore.com/products/snug-fit-diapers"
    },
    {
      "gtin": null,
      "variant_id": "snug-fit-diapers-s1-big",
      "product_name": "Snug-Fit Diapers",
      "brand_name": "Wiggle & Snug",
      "variant_label": "Snug-Fit Diapers Size 1 — Big Pack (198 ct)",
      "size": "Size 1",
      "pack_count": 198,
      "multipack": null,
      "price": "31.99",
      "currency": "USD",
      "published_at": "2026-09-04T20:49:40.991623+00:00",
      "product_url": "https://trueshopstore.com/products/snug-fit-diapers"
    }
  ],
  "versions": []
}
```

### GET /api/console/catalog?merchant=brandco (2C, external)

```json
{
  "merchant": "brandco",
  "source": "feed",
  "read_only": false,
  "note": null,
  "version": {
    "id": 12,
    "version_number": 2,
    "upload_id": "up_61aa",
    "mode": "all_valid_rows",
    "row_count": 2,
    "counts": {
      "ready": 2,
      "warning": 0,
      "error": 0
    },
    "committed_at": "2026-10-08T10:00:00+00:00",
    "superseded_at": null
  },
  "rows": [
    {
      "row_number": 2,
      "gtin": "012345678905",
      "product_name": "Brandco Wipes",
      "variant_label": "72 ct",
      "pack_count": 72,
      "multipack": null,
      "price": "4.99",
      "currency": "USD",
      "retailers": [
        {
          "domain": "target.com",
          "url": "https://www.target.com/p/2"
        }
      ]
    },
    {
      "row_number": 3,
      "gtin": "012345678912",
      "product_name": "Brandco Diapers Size 3",
      "variant_label": "84 ct",
      "pack_count": 84,
      "multipack": null,
      "price": "22.99",
      "currency": "USD",
      "retailers": [
        {
          "domain": "target.com",
          "url": "https://www.target.com/p/3"
        }
      ]
    }
  ],
  "versions": [
    {
      "id": 12,
      "version_number": 2,
      "upload_id": "up_61aa",
      "mode": "all_valid_rows",
      "row_count": 2,
      "counts": {
        "ready": 2,
        "warning": 0,
        "error": 0
      },
      "committed_at": "2026-10-08T10:00:00+00:00",
      "superseded_at": null
    },
    {
      "id": 9,
      "version_number": 1,
      "upload_id": "up_40b2",
      "mode": "require_clean",
      "row_count": 1,
      "counts": {
        "ready": 1,
        "warning": 0,
        "error": 0
      },
      "committed_at": "2026-10-01T10:00:00+00:00",
      "superseded_at": "2026-10-08T10:00:00+00:00"
    }
  ]
}
```

### POST /api/console/catalog/validate?merchant=brandco (2C)

Brandco is soa's external test fake; supply's preview is shaped by its `feed/validate.py`.

```json
{
  "_note": "supply POST /api/truesync/merchants/brandco/feed/validate, shaped by truesync/feed/validate.py (supply b3f261e); Brandco is soa's test fake.",
  "upload_id": "up_7f3c2a",
  "merchant": "brandco",
  "summary": {
    "rows": 3,
    "ready": 1,
    "warning": 1,
    "error": 1,
    "file_errors": 0,
    "forms": [
      "wide"
    ],
    "reachability_checked": false,
    "incentives": null
  },
  "file_errors": [],
  "rows": [
    {
      "row_number": 2,
      "sheet": "skus",
      "gtin_as_given": "012345678905",
      "gtin": "00012345678905",
      "product_name": "Brandco Wipes",
      "brand_name": "Brandco",
      "variant_label": "72 ct",
      "pack_count": 72,
      "multipack": null,
      "size_value": null,
      "size_unit": null,
      "price": "4.99",
      "currency": "USD",
      "description": null,
      "image_url": null,
      "retailers": [
        {
          "domain": "target.com",
          "url": "https://www.target.com/p/2"
        }
      ],
      "messages": [
        {
          "code": "multipack_suggested",
          "severity": "warning",
          "field": "multipack",
          "message": "page shows a count but multipack is empty: target.com shows 3, 216, the row says pack_count 72, and multipack 3 would explain it",
          "source": "soa",
          "suggested": 3
        }
      ],
      "status": "warning"
    },
    {
      "row_number": 3,
      "sheet": "skus",
      "gtin_as_given": "012345678912",
      "gtin": "00012345678912",
      "product_name": "Brandco Diapers Size 3",
      "brand_name": "Brandco",
      "variant_label": "84 ct",
      "pack_count": 84,
      "multipack": null,
      "size_value": null,
      "size_unit": null,
      "price": "22.99",
      "currency": "USD",
      "description": null,
      "image_url": null,
      "retailers": [
        {
          "domain": "target.com",
          "url": "https://www.target.com/p/3"
        }
      ],
      "messages": [],
      "status": "ready"
    },
    {
      "row_number": 4,
      "sheet": "skus",
      "gtin_as_given": "01234567891",
      "gtin": "00001234567891",
      "product_name": "Brandco Balm",
      "brand_name": "Brandco",
      "variant_label": "4 oz",
      "pack_count": null,
      "multipack": null,
      "size_value": null,
      "size_unit": null,
      "price": "9.99",
      "currency": "USD",
      "description": null,
      "image_url": null,
      "retailers": [
        {
          "domain": "target.com",
          "url": "https://www.target.com/p/4"
        }
      ],
      "messages": [
        {
          "code": "gtin_check_digit",
          "severity": "error",
          "field": "gtin",
          "message": "the GTIN's check digit is wrong"
        }
      ],
      "status": "error"
    }
  ],
  "incentives": null,
  "reference_checked": true
}
```

### GET /api/console/studies/options (2C, cut)

```json
{
  "constraints": {
    "category": [
      "Skincare",
      "Makeup",
      "Fragrance",
      "… 7 more"
    ],
    "stage": [
      "Awareness",
      "Research",
      "Comparison",
      "Ready to Buy"
    ],
    "specificity": [
      "Broad",
      "Mid",
      "Narrow",
      "… 0 more"
    ],
    "persona": [
      "Casual / Gift Buyer",
      "Value-Conscious",
      "Beauty Enthusiast",
      "… 13 more"
    ],
    "status": [
      "Active",
      "Paused",
      "Retired",
      "… 0 more"
    ],
    "study_pattern": [
      "retailer",
      "brand_at_retail",
      "brand_vs_brand"
    ],
    "subscription_state": [
      "subscribed",
      "not_subscribed",
      "… -1 more"
    ]
  },
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
    "… 7 more, as /api/console/surfaces"
  ],
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
  "merchants_error": null,
  "max_questions": 100,
  "default_brand_direct_count": 12,
  "default_variant_cap": 20
}
```

### POST /api/console/studies/preview (2C, W&S catalog, 2 questions per tier shown)

`{"merchant": "wiggle-and-snug", "tiers": {"brand_direct": true, "catalog_accuracy": true, "value_incentives": true, "category_control": false}, "stage_total": 50}` against the pipeline's real W&S catalog fixture.

```json
{
  "merchant": {
    "slug": "wiggle-and-snug",
    "brand": "Wiggle & Snug",
    "domain": "trueshopstore.com",
    "kind": "brand",
    "hosting": "parleo",
    "available": true,
    "error": null,
    "record_error": null,
    "read_at": "2026-10-14T18:26:08.147055Z",
    "products": 5,
    "variants": 19,
    "gtins": 6,
    "codes": 2,
    "readback": "5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)"
  },
  "tiers": {
    "brand_direct": {
      "enabled": true,
      "count": 12,
      "source": "ai_from_catalog",
      "questions": [
        {
          "query_text": "Where can I buy Wiggle & Snug Snug-Fit Diapers?",
          "tier": "brand_direct",
          "illustrative": true,
          "expected": [
            "Expected: brand named, trueshopstore.com cited"
          ]
        }
      ],
      "illustrative": true,
      "expected_nulls": "Zero until Wiggle & Snug is retrievable at all on a surface; visibility gates everything below it."
    },
    "catalog_accuracy": {
      "enabled": true,
      "count": 19,
      "source": "catalog",
      "questions": [
        {
          "query_text": "What does the Wiggle & Snug Snug-Fit Diapers Size 1 small pack cost?",
          "tier": "catalog_accuracy",
          "stage": "Ready to Buy",
          "provenance": "catalog",
          "expected_answer": {
            "type": "price",
            "amount": "17.99",
            "currency": "USD",
            "secondary": [
              {
                "type": "pack_count",
                "value": 96
              }
            ]
          },
          "expected": [
            "Expected: $17.99",
            "96 count"
          ],
          "variant_id": "snug-fit-diapers-s1-small"
        },
        {
          "query_text": "What does the Wiggle & Snug Snug-Fit Diapers Size 1 big pack cost?",
          "tier": "catalog_accuracy",
          "stage": "Ready to Buy",
          "provenance": "catalog",
          "expected_answer": {
            "type": "price",
            "amount": "31.99",
            "currency": "USD",
            "secondary": [
              {
                "type": "pack_count",
                "value": 198
              }
            ]
          },
          "expected": [
            "Expected: $31.99",
            "198 count"
          ],
          "variant_id": "snug-fit-diapers-s1-big"
        },
        "… 17 more questions"
      ],
      "sampled": false,
      "variants_available": 19,
      "variant_cap": 20,
      "unavailable": null,
      "skipped_no_price": [],
      "expected_nulls": "Surfaces without feed enrollment show crawl-derived data only. An absent price on those is a distribution gap, not an accuracy failure."
    },
    "value_incentives": {
      "enabled": true,
      "count": 6,
      "source": "catalog",
      "questions": [
        {
          "query_text": "Is there a first-order promo code for Wiggle & Snug, and what does it take off?",
          "tier": "value_incentives",
          "stage": "Ready to Buy",
          "provenance": "catalog",
          "expected_answer": {
            "type": "code",
            "code": "WELCOME10",
            "value_kind": "percent_off",
            "value": "10.00"
          },
          "expected": [
            "Expected: WELCOME10, 10.00% off"
          ],
          "variant_id": null
        },
        {
          "query_text": "Are there any promo codes for Wiggle & Snug Snug-Fit Diapers right now, and what do they take off?",
          "tier": "value_incentives",
          "stage": "Ready to Buy",
          "provenance": "catalog",
          "expected_answer": {
            "type": "code",
            "code": "SNUG3",
            "value_kind": "amount_off",
            "value": "3.00"
          },
          "expected": [
            "Expected: SNUG3, $3.00 off"
          ],
          "variant_id": null
        },
        "… 4 more questions"
      ],
      "mechanics": {
        "code": 2,
        "member_price": 3,
        "points": 1
      },
      "mechanics_absent": [],
      "expected_nulls": "Surfaces without feed enrollment show crawl-derived data only, so a member price may be absent there while present elsewhere."
    },
    "category_control": {
      "enabled": false,
      "count": 0,
      "source": "ai",
      "questions": []
    }
  },
  "stage_total": 50,
  "tally": {
    "ai_written": 62,
    "from_catalog": 25,
    "total": 87,
    "limit": 100,
    "within": true,
    "tone": "ok",
    "text": "62 AI-written + 25 from the catalog = 87 questions, within the 100 limit"
  }
}
```

### POST /api/console/studies/generate (2C)

```json
{
  "study_type": "wiggle_snug_visibility_after_syndication_<6 hex>",
  "study_name": "Wiggle & Snug — visibility after syndication",
  "job_id": 2,
  "status": "pending",
  "tally": {
    "ai_written": 62,
    "from_catalog": 25,
    "total": 87,
    "limit": 100,
    "within": true,
    "tone": "ok",
    "text": "62 AI-written + 25 from the catalog = 87 questions, within the 100 limit"
  }
}
```

### POST /api/console/cycles (2C)

```json
{
  "cycle_code": "WS-2C-TEST",
  "status": "planned",
  "cycle_mode": "query",
  "study_type": "ws-2b-fixture",
  "study_pattern": "brand_at_retail",
  "total_runs_planned": 12,
  "completed_runs": 0,
  "created_at": null,
  "updated_at": null,
  "platforms": [
    "chatgpt",
    "gemini_grounded"
  ],
  "runs_per_query": 1,
  "truecost_tiers": null,
  "id": 2
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

### GET /api/console/visibility?cycle=WS-2B-FIXTURE (2C-1)

The fixture's other_brands_named are all empty and Huggies, in its comparison set, is named by no
answer, so W&S is the only row.

```json
{
  "cycle": "WS-2B-FIXTURE",
  "lede": "Who the answers name, and who they name first, in cycle WS-2B-FIXTURE. Counted per surface: a model-only API, a grounded API and a consumer UI are never added together.",
  "byQuestion": [
    {
      "q": "Is Wiggle & Snug Member Rewards still available?",
      "type": "Brand-direct",
      "tier": "brand_direct",
      "surface": "grounded_api",
      "agent": "chatgpt",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1006",
      "platform": "chatgpt",
      "query_code": "WIG_144",
      "stage": "Research",
      "answered": true,
      "first_basis": "layer1_position"
    },
    {
      "q": "Does Wiggle & Snug sell a Snug-Fit Trial Pack?",
      "type": "Brand-direct",
      "tier": "brand_direct",
      "surface": "grounded_api",
      "agent": "gemini",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1007",
      "platform": "gemini_grounded",
      "query_code": "WIG_148",
      "stage": "Research",
      "answered": true,
      "first_basis": "layer1_position"
    },
    {
      "q": "What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "grounded_api",
      "agent": "chatgpt",
      "named": [],
      "first": null,
      "run": "run-1005",
      "platform": "chatgpt",
      "query_code": "WIG_154",
      "stage": "Ready to Buy",
      "answered": true
    },
    {
      "q": "What does the Wiggle & Snug Snug-Fit Overnight Diapers Size 6 cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "grounded_api",
      "agent": "gemini",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1004",
      "platform": "gemini_grounded",
      "query_code": "WIG_165",
      "stage": "Ready to Buy",
      "answered": true,
      "first_basis": "layer1_position"
    },
    {
      "q": "What does the Wiggle & Snug Cloud Wipes 3-Pack cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "grounded_api",
      "agent": "gemini",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1003",
      "platform": "gemini_grounded",
      "query_code": "WIG_166",
      "stage": "Ready to Buy",
      "answered": true,
      "first_basis": "layer1_position"
    },
    {
      "q": "What does the Wiggle & Snug Bum Balm 4 oz cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "consumer_ui",
      "agent": "aimode",
      "named": [],
      "first": null,
      "run": "run-1008",
      "platform": "aimode",
      "query_code": "WIG_167",
      "stage": "Ready to Buy",
      "answered": false
    },
    {
      "q": "What does the Wiggle & Snug Bum Balm 4 oz cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "grounded_api",
      "agent": "chatgpt",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1002",
      "platform": "chatgpt",
      "query_code": "WIG_167",
      "stage": "Ready to Buy",
      "answered": true,
      "first_basis": "layer1_position"
    },
    {
      "q": "What does the Wiggle & Snug Bum Balm 4 oz cost?",
      "type": "Catalog accuracy",
      "tier": "catalog_accuracy",
      "surface": "grounded_api",
      "agent": "gemini",
      "named": [
        {
          "name": "Wiggle & Snug",
          "you": true
        }
      ],
      "first": {
        "name": "Wiggle & Snug",
        "you": true
      },
      "run": "run-1001",
      "platform": "gemini_grounded",
      "query_code": "WIG_167",
      "stage": "Ready to Buy",
      "answered": true,
      "first_basis": "layer1_position"
    }
  ],
  "ranking": {
    "surface": "grounded_api",
    "rows": [
      {
        "name": "Wiggle & Snug",
        "you": true,
        "named": 6,
        "first": 6,
        "surfaces": {
          "grounded_api": {
            "named": 6,
            "first": 6,
            "agents": {
              "chatgpt": {
                "named": 2,
                "first": 2
              },
              "gemini": {
                "named": 4,
                "first": 4
              }
            }
          },
          "consumer_ui": {
            "named": 0,
            "first": 0,
            "agents": {}
          }
        }
      }
    ],
    "denom": 7,
    "denoms": {
      "grounded_api": 7,
      "consumer_ui": 0
    },
    "agent_denoms": {
      "grounded_api": {
        "chatgpt": 3,
        "gemini": 4
      },
      "consumer_ui": {}
    },
    "first_uncoded": {
      "grounded_api": 0,
      "consumer_ui": 0
    },
    "agent_first_uncoded": {
      "grounded_api": {},
      "consumer_ui": {}
    }
  },
  "note": "First pick is the first brand the answer names, as coded when it was scored. The coding ranks every brand named, so when the comparison set's first brand sits second or later, another brand came first, and the brands the answer named outside the set decide which, by where each first appears. When no coding names that brand (unprompted answers carry no list of other brands), nobody gets the pick.",
  "surfaces": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "answered": 7,
      "runs": 7
    },
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out",
      "answered": 0,
      "runs": 1
    }
  ],
  "tiers": [
    {
      "tier": "brand_direct",
      "label": "Brand-direct"
    },
    {
      "tier": "catalog_accuracy",
      "label": "Catalog accuracy"
    }
  ],
  "first_basis": {
    "layer1_position": 6
  },
  "sources_left_out": 0,
  "divergences": [
    "Visibility is per surface. RankRow.named and RankRow.first are the counts on `ranking.surface` (the highest-fidelity surface with answered runs) and `ranking.denom` is that surface's answered runs; every surface is under `surfaces`, each with its per-agent split. There is no total across surfaces.",
    "byQuestion is one row per run, not one per question with a first pick per agent (Tenant.visibility): an agent can have two surfaces, and a question has several runs.",
    "Brands outside the comparison set come from other_brands_named and are rolled up by name: a name that starts with a comparison-set brand (or alias) is that brand ('Huggies Snug & Dry' is Huggies), and a name that starts with another named brand is that brand. Sources (presented_as 'source', relation 'citation_only') are left out and counted in `sources_left_out`.",
    "RankRow.series is not sent: a sparkline needs two or more cycles, which the console reads itself.",
    "An answer whose first brand neither coding names has `first: null` and `first_basis: 'uncoded'`, counted per surface and agent in `ranking.first_uncoded` / `agent_first_uncoded`."
  ]
}
```

### GET /api/console/visibility?cycle=FL3-wiggle-and-snug-20261014 (2C-1, cycle 229, cut)

Built by `build_visibility` from cycle 229's stored rows, exported read-only on Oct 14 (runs,
questions, Layer 1 mentions, Layer 2 other_brands_named and spans; no answer text beyond the
stored spans, no customer data: the answers are public model output about Parleo's own test
store). Two of 516 rows (one first pick by span position, one uncoded) and 4 of 36 ranking rows.

```json
{
  "cycle": "FL3-wiggle-and-snug-20261014",
  "lede": "Who the answers name, and who they name first, in cycle FL3-wiggle-and-snug-20261014. Counted per surface: a model-only API, a grounded API and a consumer UI are never added together.",
  "byQuestion": [
    {
      "q": "What size of Wiggle & Snug Snug-Fit Diapers should I buy for a 15 lb baby?",
      "type": "Brand-direct",
      "tier": "brand_direct",
      "surface": "grounded_api",
      "agent": "chatgpt",
      "named": [
        {
          "name": "Huggies",
          "you": false
        }
      ],
      "first": {
        "name": "Huggies",
        "you": false
      },
      "run": "run-13146",
      "platform": "chatgpt",
      "query_code": "WIG_145",
      "stage": "Ready to Buy",
      "answered": true,
      "first_basis": "span_position"
    },
    {
      "q": "What are the most popular baby wipe options for everyday use?",
      "type": "Awareness",
      "tier": "unprompted",
      "surface": "grounded_api",
      "agent": "chatgpt",
      "named": [
        {
          "name": "Huggies",
          "you": false
        },
        {
          "name": "Pampers",
          "you": false
        }
      ],
      "first": null,
      "run": "run-12745",
      "platform": "chatgpt",
      "query_code": "WIG_089",
      "stage": "Awareness",
      "answered": true,
      "first_basis": "uncoded"
    }
  ],
  "ranking": {
    "surface": "grounded_api",
    "rows": [
      {
        "name": "Wiggle & Snug",
        "you": true,
        "named": 170,
        "first": 169,
        "surfaces": {
          "grounded_api": {
            "named": 170,
            "first": 169,
            "agents": {
              "chatgpt": {
                "named": 63,
                "first": 62
              },
              "gemini": {
                "named": 107,
                "first": 107
              }
            }
          }
        }
      },
      {
        "name": "Huggies",
        "you": false,
        "named": 138,
        "first": 49,
        "surfaces": {
          "grounded_api": {
            "named": 138,
            "first": 49,
            "agents": {
              "chatgpt": {
                "named": 84,
                "first": 40
              },
              "gemini": {
                "named": 54,
                "first": 9
              }
            }
          }
        }
      },
      {
        "name": "Pampers",
        "you": false,
        "named": 89,
        "first": 38,
        "surfaces": {
          "grounded_api": {
            "named": 89,
            "first": 38,
            "agents": {
              "chatgpt": {
                "named": 37,
                "first": 11
              },
              "gemini": {
                "named": 52,
                "first": 27
              }
            }
          }
        }
      },
      {
        "name": "Parent’s Choice",
        "you": false,
        "named": 5,
        "first": 1,
        "surfaces": {
          "grounded_api": {
            "named": 5,
            "first": 1,
            "agents": {
              "chatgpt": {
                "named": 5,
                "first": 1
              },
              "gemini": {
                "named": 0,
                "first": 0
              }
            }
          }
        }
      }
    ],
    "denom": 514,
    "denoms": {
      "grounded_api": 514
    },
    "agent_denoms": {
      "grounded_api": {
        "chatgpt": 256,
        "gemini": 258
      }
    },
    "first_uncoded": {
      "grounded_api": 27
    },
    "agent_first_uncoded": {
      "grounded_api": {
        "chatgpt": 11,
        "gemini": 16
      }
    }
  },
  "note": "First pick is the first brand the answer names, as coded when it was scored. The coding ranks every brand named, so when the comparison set's first brand sits second or later, another brand came first, and the brands the answer named outside the set decide which, by where each first appears. When no coding names that brand (unprompted answers carry no list of other brands), nobody gets the pick.",
  "surfaces": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "answered": 514,
      "runs": 516
    }
  ],
  "tiers": [
    {
      "tier": "unprompted",
      "label": "Unprompted"
    },
    {
      "tier": "brand_direct",
      "label": "Brand-direct"
    },
    {
      "tier": "catalog_accuracy",
      "label": "Catalog accuracy"
    },
    {
      "tier": "value_incentives",
      "label": "Value & incentives"
    }
  ],
  "first_basis": {
    "layer1_position": 256,
    "uncoded": 27,
    "span_position": 6
  },
  "sources_left_out": 43,
  "divergences": [
    "Visibility is per surface. RankRow.named and RankRow.first are the counts on `ranking.surface` (the highest-fidelity surface with answered runs) and `ranking.denom` is that surface's answered runs; every surface is under `surfaces`, each with its per-agent split. There is no total across surfaces.",
    "byQuestion is one row per run, not one per question with a first pick per agent (Tenant.visibility): an agent can have two surfaces, and a question has several runs.",
    "Brands outside the comparison set come from other_brands_named and are rolled up by name: a name that starts with a comparison-set brand (or alias) is that brand ('Huggies Snug & Dry' is Huggies), and a name that starts with another named brand is that brand. Sources (presented_as 'source', relation 'citation_only') are left out and counted in `sources_left_out`.",
    "RankRow.series is not sent: a sparkline needs two or more cycles, which the console reads itself.",
    "An answer whose first brand neither coding names has `first: null` and `first_basis: 'uncoded'`, counted per surface and agent in `ranking.first_uncoded` / `agent_first_uncoded`."
  ]
}
```

### GET /api/console/record/list?merchant=wiggle-and-snug (2C-1)

```json
{
  "merchant": "wiggle-and-snug",
  "kind": "brand",
  "hosting": "parleo",
  "products": [
    {
      "sku": "catalog_product:27",
      "listing_id": 90,
      "title": "Snug-Fit Diapers",
      "sub": "Wiggle & Snug · 12 variants · trueshopstore.com",
      "variants": 12,
      "status": {
        "label": "Published to 4 channels",
        "tone": "ok"
      },
      "diffs": 0
    },
    {
      "sku": "catalog_product:28",
      "listing_id": 91,
      "title": "Snug-Fit Overnight Diapers",
      "sub": "Wiggle & Snug · 4 variants · trueshopstore.com",
      "variants": 4,
      "status": {
        "label": "1 page difference",
        "tone": "warn"
      },
      "diffs": 1
    },
    {
      "sku": "catalog_product:29",
      "listing_id": 92,
      "title": "Cloud Wipes 3-Pack",
      "sub": "Wiggle & Snug · 1 variant · trueshopstore.com",
      "variants": 1,
      "status": {
        "label": "1 page difference",
        "tone": "warn"
      },
      "diffs": 1
    },
    {
      "sku": "catalog_product:30",
      "listing_id": 93,
      "title": "Bum Balm 4 oz",
      "sub": "Wiggle & Snug · 1 variant · trueshopstore.com",
      "variants": 1,
      "status": {
        "label": "Published to 4 channels",
        "tone": "ok"
      },
      "diffs": 0
    },
    {
      "sku": "catalog_product:31",
      "listing_id": 94,
      "title": "Snug-Fit Trial Pack",
      "sub": "Wiggle & Snug · 1 variant · trueshopstore.com",
      "variants": 1,
      "status": {
        "label": "Published to 4 channels",
        "tone": "ok"
      },
      "diffs": 0
    }
  ],
  "read_errors": {}
}
```

### GET /api/console/record?merchant=wiggle-and-snug&product=91 (2C-1)

Supply as `test_console_truesync.py` fakes it, plus the W&S reference read
(`tests/fixtures/console/supply_reference_ws.json`, illustrative): the Overnight Size 6 page's
name disagrees with the record. The artifact is elided.

```json
{
  "kind": "product",
  "sku": "catalog_product:28",
  "title": "Snug-Fit Overnight Diapers",
  "sub": "Wiggle & Snug · 4 variants · trueshopstore.com",
  "status": {
    "label": "1 page difference",
    "tone": "warn"
  },
  "fields": [
    {
      "k": "Name",
      "v": "Snug-Fit Overnight Diapers",
      "prov": "brand"
    },
    {
      "k": "Brand",
      "v": "Wiggle & Snug",
      "prov": "brand"
    },
    {
      "k": "Product page",
      "v": "https://trueshopstore.com/products/snug-fit-overnight-diapers",
      "prov": "brand",
      "mono": true
    },
    {
      "k": "Price",
      "v": "$23.99 to $29.99",
      "prov": "brand",
      "note": "4 variants"
    },
    {
      "k": "GTIN",
      "v": "not carried",
      "prov": "brand",
      "mono": false
    },
    {
      "k": "Count",
      "v": "42 to 62",
      "prov": "brand"
    },
    {
      "k": "Published",
      "v": "2026-08-28",
      "prov": "brand",
      "note": "schemaorg-merchant-listing-2026-08-18"
    },
    {
      "k": "Name · Snug-Fit Overnight Diapers Size 6 (42 ct)",
      "v": "Snug-Fit Overnight Diapers Size 6 (42 ct)",
      "prov": "brand",
      "was": "Overnight Diapers Size 6, 42 Count",
      "diff": true,
      "note": "trueshopstore.com, read 2026-10-09 by our own fetch. only in the record: snug fit",
      "finding": "name_differs",
      "variant_id": "snug-fit-overnight-s6",
      "url": "https://trueshopstore.com/products/snug-fit-overnight-diapers"
    }
  ],
  "issues": [
    {
      "title": "Not published to UCP / Universal Incentive Protocol, Agentic Commerce Protocol, Google Merchant Center feed",
      "detail": "The publish failed: not implemented in Step 2.",
      "tone": "warn",
      "channel": "ucp_uip,acp,merchant_center",
      "verdict": "blocked"
    },
    {
      "title": "Schema.org Product/Offer: amount_off approximated by the channel",
      "detail": "schema.org: the resulting price is expressible; the amount off itself is only a hint (specs §4).",
      "tone": "warn",
      "channel": "schema_org",
      "verdict": "approx"
    },
    {
      "title": "Schema.org Product/Offer: percent_off approximated by the channel",
      "detail": "schema.org: price and priceSpecification carry the resulting price; the percentage itself is only a hint (specs §4).",
      "tone": "warn",
      "channel": "schema_org",
      "verdict": "approx"
    },
    {
      "title": "Schema.org Product/Offer: new_customer dropped by the channel",
      "detail": "schema.org: no new-customer eligibility structure (specs matrix).",
      "tone": "warn",
      "channel": "schema_org",
      "verdict": "dropped"
    },
    {
      "title": "Schema.org Product/Offer: effective_net_price approximated by the channel",
      "detail": "The calculator's net price includes a member-only offer, so the public Offer.price quotes list; the member price is carried in priceSpecification, gated by tier.",
      "tone": "warn",
      "channel": "schema_org",
      "verdict": "approx"
    },
    {
      "title": "Schema.org Product/Offer: stacking note",
      "detail": "schema.org has no stacking vocabulary; combinability is stated in the description only (specs matrix).",
      "tone": "neu",
      "channel": "schema_org",
      "verdict": "info"
    }
  ],
  "json": "… the schema_org artifact, pretty-printed (elided here) …",
  "variants": [
    {
      "id": "snug-fit-overnight-s3",
      "name": "Snug-Fit Overnight Diapers Size 3 (62 ct)",
      "price": "$23.99",
      "status": "Not read yet",
      "tone": "neu",
      "gtin": null,
      "list_price": "23.99",
      "member_price": null,
      "count": 62,
      "pages": []
    },
    {
      "id": "snug-fit-overnight-s4",
      "name": "Snug-Fit Overnight Diapers Size 4 (54 ct)",
      "price": "$25.99",
      "status": "Not read yet",
      "tone": "neu",
      "gtin": null,
      "list_price": "25.99",
      "member_price": null,
      "count": 54,
      "pages": []
    },
    {
      "id": "snug-fit-overnight-s5",
      "name": "Snug-Fit Overnight Diapers Size 5 (48 ct)",
      "price": "$27.99",
      "status": "Not read yet",
      "tone": "neu",
      "gtin": null,
      "list_price": "27.99",
      "member_price": null,
      "count": 48,
      "pages": []
    },
    {
      "id": "snug-fit-overnight-s6",
      "name": "Snug-Fit Overnight Diapers Size 6 (42 ct)",
      "price": "$29.99",
      "status": "Page differs: name",
      "tone": "warn",
      "gtin": null,
      "list_price": "29.99",
      "member_price": null,
      "count": 42,
      "pages": [
        "https://trueshopstore.com/products/snug-fit-overnight-diapers"
      ]
    }
  ],
  "merchant": "wiggle-and-snug",
  "listing_id": 91,
  "product_url": "https://trueshopstore.com/products/snug-fit-overnight-diapers",
  "merchant_kind": "brand",
  "hosting": "parleo",
  "source": "published",
  "source_basis": "merchant",
  "json_channel": "schema_org",
  "channels": {
    "deal_directory": {
      "status": "published",
      "published_at": "2026-08-21T20:16:23.989748Z"
    },
    "mcp": {
      "status": "published",
      "published_at": "2026-08-21T20:16:23.843494Z"
    },
    "deals_api": {
      "status": "published",
      "published_at": "2026-08-21T20:16:23.692383Z"
    },
    "ucp_uip": {
      "status": "failed",
      "published_at": null
    },
    "acp": {
      "status": "failed",
      "published_at": null
    },
    "merchant_center": {
      "status": "failed",
      "published_at": null
    },
    "schema_org": {
      "status": "published",
      "published_at": "2026-08-21T20:16:23.305701Z"
    }
  },
  "reference_run": {
    "id": 7,
    "status": "done",
    "started_at": "2026-10-09T14:41:20+00:00",
    "finished_at": "2026-10-09T14:43:00+00:00",
    "counts": {},
    "allow_hosted_render": true
  },
  "read_errors": {},
  "divergences": [
    "Field.prov is mapped once (RECORD_PROVENANCE): source 'published' on a seller merchant is 'retail', on a brand merchant 'brand'; 'scrape' is 'parleo'; a value taken from an agent answer is 'agent'. A published listing whose merchant kind is unknown is 'unknown', which the console renders neutral.",
    "A listing's source is supply's provenance mix (listing rows); an external merchant's feed has no listing rows, so its record is 'published' with source_basis 'feed'.",
    "Field.was is what the latest reference read found on the page, not an earlier record value; `diff` marks the field, and `note` says which page, when and how it was read.",
    "Variant-level disagreements are their own fields ('Name · <variant>'), since 2A compares each variant with each page.",
    "`json` is the schema_org publication's artifact; empty when the product was never compiled for schema.org (an external merchant's feed is not compiled here).",
    "A price the record does not carry reads 'not carried', never blank.",
    "issues are the validator and expressiveness lines of the publications that compiled (the artifacts the channels host); a failed publish is one 'Not published to …' issue with its error, as the TrueSync matrix shows it blocked."
  ]
}
```

### GET /api/console/record?merchant=brandco&product=feed:brandco:00012345678905 (2C-1, external seller)

Brandco is soa's external test fake, served from its feed with no price on the wipes row; the
reference read is the 2C sample's (`supply_feed_brandco.json`), whose target.com page shows
"216, 3" against the record's 72.

```json
{
  "kind": "offer",
  "sku": "feed:brandco:00012345678905",
  "title": "Brandco Wipes",
  "sub": "Brandco · 1 variant · brandco.test",
  "status": {
    "label": "1 page difference",
    "tone": "warn"
  },
  "fields": [
    {
      "k": "Name",
      "v": "Brandco Wipes",
      "prov": "retail"
    },
    {
      "k": "Brand",
      "v": "Brandco",
      "prov": "retail"
    },
    {
      "k": "Product page",
      "v": "not carried",
      "prov": "retail",
      "mono": false
    },
    {
      "k": "Price",
      "v": "not carried",
      "prov": "retail"
    },
    {
      "k": "GTIN",
      "v": "00012345678905",
      "prov": "retail",
      "mono": true
    },
    {
      "k": "Count",
      "v": "72",
      "prov": "retail"
    },
    {
      "k": "Published",
      "v": "2026-10-08",
      "prov": "retail",
      "note": "sku-feed-v1"
    },
    {
      "k": "Pack count · 72 ct",
      "v": "72",
      "prov": "retail",
      "was": "216, 3",
      "diff": true,
      "note": "target.com, read 2026-10-09 by our own fetch",
      "finding": "pack_differs",
      "variant_id": "00012345678905",
      "url": "https://www.target.com/p/2"
    }
  ],
  "issues": [],
  "json": "",
  "variants": [
    {
      "id": "00012345678905",
      "name": "72 ct",
      "price": "not carried",
      "status": "Page differs: pack count",
      "tone": "warn",
      "gtin": "00012345678905",
      "list_price": null,
      "member_price": null,
      "count": 72,
      "pages": [
        "https://www.target.com/p/2"
      ]
    }
  ],
  "merchant": "brandco",
  "listing_id": 501,
  "product_url": null,
  "merchant_kind": "seller",
  "hosting": "external",
  "source": "published",
  "source_basis": "feed",
  "json_channel": null,
  "channels": {},
  "reference_run": {
    "id": 4,
    "status": "done",
    "started_at": "2026-10-09T14:40:00+00:00",
    "finished_at": "2026-10-09T14:44:00+00:00",
    "counts": {},
    "allow_hosted_render": true
  },
  "read_errors": {},
  "divergences": [
    "… as in RECORD_DIVERGENCES …"
  ]
}
```

### GET /api/console/overview?cycle=WS-2B-FIXTURE&merchant=wiggle-and-snug (2C-2b, cut)

The W&S fixture cycle with the W&S access sample and the production-shaped reference read. One
product of four, the consumer UI and the ranking rows cut (`rules` is `TEMPLATES`, also cut).

```json
{
  "cycle": "WS-2B-FIXTURE",
  "started": "2026-10-09",
  "surface": "grounded_api",
  "surfaces": [
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out"
    },
    {
      "surface": "grounded_api",
      "label": "API with search grounding"
    }
  ],
  "scored_cycles": 1,
  "previous_cycle": null,
  "changes_note": "First cycle. Changes appear from the next one.",
  "coverage": {
    "questions": 6,
    "agents": 3,
    "runs": 8,
    "answers": 7,
    "unprompted": 0
  },
  "read_errors": {},
  "by_surface": {
    "grounded_api": {
      "agents": [
        {
          "agent": "chatgpt",
          "answers": 3,
          "named": 2,
          "first": 2,
          "pricesRight": "0 of 2",
          "wrong": 2,
          "note": "Wrong on 2 prices.",
          "delta": "",
          "named_of": 3,
          "exact": 0,
          "scored": 2,
          "stale": 0,
          "unverifiable": 0,
          "answered_with_other_brand": 0,
          "did_not_know": 0,
          "note_rule": "agent.wrong",
          "delta_status": "first_cycle"
        },
        {
          "agent": "gemini",
          "answers": 4,
          "named": 4,
          "first": 4,
          "pricesRight": "1 of 3",
          "wrong": 2,
          "note": "Wrong on 2 prices.",
          "delta": "",
          "named_of": 4,
          "exact": 1,
          "scored": 3,
          "stale": 0,
          "unverifiable": 0,
          "answered_with_other_brand": 0,
          "did_not_know": 1,
          "note_rule": "agent.wrong",
          "delta_status": "first_cycle"
        }
      ],
      "signals": [],
      "summary": {
        "lines": [
          "First in 6 of 7 answers, ahead of every other brand.",
          "Prices right in 1 of 5 scored answers, 0 answered with another brand's price.",
          "No signal crossed its threshold this cycle."
        ],
        "text": "First in 6 of 7 answers, ahead of every other brand. Prices right in 1 of 5 scored answers, 0 answered with another brand's price. No signal crossed its threshold this cycle.",
        "signal": null
      },
      "changes": [],
      "changes_status": "first_cycle",
      "changes_note": "First cycle. Changes appear from the next one.",
      "tier": "all",
      "products": [
        {
          "name": "Wiggle & Snug Bum Balm 4 oz",
          "sku": "bum-balm-4oz",
          "named": 2,
          "first": 2,
          "quoted": "$12.99, 1 of 2 runs (Gemini 1). $14.99, 1 of 2 runs (ChatGPT 1)",
          "live": "$12.99 at trueshopstore.com, our own fetch, Oct 14",
          "status": "wrong",
          "issue": "Quoted a wrong price in 1 of 2 runs.",
          "route": "true-value",
          "cell_status": "wrong",
          "quote": "$14.99",
          "retailer": "trueshopstore.com",
          "runs": 2,
          "answered": 2,
          "issue_rule": "product.wrong",
          "wrong_runs": 1,
          "reference_source": "honest_fetch",
          "observed_at": "2026-10-14T17:01:18+00:00",
          "live_price": "$12.99",
          "answer_ids": [
            "run-1001",
            "run-1002"
          ],
          "quote_groups": [
            {
              "stated": "12.99",
              "swap_product": null,
              "runs": 1,
              "agents": {
                "gemini": 1
              }
            },
            {
              "stated": "14.99",
              "swap_product": null,
              "runs": 1,
              "agents": {
                "chatgpt": 1
              }
            }
          ]
        }
      ],
      "totals": {
        "answers": 7,
        "named": 6,
        "first": 6,
        "named_of": 7,
        "exact": 1,
        "scored": 5,
        "wrong": 4,
        "stale": 0,
        "price_answered": 5,
        "partial": 0,
        "unverifiable": 0,
        "other_brand": 0,
        "left_out": 0,
        "unknown": 1,
        "fabricated": 0,
        "brand_scored": 2
      }
    },
    "consumer_ui": "… cut"
  },
  "ranking": {
    "surface": "grounded_api",
    "denom": 7,
    "denoms": {
      "grounded_api": 7,
      "consumer_ui": 0
    },
    "rows": "… Visibility's ranking rows, as /visibility sends them"
  }
}
```

### GET /api/console/visibility?cycle=WS-2B-FIXTURE, the 2C-2 additions (cut)

```json
{
  "headline": "First in 6 of 7 answers.",
  "matrix": {
    "grounded_api": {
      "surface": "grounded_api",
      "agents": [
        "chatgpt",
        "gemini"
      ],
      "rows": [
        {
          "q": "Is Wiggle & Snug Member Rewards still available?",
          "query_code": "WIG_144",
          "stage": "Research",
          "tier": "brand_direct",
          "type": "Brand-direct",
          "cells": {
            "chatgpt": {
              "first": {
                "name": "Wiggle & Snug",
                "you": true,
                "runs": 1
              },
              "runs": 1,
              "answered": 1,
              "picks": {
                "Wiggle & Snug": 1
              }
            }
          }
        },
        {
          "q": "Does Wiggle & Snug sell a Snug-Fit Trial Pack?",
          "query_code": "WIG_148",
          "stage": "Research",
          "tier": "brand_direct",
          "type": "Brand-direct",
          "cells": {
            "gemini": {
              "first": {
                "name": "Wiggle & Snug",
                "you": true,
                "runs": 1
              },
              "runs": 1,
              "answered": 1,
              "picks": {
                "Wiggle & Snug": 1
              }
            }
          }
        }
      ]
    }
  },
  "by_stage": {
    "grounded_api": {
      "surface": "grounded_api",
      "stages": [
        {
          "stage": "Research",
          "label": "Research",
          "answered": 2,
          "named": 2,
          "first": 2,
          "top": {
            "name": "Wiggle & Snug",
            "first": 2,
            "you": true
          }
        },
        {
          "stage": "Ready to Buy",
          "label": "Ready to buy",
          "answered": 5,
          "named": 4,
          "first": 4,
          "top": {
            "name": "Wiggle & Snug",
            "first": 4,
            "you": true
          }
        }
      ],
      "stages_by_tier": {
        "all": [
          {
            "stage": "Research",
            "label": "Research",
            "answered": 2,
            "named": 2,
            "first": 2,
            "top": {
              "name": "Wiggle & Snug",
              "first": 2,
              "you": true
            }
          },
          {
            "stage": "Ready to Buy",
            "label": "Ready to buy",
            "answered": 5,
            "named": 4,
            "first": 4,
            "top": {
              "name": "Wiggle & Snug",
              "first": 4,
              "you": true
            }
          }
        ],
        "brand_direct": [
          {
            "stage": "Research",
            "label": "Research",
            "answered": 2,
            "named": 2,
            "first": 2,
            "top": {
              "name": "Wiggle & Snug",
              "first": 2,
              "you": true
            }
          }
        ],
        "catalog_accuracy": [
          {
            "stage": "Ready to Buy",
            "label": "Ready to buy",
            "answered": 5,
            "named": 4,
            "first": 4,
            "top": {
              "name": "Wiggle & Snug",
              "first": 4,
              "you": true
            }
          }
        ]
      },
      "tiers": [
        {
          "tier": "brand_direct",
          "label": "Brand-direct",
          "answered": 2,
          "named": 2,
          "first": 2,
          "top": {
            "name": "Wiggle & Snug",
            "first": 2,
            "you": true
          }
        },
        {
          "tier": "catalog_accuracy",
          "label": "Catalog accuracy",
          "answered": 5,
          "named": 4,
          "first": 4,
          "top": {
            "name": "Wiggle & Snug",
            "first": 4,
            "you": true
          }
        }
      ]
    }
  }
}
```

### GET /api/console/true-value?cycle=WS-2B-FIXTURE&merchant=wiggle-and-snug (2C-2b, one row)

One retailer in the record, so the columns are the agents, per surface; each row keeps its
one-retailer cell in `retailer_cells`. The live price is the newest page read. The ladder is Bum
Balm's (the variant this cycle asked about most): the record's offers state its prices, so no
step comes from a page read here; Size 1 small's Member+ step does (test_console_2c2b).

```json
{
  "column_kind": "agent",
  "columns": [
    {
      "id": "chatgpt",
      "name": "ChatGPT",
      "kind": "agent",
      "retailer": "trueshopstore.com",
      "retailer_name": "trueshopstore.com"
    },
    {
      "id": "gemini",
      "name": "Gemini",
      "kind": "agent",
      "retailer": "trueshopstore.com",
      "retailer_name": "trueshopstore.com"
    }
  ],
  "columns_by_surface": {
    "consumer_ui": [
      {
        "id": "aimode",
        "name": "Google AI Mode",
        "kind": "agent",
        "retailer": "trueshopstore.com",
        "retailer_name": "trueshopstore.com"
      }
    ],
    "grounded_api": [
      {
        "id": "chatgpt",
        "name": "ChatGPT",
        "kind": "agent",
        "retailer": "trueshopstore.com",
        "retailer_name": "trueshopstore.com"
      },
      {
        "id": "gemini",
        "name": "Gemini",
        "kind": "agent",
        "retailer": "trueshopstore.com",
        "retailer_name": "trueshopstore.com"
      }
    ]
  },
  "retailer_columns": [
    {
      "id": "trueshopstore.com",
      "name": "trueshopstore.com",
      "you": true
    }
  ],
  "surface": "grounded_api",
  "surfaces": [
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out"
    },
    {
      "surface": "grounded_api",
      "label": "API with search grounding"
    }
  ],
  "rows": [
    {
      "product": "Wiggle & Snug Bum Balm 4 oz",
      "sku": "bum-balm-4oz",
      "cells": {
        "chatgpt": {
          "quoted": "$14.99",
          "live": "$12.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 1,
          "reference_source": "honest_fetch",
          "method": "json_ld",
          "observed_at": "2026-10-14T17:01:18+00:00",
          "live_basis": "reference_read",
          "surface": "grounded_api",
          "by_surface": {
            "grounded_api": {
              "quoted": "$14.99",
              "status": "wrong",
              "outcome": "wrong",
              "runs": 1
            }
          },
          "quotes": [
            {
              "agent": "chatgpt",
              "surface": "grounded_api",
              "outcome": "wrong",
              "stated": "14.99",
              "run": "run-1002"
            }
          ]
        },
        "gemini": {
          "quoted": "$12.99",
          "live": "$12.99",
          "status": "exact",
          "outcome": "exact",
          "runs": 1,
          "reference_source": "honest_fetch",
          "method": "json_ld",
          "observed_at": "2026-10-14T17:01:18+00:00",
          "live_basis": "reference_read",
          "surface": "grounded_api",
          "by_surface": {
            "grounded_api": {
              "quoted": "$12.99",
              "status": "exact",
              "outcome": "exact",
              "runs": 1
            }
          },
          "quotes": [
            {
              "agent": "gemini",
              "surface": "grounded_api",
              "outcome": "exact",
              "stated": "12.99",
              "run": "run-1001"
            }
          ]
        },
        "aimode": {
          "quoted": "—",
          "live": "$12.99",
          "status": "none",
          "outcome": null,
          "runs": 0,
          "reference_source": "honest_fetch",
          "method": "json_ld",
          "observed_at": "2026-10-14T17:01:18+00:00",
          "live_basis": "reference_read",
          "surface": null,
          "by_surface": {
            "consumer_ui": {
              "quoted": "—",
              "status": "missed",
              "outcome": "absent",
              "runs": 1
            }
          },
          "quotes": [
            {
              "agent": "aimode",
              "surface": "consumer_ui",
              "outcome": "absent",
              "stated": null,
              "run": "run-1008"
            }
          ]
        }
      },
      "retailer_cells": {
        "trueshopstore.com": {
          "quoted": "$14.99",
          "live": "$12.99",
          "status": "wrong",
          "outcome": "wrong",
          "runs": 2,
          "reference_source": "honest_fetch",
          "method": "json_ld",
          "observed_at": "2026-10-14T17:01:18+00:00",
          "live_basis": "reference_read",
          "surface": "grounded_api",
          "by_surface": {
            "consumer_ui": {
              "quoted": "—",
              "status": "missed",
              "outcome": "absent",
              "runs": 1
            },
            "grounded_api": {
              "quoted": "$14.99",
              "status": "wrong",
              "outcome": "wrong",
              "runs": 2
            }
          },
          "quotes": [
            {
              "agent": "gemini",
              "surface": "grounded_api",
              "outcome": "exact",
              "stated": "12.99",
              "run": "run-1001"
            },
            {
              "agent": "chatgpt",
              "surface": "grounded_api",
              "outcome": "wrong",
              "stated": "14.99",
              "run": "run-1002"
            },
            {
              "agent": "aimode",
              "surface": "consumer_ui",
              "outcome": "absent",
              "stated": null,
              "run": "run-1008"
            }
          ]
        }
      }
    }
  ],
  "by_agent": {
    "consumer_ui": {
      "aimode": {
        "exact": 0,
        "scored": 0,
        "wrong": 0,
        "stale": 0,
        "partial": 0,
        "unverifiable": 0,
        "left_out": 1,
        "other_brand": 0
      }
    },
    "grounded_api": {
      "gemini": {
        "exact": 1,
        "scored": 3,
        "wrong": 2,
        "stale": 0,
        "partial": 0,
        "unverifiable": 0,
        "left_out": 0,
        "other_brand": 0
      },
      "chatgpt": {
        "exact": 0,
        "scored": 2,
        "wrong": 2,
        "stale": 0,
        "partial": 0,
        "unverifiable": 0,
        "left_out": 0,
        "other_brand": 0
      }
    }
  },
  "programs": [
    {
      "name": "Member Rewards Member+",
      "terms": "Member+ discount, stated without a price",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "member_price",
      "code": null,
      "tier_name": "Member+",
      "valid_until": null,
      "asked": 0,
      "scored": 0,
      "right": 0,
      "surface": null,
      "by_surface": {},
      "source": "record",
      "offer_ids": []
    },
    {
      "name": "WELCOME10",
      "terms": "10% off, new customers",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "percent_off",
      "code": "WELCOME10",
      "tier_name": null,
      "valid_until": null,
      "asked": 0,
      "scored": 0,
      "right": 0,
      "surface": null,
      "by_surface": {},
      "source": "record",
      "offer_ids": [
        "wiggle-and-snug:deal:1627:bum-balm-4oz",
        "wiggle-and-snug:deal:1627:cloud-wipes-3pack",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s1-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s1-small",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s2-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s2-small",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s3-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s3-small",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s4-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s4-small",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s5-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s5-small",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s6-big",
        "wiggle-and-snug:deal:1627:snug-fit-diapers-s6-small",
        "wiggle-and-snug:deal:1627:snug-fit-overnight-s3",
        "wiggle-and-snug:deal:1627:snug-fit-overnight-s4",
        "wiggle-and-snug:deal:1627:snug-fit-overnight-s5",
        "wiggle-and-snug:deal:1627:snug-fit-overnight-s6",
        "wiggle-and-snug:deal:1627:snug-fit-trial-pack"
      ]
    },
    {
      "name": "SNUG3",
      "terms": "$3.00 off",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "mfr_coupon",
      "code": "SNUG3",
      "tier_name": null,
      "valid_until": null,
      "asked": 0,
      "scored": 0,
      "right": 0,
      "surface": null,
      "by_surface": {},
      "source": "record",
      "offer_ids": [
        "brand_incentive:2"
      ]
    },
    {
      "name": "Member Rewards points",
      "terms": "points on 19 offers",
      "agentsRight": "not asked this cycle",
      "tone": "neu",
      "mechanic": "points",
      "code": null,
      "tier_name": null,
      "valid_until": null,
      "asked": 0,
      "scored": 0,
      "right": 0,
      "surface": null,
      "by_surface": {},
      "source": "record",
      "offer_ids": [
        "wiggle-and-snug:deal:1629:bum-balm-4oz",
        "wiggle-and-snug:deal:1629:cloud-wipes-3pack",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s1-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s1-small",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s2-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s2-small",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s3-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s3-small",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s4-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s4-small",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s5-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s5-small",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s6-big",
        "wiggle-and-snug:deal:1629:snug-fit-diapers-s6-small",
        "wiggle-and-snug:deal:1629:snug-fit-overnight-s3",
        "wiggle-and-snug:deal:1629:snug-fit-overnight-s4",
        "wiggle-and-snug:deal:1629:snug-fit-overnight-s5",
        "wiggle-and-snug:deal:1629:snug-fit-overnight-s6",
        "wiggle-and-snug:deal:1629:snug-fit-trial-pack"
      ]
    }
  ],
  "ladder": {
    "title": "Bum Balm 4 oz",
    "sub": "The product this cycle asked about most, in 3 runs.",
    "steps": [
      {
        "label": "List",
        "value": "$12.99",
        "pct": 100,
        "kind": "ink",
        "source": "record",
        "amount": "12.99",
        "note": "from the record"
      },
      {
        "label": "Member",
        "value": "$10.99",
        "pct": 85,
        "kind": "b",
        "source": "record",
        "basis": "member_price",
        "amount": "10.99",
        "observed_at": null,
        "note": "from the record"
      },
      {
        "label": "Member+",
        "value": "$7.34",
        "pct": 57,
        "kind": "b",
        "source": "record",
        "basis": "effective_net_price",
        "amount": "7.34",
        "observed_at": null,
        "note": "from the record"
      }
    ],
    "note": "Only stated prices. No discount is computed here. Stated without a price, so not drawn: WELCOME10 10% off.",
    "variant_id": "bum-balm-4oz",
    "listing_id": 93,
    "unpriced": [
      "WELCOME10 10% off"
    ]
  },
  "receipt": {
    "title": "What a shopper pays",
    "sub": "Bum Balm 4 oz",
    "rows": [
      {
        "k": "List price",
        "v": "$12.99",
        "tag": "trueshopstore.com"
      },
      {
        "k": "Member+, from the record",
        "v": "-$5.65",
        "kind": "minus",
        "tag": "Stated by the record"
      },
      {
        "k": "The lowest stated price",
        "v": "$7.34",
        "kind": "big"
      }
    ]
  },
  "cell_rule": "A cell is the worst outcome among the runs that quoted a price for it (wrong, then stale, then partial, then exact). When no run quoted a price, it is left out. The quote shown is that run's.",
  "read_errors": {}
}
```

### GET /api/console/accessibility?merchant=wiggle-and-snug, the 2C-2 additions (cut)

```json
{
  "checks": [
    {
      "name": "robots.txt names answer-time agents",
      "value": "not checked",
      "status": "not_checked",
      "checked": false,
      "key": "robots",
      "basis": "supply's access payload does not carry each token's rule source (an explicit group or the wildcard)"
    },
    {
      "name": "Product markup on product pages",
      "value": "19 of 19",
      "status": "ok",
      "checked": true,
      "got": 19,
      "of": 19,
      "key": "markup",
      "basis": "reads with method json_ld"
    },
    {
      "name": "GTIN in markup",
      "value": "6 of 19",
      "status": "partial",
      "checked": true,
      "got": 6,
      "of": 19,
      "key": "gtin",
      "basis": "pages read whose record carries a GTIN, read with structured data, without a gtin_missing_on_page finding, over every page read"
    },
    {
      "name": "Program price in markup",
      "value": "7 of 19",
      "status": "partial",
      "checked": true,
      "got": 7,
      "of": 19,
      "key": "member_price",
      "basis": "reads with member_price present"
    },
    {
      "name": "Needs a hosted render",
      "value": "0 of 19",
      "status": "ok",
      "checked": true,
      "got": 0,
      "of": 19,
      "key": "hosted_render",
      "basis": "reads that came from the hosted renderer. 0 is the good answer"
    },
    {
      "name": "Edge lets signed agents in",
      "value": "not checked",
      "status": "not_checked",
      "checked": false,
      "key": "signed_agents",
      "basis": "signed-agent requests are not probed yet"
    },
    {
      "name": "Protocol profile (UCP, MCP, llms.txt)",
      "value": "not checked",
      "status": "not_checked",
      "checked": false,
      "key": "protocol",
      "basis": "the protocol profile is not read yet"
    }
  ],
  "agent_checks": [
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
  "problems": 0,
  "requests": [
    {
      "identity": "OAI-SearchBot",
      "vendor": "chatgpt",
      "agent": "chatgpt",
      "result": "1 of 1 pages answered",
      "ok": true,
      "code": "ok",
      "measured": true
    },
    {
      "identity": "Claude-User",
      "vendor": "claude",
      "agent": "claude",
      "result": "not measured: no verified UA configured",
      "ok": false,
      "code": "—",
      "measured": false
    }
  ]
}
```

### GET /api/console/record?merchant=wiggle-and-snug&product=91, the 2C-2 additions (cut)

```json
{
  "variants": [
    {
      "id": "snug-fit-overnight-s3",
      "name": "Snug-Fit Overnight Diapers Size 3 (62 ct)",
      "price": "$23.99",
      "status": "Matches the page",
      "tone": "ok",
      "gtin": null,
      "list_price": "23.99",
      "member_price": null,
      "member_source": null,
      "member_note": null,
      "count": 62,
      "pages": [
        "https://trueshopstore.com/products/snug-fit-overnight-diapers"
      ]
    },
    {
      "id": "snug-fit-overnight-s4",
      "name": "Snug-Fit Overnight Diapers Size 4 (54 ct)",
      "price": "$25.99",
      "status": "Matches the page",
      "tone": "ok",
      "gtin": null,
      "list_price": "25.99",
      "member_price": null,
      "member_source": null,
      "member_note": null,
      "count": 54,
      "pages": [
        "https://trueshopstore.com/products/snug-fit-overnight-diapers"
      ]
    }
  ],
  "offer_fields": [
    {
      "k": "Incentive · Member Rewards",
      "v": "$16.84 member price, on all",
      "prov": "brand",
      "note": "Member price · no end date",
      "mechanic": "member_price",
      "source": "owned_incentive"
    },
    {
      "k": "Incentive · SNUG3",
      "v": "$3.00 off, code SNUG3, on Diapers, until 2026-12-31",
      "prov": "brand",
      "note": "Code · ends 2026-12-31",
      "mechanic": "code",
      "ends": "2026-12-31",
      "source": "owned_incentive"
    },
    {
      "k": "Last verified",
      "v": "2026-10-14",
      "prov": "parleo",
      "note": "the newest reference read or channel check of this product"
    }
  ],
  "history": [
    {
      "at": "2026-10-14T17:01:16+00:00",
      "event": "Page read for the study",
      "surface": "trueshopstore.com",
      "channel": null,
      "kind": "reference",
      "detail": "our own fetch, ok",
      "tone": "neu"
    },
    {
      "at": "2026-10-14T17:01:15+00:00",
      "event": "Page read for the study",
      "surface": "trueshopstore.com",
      "channel": null,
      "kind": "reference",
      "detail": "our own fetch, ok",
      "tone": "neu"
    },
    {
      "at": "2026-10-14T17:01:14+00:00",
      "event": "Page read for the study",
      "surface": "trueshopstore.com",
      "channel": null,
      "kind": "reference",
      "detail": "our own fetch, ok",
      "tone": "neu"
    },
    "… newest first"
  ],
  "surfaces": [
    {
      "channel": "schema_org",
      "name": "Schema.org Product/Offer",
      "s": "published",
      "d": "unverified",
      "n": null,
      "at": null,
      "acceptance": null,
      "published_at": "2026-08-21T20:16:23.305701Z",
      "note": null
    },
    {
      "channel": "merchant_center",
      "name": "Google Merchant Center feed",
      "s": "blocked",
      "d": "unverified",
      "n": null,
      "at": null,
      "acceptance": null,
      "published_at": null,
      "note": "not implemented in Step 2"
    },
    "… cut"
  ],
  "issue_groups": {
    "groups": [
      {
        "channel": "schema_org",
        "count": 5,
        "issues": [
          1,
          2,
          3,
          4,
          5
        ],
        "label": "Schema.org Product/Offer"
      },
      {
        "channel": "ucp_uip,acp,merchant_center",
        "count": 1,
        "issues": [
          0
        ],
        "label": "UCP / Universal Incentive Protocol, Agentic Commerce Protocol, Google Merchant Center feed"
      }
    ],
    "expanded": [
      3,
      0,
      1
    ],
    "total": 6
  }
}
```

### GET /api/console/catalog?merchant=wiggle-and-snug, the 2C-2 additions (one row)

```json
{
  "rows": [
    {
      "gtin": "884400896186",
      "variant_id": "bum-balm-4oz",
      "listing_id": 93,
      "product_name": "Bum Balm 4 oz",
      "brand_name": "Wiggle & Snug",
      "variant_label": "Bum Balm 4 oz",
      "size": "4 oz",
      "pack_count": 1,
      "multipack": null,
      "price": "12.99",
      "currency": "USD",
      "published_at": "2026-08-28T18:03:06.090934+00:00",
      "product_url": "https://trueshopstore.com/products/bum-balm-4-oz",
      "stage": "published",
      "stages": [
        "measured",
        "published"
      ],
      "quoted_runs": 2,
      "scored": 2,
      "exact": 1,
      "key": "bum-balm-4oz"
    }
  ],
  "retailers_read": [
    {
      "domain": "trueshopstore.com",
      "pages": 19,
      "read": 19,
      "method": "json ld 19",
      "hosted_render": 0,
      "last_read": "2026-10-14T17:01:19+00:00",
      "note": "19 of 19 pages read."
    }
  ],
  "stage_cycle": "WS-2B-FIXTURE",
  "read_errors": {}
}
```

### A swap check, scored before b3c5a29 (2C-2c, `build_answer`)

Size 1 small asked, the Trial Pack's $6.99 stated. The claim's own `outcome` is `exact` (it is the
Trial Pack's price); the question's is `question_outcome: wrong`.

```json
[
  {
    "claim": "$6.99 for Snug-Fit Trial Pack",
    "agent": "ChatGPT",
    "live": "$17.99",
    "verdict": "wrong",
    "note": "priced Snug-Fit Trial Pack instead",
    "reason": "variant_swap",
    "tone": "bad",
    "target": "swap"
  }
]
```

### GET /api/console/truesync?merchant=wiggle-and-snug, the 2C-2c timeline (one product, cut)

```json
{
  "products": [
    {
      "sku": "catalog_product:30",
      "name": "Bum Balm 4 oz",
      "listing_id": 93,
      "timeline": [
        {
          "at": "2026-08-21T20:15:00.801167Z",
          "event": "Published",
          "surface": "Deal directory / affiliate listing",
          "channel": "deal_directory",
          "kind": "publication",
          "status": "published",
          "tone": "ok"
        },
        {
          "at": "2026-08-21T20:15:00.627877Z",
          "event": "Published",
          "surface": "Model Context Protocol server",
          "channel": "mcp",
          "kind": "publication",
          "status": "published",
          "tone": "ok"
        },
        {
          "at": "2026-08-21T20:15:00.466754Z",
          "event": "Published",
          "surface": "Parleo Deals API",
          "channel": "deals_api",
          "kind": "publication",
          "status": "published",
          "tone": "ok"
        },
        {
          "at": "2026-08-21T20:15:00.041685Z",
          "event": "Published",
          "surface": "Schema.org Product/Offer",
          "channel": "schema_org",
          "kind": "publication",
          "status": "published",
          "tone": "ok"
        },
        "… newest first"
      ]
    }
  ]
}
```

### GET /api/console/answers/summary?cycle=WS-2B-FIXTURE, the 2C-2c `all_tiers`

```json
{
  "all_tiers": [
    {
      "surface": "grounded_api",
      "label": "API with search grounding",
      "runs": 7,
      "answered": 7
    },
    {
      "surface": "consumer_ui",
      "label": "Consumer UI, logged out",
      "runs": 1,
      "answered": 0
    }
  ]
}
```

## 2I: grounded surfaces only

Every path that starts answers (`POST /api/full-loop`, `POST /api/console/cycles`, and the web app's
`POST /api/cycles`) dispatches grounded surfaces only (`soa_shared/surfaces.py`, `grounded` on each
surface, classified from its runner's code). A name that resolves to an ungrounded surface is a 422
`{"code": "ungrounded_surface_not_allowed", "message": ...}`, and the message names what to send
instead. That includes the alias `gemini`, which is `gemini_api`, so the message says "use
gemini_grounded". A surface the worker reported it has no key for is a 422 `surface_not_configured`.

| surface id | runner | grounded | how we know |
|---|---|---|---|
| `chatgpt` | `OpenAIRunner` | yes | `openai_runner.py`: `tools=[{"type": "web_search"}]` on every request |
| `chatgpt_api` | `OpenAIApiRunner` | no | `openai_api_runner.py`: the same call with no `tools` |
| `gemini_grounded` | `GeminiGroundedRunner` | yes | `gemini_grounded_runner.py`: `tools=[types.Tool(google_search=types.GoogleSearch())]` |
| `gemini_api` (alias `gemini`) | `GeminiApiRunner` | no | `gemini_runner.py`: `GenerateContentConfig()` with no tools |
| `perplexity` | `PerplexityRunner` | yes | `perplexity_runner.py`: an online Sonar model (`…-sonar-…-online`), whose `citations` it reads |
| `claude` | `ClaudeRunner` | yes | `claude_runner.py`: `tools=[{"type": "web_search_20250305", "name": "web_search"}]` |
| `aimode` | `AiModeRunner` | yes | `serpapi_runner.py`: SerpApi `google_ai_mode`, Google's search answer, sources from `references` |
| `copilot` | `CopilotRunner` | yes | `serpapi_runner.py`: SerpApi `bing_copilot`, Bing's search answer, sources from `references` |
| `gemini_web`, `chatgpt_web` | none | no | no runner (`never_available`): nothing runs, so nothing is classified grounded |

The worker writes one row per runner at boot to `soa_worker_surfaces` (migration `d2f6b8a4c1e9`):
`{surface_id, configured, seen_at}`, booleans only, never a key. `GET /api/console/surfaces` serves each
surface with `fidelity_label`, `grounded`, `configured` and `seen_at` (`null` until the worker has
reported). A surface with no row is not refused. The run dialog checks every grounded surface with
`configured: true`. That is also the worker's fallback for a cycle stored with no platforms; before 2I
the fallback was a fixed `[chatgpt, gemini_grounded]`.

**2I-2: the dialog lists what the worker reports it can run.** `aimode` and `copilot` are listed from
the same report, never from the API's environment: `SOA_CONSUMER_SURFACES_ENABLED` and
`SERPAPI_API_KEY` are the worker's settings (the API never calls SerpApi), and no API code reads them.
Before 2I-2 the API hid a consumer surface unless its own process had both. Each row also carries
`worker_note`:

| worker's report for `aimode` | `configured` | `available` | `unavailable_reason` | `worker_note` | dispatch naming it |
|---|---|---|---|---|---|
| `true` | `true` | `true` | `null` | `null` | accepted |
| `false` | `false` | `false` | `"no key on the worker"` | `"no key on the worker"` | 422 `surface_not_configured` |
| no row | `null` | `true` | `null` | `"the worker has not reported yet"` | accepted (unchecked) |

An API surface reads the same way. Gemini web and ChatGPT web stay listed last, not available, with
their reason and no `worker_note`.


## 2I: what the run dialog compares against

`GET /api/console/runs` (the cycle picker) and `GET /api/console/full-loop/latest` also return
`surface_ids`, `runs_per_question` and `study_id` (so does `/api/full-loop/{id}`, one shape). The existing `surfaces` on `/runs` keeps its meaning,
the surface kinds, so the resolved ids get their own name. On `/runs` the ids are what ran
(`soa_runs.platform`, in registry order). A pre-2D cycle stored an alias and ran it under another id
(229 stored "gemini" and ran `gemini_grounded`). Before any run, the ids are what the cycle stored
resolved (`soa_cycles.surfaces`), else its platforms resolved today. On `/full-loop/latest` the ids are
the request's `platforms`, stored resolved since 2D. A reads-only request has `[]` and `study_id: null`.

## 2I-5: a study's first cycle

On production (Oct 16, 8:44 PM) Wiggle & Snug Brand's first full loop read its pages, then failed
with no cycle: "could not create the cycle: the study has no earlier cycle to take a comparison set
from". The coordinator took the set only from the study's latest cycle, so the full loop had never
been able to run a study's first cycle (FL3 and FL4 worked because the store's study had a September
cycle made in the web app). The console's Start cycle had a partial rule and otherwise answered 422
"create its first cycle in Command Center".

A first cycle needs nothing declared: the mention coder learns the brands the answers name (the
ranking, "who agents name first" and the agent columns come from coding, not from the set). The set
only decides which rivals are tracked as full rows and which are "also named but not tracked" (2G).
One rule now serves both callers, `soa_shared/comparison_sets.comparison_set_for_study` (identical in
the three `soa_shared` copies):

1. The study's latest cycle has entities: copied, by comparison code. No supply read.
2. Else the study's merchant, `tier_config.merchant.slug`, else `syndicated_merchant` (#120 sets one
   on every console study), is **M001, primary**: its `soa_entities` row by slug, created when missing
   from supply's `/tenant` record: `name` the merchant's name ("Wiggle & Snug Brand"), `slug` the
   merchant slug, `entity_type` `brand` for a brand merchant else `retailer`, `website_url`
   `https://<own domain>/`, `aliases` `[<own domain>]`.
3. The rivals are the merchant's `comparison_domains` from supply's
   `GET /merchants/{slug}/retailers` (2A-4), in its order, **M002 onward, competitor**: each the
   `soa_entities` row whose alias or `website_url` host is that domain, else a new row of the
   merchant's entity type. **A created rival is named by its domain** (`huggies.com`, slug
   `huggies-com`) until the soa wizard's competitor field (2I-6) supplies its name. An empty list: the
   primary alone.
4. No merchant (no job in the org, or a job naming none: a study generated before #120): no set, and
   the request fails "could not create the cycle: the study belongs to no merchant" (Start cycle: 422).

A supply read that fails on a first cycle fails the request with the read ("could not create the
cycle: could not read '<slug>''s retailers from TrueSync: …"; Start cycle: 502) rather than create a
guessed set every later cycle would copy. The coordinator reads with the org's tenant token
(`TrueSyncCatalogClient`), built only when a first cycle needs it; the API reads `/tenant` (the
switcher's read) and `/retailers` with the org's async client before the rule runs.


### 2I-5: why a loop failed

`GET /api/console/full-loop/latest` and `GET /api/full-loop/{id}` serve the request's `error` as the
coordinator wrote it, unchanged (the Oct 16 request keeps its pre-2I-5 wording). A failed request
also carries **`failed_step`**, `reads | cycle | study | scoring`, from what the request reached,
not from the error's words (`app/routers/full_loop.py` `failed_step`):

| `failed_step` | the request | the coordinator's failures |
|---|---|---|
| `reads` | no supply run, or supply's run not `reference_done` / `scored` | did not start, supply failed it, refused the read, `orphaned_by_restart`, timed out before the reads finished |
| `cycle` | reads finished, no cycle | `could not create the cycle: …` (no active questions, no merchant, a supply read for the set), timed out at `reference_done` |
| `study` | a cycle that did not complete | `cycle failed: …`, the cycle is gone, timed out while planned or running |
| `scoring` | the cycle completed | supply refused the PATCH (409 `conflict`, 401/403/404) |

A cycle decides first: a failed cycle PATCHes supply's run to `failed` as well, so supply's status
alone cannot tell the reads from the study. The key is only on a failed request: every other state
reads byte for byte as before (`tests/test_full_loop_2i.py`). The strip's three chip states are
unchanged; the console colours the chip `failed_step` names (`reads` the reads chip, `cycle` and
`study` the study chip, `scoring` the scoring chip).

## 2I-6: competitors to track, entered once

The brand's first cycle (FL7, Oct 17) tracked Wiggle & Snug alone, as 2I-5's rule makes a first cycle
when the merchant has no competitor list: the coder records the comparison set's brands, so Pampers
and Huggies were invisible on every consumer answer and "named but not tracked" was empty.
Competitors are now entered once per merchant, as name + domain: in the setup wizard's first step
("Competitors to track", beside the retailers) and on an existing customer in the Command Center
(the **Competitors** button: `CompetitorsPanel`, the same `CompetitorsSection`).

**One save, two writes, in order** (`PUT /api/customers/{org}/merchants/{slug}/competitors`):

1. supply: the merchant's `comparison_domains` through `PUT /api/truesync/merchants/{slug}/comparison-domains`
   (2A-4, `tenant_writer`; replaces the list, `[]` clears it). Supply refuses an own or retailer domain
   (409) and a malformed one (422); soa checks the same format first. A refusal leaves soa untouched.
2. soa: one `soa_entities` row per competitor (`comparison_sets.upsert_competitor`): the row whose
   alias or `website_url` host is the domain (its name kept, unless it is the domain itself, as 2I-5
   names a rival it creates: then it takes the name given), else a new row with the name given, slug
   from the name, `website_url` `https://<domain>/`, `aliases` `[<domain>]`. A failure here, after
   supply saved, says so (`entities_failed`); saving again finishes it.

Removing a competitor removes its domain from supply; its entity stays (entities are global).
`GET` on the same path reads supply's `/retailers` back and joins `comparison_domains` to entity
names: a domain with no entity reads **"no entity yet"**, so the two cannot drift silently.

**The comparison set** (`soa_shared/comparison_sets.py`): a first cycle is as 2I-5 (M001 the
merchant, M002 onward the list). A later cycle is now the previous cycle's set **plus** any listed
domain it does not hold yet, numbered on from its last code: rivals = previous rivals ∪ the current
list, in that order. **A domain removed from the list stays in later cycles' sets** until an operator
removes it from the cycle entities: a set only grows by itself, so cycles stay comparable. A later
cycle whose list cannot be read is copied as it was (the next one picks the addition up).

### 2I-6: no share-of-mentions score without a rival (console scorer 8)

Share of mentions counts our mentions over every tracked entity's, so a cycle whose comparison set
is the brand alone scores it 1 of 1 whenever the brand is named: FL7's grounded surface scored 54
with the brand named in 1 of 15 answers. On a cycle with no `competitor` in `soa_cycle_entities`
(`console_score.load_tracked_rivals`), the dimension is **not measured**,
`reason.no_rivals` ("no competitor is tracked on this cycle: add competitors in the wizard"; a colon,
since no template carries a semicolon); its points leave the applicable max and the verdict is
withheld, as for any unmeasured dimension (2C-3). Recommendation strength and the named counts do not
depend on the set. The console's `SCORER_VERSION` is **8**, its own: the full-cycle scorer it reuses
(`FULL_CYCLE_SCORER_VERSION`, Full Analysis) does not apply the rule and stays 7. The recompute line
names each version's change between the stored and the new score that applies to the new one
(`SCORER_CHANGES`, `SCORER_CHANGE_APPLIES`): "scorer 7 → 8: share of mentions not measured without a
tracked competitor", and "scorer 6 → 8: ungrounded surfaces excluded from pooling" for a v6 score.

Not measuring moves a score either way, by what the dimension was earning: FL7's (all 22 points, 1 of
1) leaves and the score drops; on cycle 229's runs with its three rivals removed (the brand never
named, 0 of 22) the score rises from 32 to 47 on 47 applicable points. 229 and FL4 as they ran track
rivals and score as before.

## 2I-7: category-control questions are unprompted (console scorer 9)

One rule decides which questions are unprompted, `soa_shared/unprompted.py` `is_unprompted(run_or_question, terms)`
(identical in `apps/api`, `apps/pipeline` and `packages/shared`), read by the score, the read models and the study
generator's category-control check:

- the question's tier is `category_control` or absent, **and**
- its text names none of the brand's terms, matched by `expected_answers.names_brand`: case-insensitive, whole
  words, `&` read as "and", punctuation flattened ("Wiggle & Snug", "wiggle and snug" and "WIGGLE & SNUG" all name
  it; a brand called "Bum" is not named by "album").

The terms (`unprompted.brand_terms`, loaded by `console_read_models.load_brand_terms` per cycle and
`study_brand_terms` per study) are the cycle's primary entity's `name` and `aliases`, and the brand's product
names from its catalog, which the generator stores on the job as `tier_config.merchant.product_names` (from 2I-7
on; a study generated before stores none, and its questions are checked against the name and aliases alone).

Why both halves. A study generated with the syndicated-brand box on tags its stage questions `category_control`;
one generated with it off leaves them untiered. They are the same questions, but the score counted only untiered
runs, so a box-on study (FL12, Pampers, Oct 19) found no unprompted answer and left Visibility not measured
(`reason.no_unprompted`, "32 of 100 points are not measured"), and the screens fell back to every answered
question. And a category-control question exists to ask with no brand named ("Best diapers for a newborn"); one
that names the brand put the brand in the answer and is not a share-of-mentions measurement. FL12 asked 13 of them
in its first 25.

Where it is read:

| Call site | Before | Now |
| --- | --- | --- |
| `console_score.visibility_inputs` (share of mentions, recommendation strength) | `not r.get('tier')` | `is_unprompted(r, terms)`; `named_the_brand` counts the runs of an unprompted tier left out |
| `console_score.metric_counts` (Overview tiles' "program named" over the unprompted runs) | `(tier or 'unprompted') == tier` | `is_unprompted(r, terms)` |
| `console_read_models.build_visibility` byQuestion | `tier` only | each row adds `unprompted` (the rule); `tier` stays the question's tier |
| `console_parity._tier_for_reads`, `visibility_headline` ("Named in N of M unprompted answers"), `surface_metrics` (Overview tiles "First recommendation / Share of answers … unprompted answers", the agent table's `named_of`), the Overview's `coverage.unprompted` | `row.tier == 'unprompted'` | `row.unprompted` |
| `console_read_models.prompt_counts` (studio study list) | branded = a branded tier | branded = a branded tier, or any other question naming the brand |
| `console_read_models.build_prompt` `branded` | names the study brand | names any of the terms |

The "every answered question" fallback stays for a cycle that asked no unprompted question at all. Visibility's
per-tier breakdown (`tiers`, `by_stage.stages_by_tier`) still groups by the question's tier.

The score's `SCORER_VERSION` is **9**: `SCORER_CHANGES['9']` "category-control questions count as unprompted",
applying (`SCORER_CHANGE_APPLIES`) when the new score's `unprompted` block shows a category-control question or one
left out for naming the brand. Every stored score reads stale and is recomputed on its next read: no re-run. The
body adds `unprompted: {questions, named_the_brand, category_control}` (distinct questions on the pooled surfaces).
When every unprompted-tier question on a surface names the brand, both Visibility dimensions are not measured with
`reason.all_named_the_brand`: "no unprompted question answered on this surface: every category-control question
names the brand ({n} answered), and a question that names it is not counted".

On cycle 229's runs with its 50 stage questions tagged `category_control` and 13 rewritten to name the brand
(FL12's shape, `tests/test_unprompted_2i7.py`): scorer 8 scored 60 on 37 applicable points with Visibility not
measured; scorer 9 measures it over the 37 unbranded questions' 222 grounded answers (share of mentions 0 of 26:
the brand is named in none of 229's answers) and scores 32 on 69. 229 as recorded (untiered, FL8's shape) scores
32 on 69 under both.

The generator keeps the brand out of category-control questions (`generation/syndicated_study.py`): see the module
docstring there and `tier_config.category_control` (`branded_dropped`, `branded_regenerated`, `line`).

## 2J-2: a brand's read models

### Products this week on a brand

FL12 (Pampers) showed no "Products this week" block although True Value had every variant with quotes.
A brand's True Value has its own site as the `you` column (`retailer_columns[].you`, `pampers.com`),
and no agent quotes it: the brand sets no price there, so its catalog questions name a retailer
(`expected_answer.attributed_to`). `build_products` read only the `you` cell when the row had one, so
every row was skipped and the Overview hid the block. The W&S store worked because its `you` column is
the store, which its questions ask about.

The rule now (`console_parity.build_products`): a row reads its `you` cell when that cell has quotes on
the surface, else the retailer cells together (`_product_across`):

| field | read across retailers |
|---|---|
| `quoted` | every quote, grouped by price, each naming the retailers it was quoted at, then the runs with no price: "Amazon and Walmart $27.97, 5 of 12 runs (Gemini 2, Google AI Mode 1, Perplexity 2). …" |
| `live` | each retailer's live price, as `_live_text` words it, in column order |
| `status`, `cell_status` | the worst cell's (wrong, partial, none, exact) |
| `issue`, `wrong_runs`, `runs`, `quote_groups`, `named`, `first` | over every quote |
| `retailer`, `quote`, `live_price`, `reference_source`, `observed_at` | the worst cell's |
| `read_across` (new) | `true` |
| `retailers` (new) | per retailer cell with quotes: `retailer`, `name`, `runs`, `quote`, `cell_status`, `live_price`, `reference_source`, `observed_at` |

A store's products are unchanged on every surface, `all` included (`tests/test_console_2j2.py` pins the
W&S fixtures to main's output, byte for byte). On the FL12-shaped brand fixture
(`tests/console_fixture_2j2.py`; its prices and names are the fixture's, not production's), Swaddlers NB
84 on `all`:

```json
{
  "name": "Swaddlers NB 84", "sku": "00037000863434", "named": 0, "first": 0,
  "quoted": "Amazon and Walmart $27.97, 5 of 12 runs (Gemini 2, Google AI Mode 1, Perplexity 2). Amazon and Walmart $24.97, 3 of 12 runs (ChatGPT 2, Google AI Mode 1). No price, 4 of 12 runs (Claude 2, Copilot 2)",
  "live": "$24.97 at walmart.com, our own fetch, Oct 19. $27.97 at amazon.com, our own fetch, Oct 19",
  "status": "wrong", "issue": "Quoted a wrong price in 3 of 12 runs.", "route": "true-value",
  "cell_status": "wrong", "quote": "$27.97", "retailer": "walmart.com", "runs": 12, "answered": 12,
  "issue_rule": "product.wrong", "wrong_runs": 3, "live_price": "$24.97", "read_across": true,
  "retailers": [
    {"retailer": "walmart.com", "name": "Walmart", "runs": 6, "quote": "$27.97", "cell_status": "wrong", "live_price": "$24.97"},
    {"retailer": "amazon.com", "name": "Amazon", "runs": 6, "quote": "$24.97", "cell_status": "wrong", "live_price": "$27.97"}
  ]
}
```

(`answer_ids`, `quote_groups` and the per-retailer `reference_source`/`observed_at` cut.)

### Catalog stages for a GTIN-less row

FL12's Catalog read "Not measured, 4 of 10" for its four feed rows with no GTIN (Ultra, Pure, AMORE,
Cruisers S5), and True Value showed them "not quoted" at every retailer, although the study asked about
them. **Case (a): the quotes exist and the joins missed them.** It is not a generator gap: the brand mode
(`catalog_tiers._build_catalog_from_reads`) asks about a GTIN-less variant at each retailer page read,
keyed by supply's variant key, `sku:<sku>` (`catalog_snapshot.merge_merchant_record` and `merge_reads`
key it the same way since 2I), and writes that key as the question's `source_ref.variant_id`. On the
FL12-shaped fixture the generator, run on the fixture's supply payloads, writes exactly the fixture's 20
questions, the four GTIN-less variants at Walmart and Amazon among them (`tests/test_console_2j2.py`).

The two joins that missed:

| where | before | now |
|---|---|---|
| `console_parity.catalog_stages` (Catalog's `stages`, `stage_ladder`) | a row's quotes under its `variant_id` else its GTIN-14. A feed row carries no `variant_id`, only `variant_key`, so a GTIN-less feed row was keyed by nothing | under the first of `catalog_row_keys`: `variant_id`, `variant_key` (the GTIN-14, or `sku:<sku>`), the GTIN-14, `sku:<sku>`. `key` is the first of them |
| `console_read_models.build_true_value` (a cycle with a cached reference) | the read's row keyed by its GTIN-14 else `variant_ref`, aliased by `variant_ref`, `variant_label` and the bare SKU. A GTIN-less read's `variant_ref` is `feed_sku:<n>`, so a question's `sku:<sku>` found no row and its quotes were dropped | also aliased by `sku:<sku>`: the quotes fill the row's retailer cells, and the Overview's products (above) include the row |

A row with a GTIN was found by its GTIN before and is unchanged. On the fixture every one of the 10 rows
is measured (`stage_ladder` not measured 0, measured 10); each GTIN-less row has 8 quotes, 5 of them exact.
