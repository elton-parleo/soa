# SoA Remediation Playbook — v1

Version: 1.0-draft · 20 plays
Purpose: curated library backing the AC3 Actions feature. Each play is keyed to a
failure mode the finding detector can identify deterministically from cycle metrics.

## Schema

Each play carries:

- **ID** — stable key, referenced by `soa_recommendations`
- **Failure mode** — what the finding detector observed
- **Detection trigger** — the rule, expressed against AC3 metrics (entity × dimension × surface × persona/stage)
- **Dimension(s)** — which SoA dimension(s) the play moves
- **Owner** — brand / retailer / joint
- **Play** — the remediation
- **Mechanism** — why it works (client-facing rationale)
- **Effort** — Low / Medium / High
- **Expected impact** — qualitative, until cycle-over-cycle attribution data calibrates it
- **Evidence to attach** — what to deep-link from Response Explorer

---

## Pillar 1 — Visibility

### VIS-01 · Structured data completeness
- **Failure mode:** Entity absent from agent responses for in-category queries despite active distribution.
- **Detection trigger:** Presence rate < 30% for an entity across ≥2 surfaces on purchase-stage intents, while ≥1 competitor exceeds 70% on the same cells.
- **Dimension(s):** Presence
- **Owner:** Brand + retailer
- **Play:** Audit and complete schema.org Product markup (name, GTIN, brand, offers, aggregateRating) on brand-site and top-retailer PDPs; validate against Merchant Center / rich-results tooling.
- **Mechanism:** Agents ground shopping answers in structured product entities; malformed or missing markup makes the product unparseable even when the page ranks.
- **Effort:** Low
- **Expected impact:** Moderate presence lift on retrieval-grounded surfaces (Perplexity, Google AI Mode, Copilot); weaker on model-memory-heavy surfaces.
- **Evidence to attach:** Runs where the entity was absent but the PDP existed; competitor responses on identical queries.

### VIS-02 · Cited-source coverage
- **Failure mode:** Agent answers are grounded in third-party sources (forums, review sites, category publishers) where the entity has no meaningful presence.
- **Detection trigger:** ≥40% of responses on an intent cluster cite sources in which the entity appears in <10% of cited pages (requires citation extraction in the coding stage).
- **Dimension(s):** Presence, Prominence
- **Owner:** Brand
- **Play:** Map the top cited domains per intent from the cycle's citation data; invest in earned/owned presence there — expert reviews, community engagement, category-publisher inclusion. For Baby Care: parenting communities and pediatric-adjacent publishers dominate awareness-stage citations.
- **Mechanism:** Retrieval-based agents synthesize from what they cite. Being absent from the citation graph is invisibility regardless of PDP quality.
- **Effort:** High
- **Expected impact:** High on awareness/consideration stages; compounding over cycles as content indexes.
- **Evidence to attach:** Citation frequency table per surface; example responses citing sources that omit the entity.

### VIS-03 · Agent shopping-feed inclusion
- **Failure mode:** Entity missing from a surface's native shopping integration (product carousels, shopping units) while appearing in its prose answers, or vice versa.
- **Detection trigger:** Presence in structured shopping units = 0 on a surface where the retailer participates in that surface's merchant program.
- **Dimension(s):** Presence, Accessibility
- **Owner:** Retailer (with brand escalation)
- **Play:** Verify feed submission status, feed field completeness, and eligibility rules for the surface's merchant program; escalate exclusions through the retailer's integration owner.
- **Mechanism:** Shopping units are populated from feeds, not crawls. Feed gaps are binary invisibility in the highest-converting response format.
- **Effort:** Medium
- **Expected impact:** High and fast — feed fixes propagate in days, not indexing cycles.
- **Evidence to attach:** Side-by-side runs showing competitor products in shopping units on identical queries.

### VIS-04 · Entity disambiguation
- **Failure mode:** Agent conflates sub-lines within the brand's portfolio (e.g., attributes of one line ascribed to another, or lines treated as interchangeable).
- **Detection trigger:** Coding stage flags cross-entity attribute contamination in ≥15% of responses mentioning either entity.
- **Dimension(s):** Presence, Fidelity
- **Owner:** Brand
- **Play:** Enforce canonical, consistently distinct naming across PDPs, brand site, and feeds; give each sub-line differentiated attribute content (distinct use cases, distinct claims); avoid shared boilerplate copy across sub-line PDPs.
- **Mechanism:** Agents build entity representations from co-occurring text. Near-identical copy across sub-lines teaches the model they are the same product.
- **Effort:** Medium
- **Expected impact:** Moderate; also protects premium sub-lines from being price-anchored to value sub-lines.
- **Evidence to attach:** Responses showing conflation, with the contaminated attributes highlighted.

