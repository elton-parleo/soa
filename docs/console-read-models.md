# Console read models (2B, 2C, 2C-1)

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
| `GET /api/console/programs?merchant=<slug>[&cycle=<code>]` | the merchant's owned incentives, with how the cycle's value answers did (2C) | `TrueValue.programs` |
| `GET /api/console/accessibility?merchant=<slug>` | supply's access payload | `Accessibility` |
| `GET /api/console/truesync?merchant=<slug>` | the TrueSync matrix, assembled from supply (2C) | `TrueSyncData` (products, channels, lastVerified) |
| `GET /api/console/catalog?merchant=<slug>`, `/catalog/versions`, `/catalog/template.{csv,xlsx}`, `POST /catalog/validate`, `POST /catalog/commit` | Setup › Catalog over supply's 1B feed loader; **operator only** (2C) | — (soa) |
| `GET /api/console/studies/options`, `POST /studies/preview`, `POST /studies/generate`, `POST /studies/{study_type}/regenerate`, `GET /studies/{study_type}/status`, `POST /api/console/cycles` | the Create Study modal and "start a cycle"; **operator only** (2C) | — (soa) |
| `GET /api/console/studies?cycle=<code>` | question x agent | `StudyRow[]` |
| `GET /api/console/accuracy?cycle=<code>` | per-surface accuracy, never pooled | — (soa) |
| `GET /api/console/visibility?cycle=<code>` | who the answers name and who they name first, per surface with a per-agent split, from the stored mention coding (2C-1) | `Ranking` / `RankRow`, and one `VisibilityRow` per run |
| `GET /api/console/record/list?merchant=<slug>` | the merchant's products for the record list, each with its status (2C-1) | — (the record list) |
| `GET /api/console/record?merchant=<slug>&product=<sku>` | one product's record, read-only: fields with provenance, page disagreements, issues, variants, the schema.org artifact (2C-1) | `Record_` |
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
| `programs` | `[]` here; the console reads them from `/api/console/programs` (2C, below) |

Extras on each cell: `outcome` (the raw soa outcome), `runs`, and (2C) `reference_source`
(`honest_fetch` or `hosted_render` from supply's reference row; `record` when the cycle was
scored against the record), `method` and `observed_at` (the read's time; the record's
publication time for `record`), so a reader can tell an honest fetch from a hosted render.

### Programs (2C)

`GET /api/console/programs?merchant=<slug>[&cycle=<code>]` proxies supply's
`GET /api/truesync/merchants/{slug}/incentives/owned` with the tenant token and maps each
incentive to `TrueValue.programs` (`name`, `terms`, `agentsRight`, `tone`). With `cycle`,
`agentsRight` is right / scored over that cycle's value & incentives answers about the
program (matched by code, else tier name; absent, unscoreable and unverifiable are outside
it); a program no question asked about reads `not asked this cycle`, never 0. Extras:
`mechanic, code, tier_name, valid_until, asked, scored, right`.

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
  anything is written; the comparison set is the study's last cycle's, else its brand as primary;
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