### VIS-05 · Funnel-stage content gap
- **Failure mode:** Entity present on purchase-intent queries but absent from awareness/educational queries in the same category.
- **Detection trigger:** Presence rate on Awareness-stage queries < 50% of the same entity's presence rate on Purchase-stage queries.
- **Dimension(s):** Presence (stage-sliced)
- **Owner:** Brand
- **Play:** Build educational content mapped to the awareness intents where the gap was measured (for Pampers: newborn prep, sizing guidance, sensitive-skin education), published on owned properties and the cited-source domains from VIS-02.
- **Mechanism:** Agents answer educational queries from educational content. Brands with only transactional content enter the consideration set late or never.
- **Effort:** Medium
- **Expected impact:** High on awareness stage; the entity enters the agent's consideration narrative before price comparison begins.
- **Evidence to attach:** Stage-by-stage presence chart; awareness responses where only competitors are named.

### VIS-06 · Persona coverage gap
- **Failure mode:** Entity surfaces for some personas but is invisible for others (e.g., strong for value-seeker, absent for sensitive-skin parent).
- **Detection trigger:** Presence rate variance across personas > 40 points for the same entity and stage.
- **Dimension(s):** Presence, Offer Relevance by Persona
- **Owner:** Brand
- **Play:** Add persona-relevant attributes and substantiated claims to PDP and structured data (hypoallergenic certifications, dermatologist endorsements, eco-materials); seed reviews and Q&A content addressing that persona's decision criteria.
- **Mechanism:** Agents match persona-framed queries to persona-relevant attributes. If the attribute isn't machine-legible, the product doesn't match the persona.
- **Effort:** Medium
- **Expected impact:** Moderate-to-high on the deficient persona cells; measurable within 1–2 cycles.
- **Evidence to attach:** Persona × presence heatmap; responses for the weak persona naming competitors' persona-matched claims.

### VIS-07 · Prominence deficit
- **Failure mode:** Entity consistently present but ranked below competitors in agent responses.
- **Detection trigger:** Presence ≥ 60% but mean rank position ≥ 2 positions behind category leader across ≥3 surfaces.
- **Dimension(s):** Prominence
- **Owner:** Brand
- **Play:** Close the social-proof gap the agent is weighting: review volume and recency programs on top retailers, third-party comparison content, category-authority content (guides, expert roundups) on cited domains.
- **Mechanism:** Rank within an agent answer correlates with strength and recency of corroborating signals — review mass, expert consensus, citation frequency — not just relevance.
- **Effort:** High
- **Expected impact:** Gradual; prominence is the slowest dimension to move. Set expectations at 2–3 cycles.
- **Evidence to attach:** Rank-position trend per surface; the corroborating sources agents cite for the leading competitor.

### VIS-08 · New-launch invisibility
- **Failure mode:** Recently launched SKU rarely or never surfaces, even on queries it is purpose-built for.
- **Detection trigger:** Entity flagged `launch` in Entity Registry with presence < 15% after two cycles post-launch.
- **Dimension(s):** Presence, Offer Freshness
- **Owner:** Brand
- **Play:** Launch-sequence checklist: structured data and retailer PDPs live before announcement; early-review program in week one; press and authoritative-publisher coverage to seed the citation graph; explicit linkage content connecting the new SKU to the established intent ("X, now with Y").
- **Mechanism:** New products have zero training-data footprint; they exist to agents only through fresh retrieval. Every retrievable signal must be in place at launch, not after.
- **Effort:** Medium
- **Expected impact:** High — launch visibility is the purest zero-baseline case; correct sequencing routinely takes presence from ~0 to competitive within 2–3 cycles.
- **Evidence to attach:** Launch SKU presence trend vs. incumbent SKUs on the same intents.

---

## Pillar 2 — Accessibility

### ACC-01 · Availability routing
- **Failure mode:** Agent recommends the entity but routes to out-of-stock listings or third-party marketplace sellers instead of the primary listing.
- **Detection trigger:** ≥20% of routed links resolve to OOS or non-first-party seller PDPs at scoring time.
- **Dimension(s):** Accessibility
- **Owner:** Joint (retailer buy-box hygiene, brand inventory allocation)
- **Play:** Audit buy-box ownership and inventory-feed freshness on affected retailers; ensure availability signals (`availability` in offer markup) are accurate and updated at feed cadence, not batch-weekly.
- **Mechanism:** Agents increasingly verify availability before recommending; stale availability data either kills the recommendation or routes the buyer somewhere the brand doesn't control price or presentation.
- **Effort:** Low
- **Expected impact:** High on accessibility score; also protects fidelity (third-party sellers often carry wrong content and prices).
- **Evidence to attach:** Routed-link audit table with resolution status per run.

### ACC-02 · Link integrity
- **Failure mode:** Agent surfaces broken, redirected, or non-canonical URLs for the entity.
- **Detection trigger:** ≥10% of surfaced URLs return non-200 or resolve to a different product.
- **Dimension(s):** Accessibility
- **Owner:** Retailer
- **Play:** Stabilize canonical PDP URLs; maintain permanent redirects through re-platforms and SKU migrations; deprecate legacy URLs with proper 301 chains rather than 404s.
- **Mechanism:** Agents cache and cite URLs with long memory. A retailer re-platform without redirect discipline erases accumulated agent-legibility.
- **Effort:** Low
- **Expected impact:** Moderate; prevents silent decay more than it lifts scores.
- **Evidence to attach:** Broken-link inventory from cycle runs.

### ACC-03 · D2C agent-legibility
- **Failure mode:** Agents route all purchase intent to marketplaces; the brand's owned channel never appears as a purchase destination.
- **Detection trigger:** D2C domain share of routed links < 5% while the domain is in the Entity Registry as an owned channel.
- **Dimension(s):** Accessibility, Net Price Accuracy (D2C-exclusive offers invisible)
- **Owner:** Brand
- **Play:** Bring the D2C channel to feed-parity with marketplaces: complete offer markup, merchant-program participation per surface, and adoption of emerging agentic checkout rails where available; expose D2C-exclusive offers (bundles, subscriptions) in machine-readable form.
- **Mechanism:** Agents route where they can verify price, availability, and increasingly transact. A D2C site that is content-rich but feed-poor loses routing to marketplaces by default.
- **Effort:** High
- **Expected impact:** Moderate initially; strategic — every routed D2C purchase carries margin and first-party data the marketplace route forfeits.
- **Evidence to attach:** Routing-share breakdown by destination domain.

### ACC-04 · Surface integration absence
- **Failure mode:** A retailer partner has no presence in a surface's shopping integration at all, capping every downstream score on that surface.
- **Detection trigger:** Zero structured shopping results for all of the retailer's SKUs on a surface where competitor retailers appear.
- **Dimension(s):** Accessibility, Presence
- **Owner:** Retailer
- **Play:** Retailer-level recommendation: evaluate and join the surface's merchant/agent program. For brand-side engagements, this becomes escalation ammunition — quantify the SoA ceiling the retailer's absence imposes on the brand's portfolio.
- **Mechanism:** Integration presence is a prerequisite, not an optimization. No feed, no shopping unit, no routing.
- **Effort:** High
- **Expected impact:** Unlocking; removes a structural cap rather than moving a dial.
- **Evidence to attach:** Cross-retailer surface-coverage matrix.

---

## Pillar 3 — True Value Delivery

### TVD-01 · Active-promo exposure
- **Failure mode:** Agent quotes list price while a SKU-level promotion is live.
- **Detection trigger:** Net Price Accuracy gap: agent-quoted price exceeds validated true price by >5% on runs where a SKU-level promo was active (per true-cost engine).
- **Dimension(s):** Net Price Accuracy
- **Owner:** Retailer
- **Play:** Expose sale price and validity window in offer markup (`price`, `priceValidUntil`) and merchant feeds; align promo start/end with feed refresh cadence so agents never see the pre-promo price during the promo window.
- **Mechanism:** Agents quote the most machine-legible price. If the promo lives only in on-page banners or checkout logic, the agent quotes list and the funded discount buys nothing at the recommendation moment.
- **Effort:** Low
- **Expected impact:** High and fast on Net Price Accuracy for the affected retailer-surface cells.
- **Evidence to attach:** Price-delta table: agent-quoted vs. validated true price per run, with active promo identified.

### TVD-02 · Basket-level incentive legibility
- **Failure mode:** Basket-threshold deals, BOGO, and gift-with-purchase never appear in agent responses; only SKU-level pricing flows through.
- **Detection trigger:** Offer Completeness: zero agent mentions of active basket-level mechanics across all runs for a retailer, while true-cost validation confirms they were live.
- **Dimension(s):** Offer Completeness, Net Price Accuracy, Competitive Value Position
- **Owner:** Joint — brand funds the incentive, retailer owns the rails
- **Play:** Two paths, presented as a decision: (a) expose basket-level mechanics through machine-readable deal rails (structured deal feeds, MCP-style connectors) so agents can compute conditional value; or (b) restructure trade funding toward SKU-level mechanics agents already parse. Path (a) preserves the incentive design; path (b) trades sophistication for guaranteed legibility.
- **Mechanism:** This is the structural gap: agent integrations parse per-SKU offer objects, and basket math requires deal logic no current integration evaluates from page content. Unexposed basket promos are trade spend that is invisible at the moment of recommendation.
- **Effort:** Medium (a) / Medium (b — requires trade-planning change, not engineering)
- **Expected impact:** High — typically the single largest recoverable gap in the True Value pillar for promo-heavy categories.
- **Evidence to attach:** Funded-vs-delivered value table: each active basket mechanic, its validated value, and its zero surfacing rate.

### TVD-03 · Loyalty and member value exposure
- **Failure mode:** Member pricing, points accrual, and tier benefits absent from agent responses even on surfaces where the retailer has an account-linked integration.
- **Detection trigger:** Offer Completeness: member-value mentions = 0 on account-linked surfaces where loyalty benefits were active for the test account.
- **Dimension(s):** Offer Completeness, Net Price Accuracy
- **Owner:** Retailer
- **Play:** Extend the account-linked integration payload to include member price and accrual value, not just identity; where no account linking exists, expose the loyalty-inclusive price tier as a labeled alternate offer in the feed.
- **Mechanism:** Account linking without value payload is authentication theater — the agent knows who the shopper is but not what that membership is worth on this SKU.
- **Effort:** Medium
- **Expected impact:** High for loyalty-heavy retailers; differentiating, since few integrations do this today.
- **Evidence to attach:** Account-linked runs where member value was live but unsurfaced.

### TVD-04 · Subscription value exposure
- **Failure mode:** Subscribe-and-save or replenishment pricing never surfaces; agent compares one-time prices only.
- **Detection trigger:** Zero subscription-price mentions for entities with active subscription offers, on ≥2 surfaces.
- **Dimension(s):** Net Price Accuracy, TCO Clarity
- **Owner:** Retailer + brand
- **Play:** Publish subscription price as a distinct machine-readable offer variant; on brand D2C, make replenishment pricing the structured default offer for consumable categories.
- **Mechanism:** For replenishable categories (diapers are the canonical case), the subscription price *is* the real price for the core buyer; agents comparing one-time prices misrank every brand with strong subscription economics.
- **Effort:** Low
- **Expected impact:** High for consumables; directly moves the price-promo expectation-vs-delivery gap.
- **Evidence to attach:** One-time vs. subscription price comparison per run.

### TVD-05 · Offer freshness
- **Failure mode:** Agent cites expired promotions or stale prices.
- **Detection trigger:** Offer Freshness: ≥10% of quoted offers were expired at run time per true-cost validation.
- **Dimension(s):** Offer Freshness, Net Price Accuracy
- **Owner:** Retailer
- **Play:** Add explicit validity metadata to every offer; increase feed refresh cadence to match promo cadence; retire promo landing pages on expiry rather than leaving them indexed.
- **Mechanism:** Stale offers cut both ways — a phantom discount creates a broken expectation at checkout (the exact expectation-vs-delivery gap), and it erodes agent trust signals for the domain.
- **Effort:** Low
- **Expected impact:** Moderate; primarily protects conversion integrity rather than lifting share.
- **Evidence to attach:** Expired-offer citations with expiry timestamps.

### TVD-06 · Unit-economics legibility
- **Failure mode:** Agent compares headline prices across different pack sizes; per-unit value never enters the comparison.
- **Detection trigger:** In comparison-intent runs, agent price comparisons omit per-unit normalization while compared SKUs differ in count/size by >25%.
- **Dimension(s):** Competitive Value Position, TCO Clarity
- **Owner:** Brand + retailer
- **Play:** Publish per-unit price in structured data (UnitPriceSpecification); normalize pack-size attributes in feeds; where the brand wins on per-unit economics, add comparison content that frames the category in per-unit terms.
- **Mechanism:** Larger-pack value plays lose to smaller headline prices when the agent lacks unit math inputs. Making the per-unit figure machine-legible lets the agent do the math that favors the value pack.
- **Effort:** Low
- **Expected impact:** Moderate-to-high for brands whose strategy is bulk value (again, diapers are the canonical case).
- **Evidence to attach:** Comparison runs where headline-price framing reversed the true per-unit ranking.

### TVD-07 · Competitive value misrepresentation
- **Failure mode:** Agent asserts a competitor is cheaper or better value when validated true cost shows otherwise.
- **Detection trigger:** Competitive Value Position: agent value-ranking contradicts true-cost ranking in ≥15% of comparison runs.
- **Dimension(s):** Competitive Value Position
- **Owner:** Brand
- **Play:** Composite play — this finding is usually downstream of TVD-01/02/04/06; bundle the applicable upstream fixes and add authoritative comparison content presenting the true-cost math. Re-measure before further action; do not treat as a standalone fixable.
- **Mechanism:** Agents don't misrank out of malice; they rank the legible subset of value. Fix legibility and the ranking follows.
- **Effort:** Rolls up constituent plays
- **Expected impact:** This is the headline metric clients care about; frame it as the outcome the pillar's other plays move.
- **Evidence to attach:** True-cost ranking vs. agent ranking, per comparison run.

### TVD-08 · Total-cost opacity
- **Failure mode:** Shipping costs, thresholds, and fees absent from agent price framing, distorting cross-retailer comparisons.
- **Detection trigger:** TCO Clarity: shipping/fee mentions = 0 in cross-retailer comparison runs where validated delivered costs differ by >8%.
- **Dimension(s):** TCO Clarity
- **Owner:** Retailer
- **Play:** Expose shipping cost and free-shipping thresholds in offer markup (shippingDetails); ensure fee structures are stated in machine-parseable form on PDP rather than revealed at checkout.
- **Mechanism:** A $2 item-price win that hides a $6 shipping loss is a value misrepresentation the agent propagates. Retailers with genuinely better delivered economics are subsidizing opaque competitors.
- **Effort:** Low
- **Expected impact:** Moderate; strongest for retailers whose delivered-cost position beats their item-price position.
- **Evidence to attach:** Delivered-cost comparison table vs. agent-quoted framing.

---

## Pillar 4 — Fidelity

*Positioning note: AC3 detects and prioritizes fidelity failures with evidence; catalog-remediation tooling is out of scope (complementary-specialist lane). Plays here specify the fix category and owner, not the tooling.*

### FID-01 · Attribute and claim errors
- **Failure mode:** Agent states incorrect specs, ingredients, sizes, or claims for the entity.
- **Detection trigger:** Coding stage flags factual contradictions between agent response and Entity Registry ground truth in ≥10% of runs mentioning the entity.
- **Dimension(s):** Fidelity
- **Owner:** Brand
- **Play:** Trace each error class to its source (retailer PDP, third-party content, stale brand site) using the citation data from the runs; correct at source; syndicate the corrected canonical content to all retailer PDPs.
- **Mechanism:** Agents propagate the most-corroborated version of a fact. Correcting the canonical source without syndication leaves the wrong version winning on corroboration count.
- **Effort:** Medium
- **Expected impact:** Moderate; critical for regulated or safety-adjacent claims where errors carry risk beyond SoA.
- **Evidence to attach:** Error inventory: claimed vs. actual, with the citing source per error.

### FID-02 · Stale product representation
- **Failure mode:** Agent describes discontinued formulations, old packaging, or superseded product generations.
- **Detection trigger:** Coding stage flags version-mismatch content in ≥10% of runs; entity has a `superseded_by` or revision record in the Entity Registry.
- **Dimension(s):** Fidelity, Offer Freshness
- **Owner:** Brand
- **Play:** Deprecation hygiene for the old version: redirect or clearly mark legacy PDPs and content as superseded; publish transition content explicitly linking old to new; refresh third-party content (reviews, guides) that anchors the stale version.
- **Mechanism:** The old product usually has years of accumulated corroboration; the new one has months. Without explicit supersession signals, agents rationally prefer the better-attested stale version.
- **Effort:** Medium
- **Expected impact:** Moderate; compounds with VIS-08 for launch scenarios.
- **Evidence to attach:** Stale-representation runs annotated against the current product record.

---

## Seeding notes

- Maps 1:1 to the proposed `soa_playbook` table: `play_id`, `pillar`, `failure_mode`, `detection_trigger`, `dimensions[]`, `owner`, `play_text`, `mechanism_text`, `effort`, `expected_impact_text`, `evidence_spec`.
- Detection thresholds above are starting values — tune per category after the first Pampers cycle; they should live in config, not code.
- TVD-07 is a composite: the mapper should suppress it as a standalone recommendation when its constituent plays (TVD-01/02/04/06) fire on the same cells, and present it as the outcome framing instead.
- Owner = "joint" plays should render with a split-responsibility layout in the Actions UI, since these become the brand-to-retailer escalation deliverable.
