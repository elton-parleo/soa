/**
 * The verification model — the executable form of
 * `docs/verification-semantics.md`.
 *
 * Read that document first. Where this file and the document disagree,
 * the document is right and this file is a bug.
 *
 * Everything here is pure: no DOM, no fetches, no React. Components
 * consume the output of `aggregateCell` and `summarize` and count
 * nothing themselves — the three bugs this model replaces all lived in
 * counting logic that had leaked into rendering.
 *
 * The one rule the whole model exists to enforce: a cell is described
 * by four orthogonal dimensions, and no dimension may contribute to
 * another's count.
 *
 *   1. publish state   what we did
 *   2. drift           our comparison        (number | null)
 *   3. acceptance      their opinion         (GMC only)
 *   4. observability   our own honesty       (unreadable count)
 *
 * Plus freshness, which cuts across all of them: a record older than
 * the cell's latest publish verified a superseded artifact and counts
 * for nothing.
 */

// ─── Methods ─────────────────────────────────────────────────────────

export const METHOD_FETCH_PROBE = 'fetch_probe'

// Per-channel copy for the Verify control. Presentation only — WHETHER a
// channel gets the control is decided by its verification_surface, never
// by membership of this object. A fetch_probe channel with no entry here
// still gets a button; it just gets the default wording.
export const VERIFY_LABELS = {
  schema_org: {
    label: 'Verify now',
    title: "Fetch this listing's live PDP and record what it served",
  },
  acp: {
    label: 'Verify feed',
    title: 'Fetch the ACP feed from its serving URL and compare it to the '
      + 'published artifact',
  },
}

export const DEFAULT_VERIFY_LABEL = {
  label: 'Verify now',
  title: 'Fetch this channel\'s surface and compare it to what we published',
}

export function verifyLabelFor(channelSlug) {
  return VERIFY_LABELS[channelSlug] || DEFAULT_VERIFY_LABEL
}
export const METHOD_GMC_DIAGNOSTICS = 'gmc_diagnostics'

// §2b. A surface-vs-surface observation of a brand we cannot publish
// for. Deliberately its own method: dimension 2 is defined as the
// findings of the newest fresh parseable `fetch_probe`, and a prospect
// record carrying that name would become eligible to answer a question
// about one of our own listings. It contributes to NO cell dimension.
export const METHOD_PROSPECT_FETCH = 'prospect_fetch'

// Google's review verdict on a PROMOTION, which is a different artifact from
// the listing this cell is about. It has its own lifecycle (days IN_REVIEW,
// not minutes), its own notion of success (LIVE, not "no blocking item
// issues"), and its own section in the drawer. Recognised here for the same
// reason `prospect_fetch` is: an unclassified method falls into 'unreadable'
// and inflates dimension 4, reporting a gap in this page's observability
// where there is none — the record simply answers a different question.
export const METHOD_GMC_PROMOTION_REVIEW = 'gmc_promotion_review'

// `live_fetch` is the older spec's name for the same thing. Accepted so
// a rename on either side cannot silently route records to the wrong
// parser.
const FETCH_PROBE_METHODS = new Set([METHOD_FETCH_PROBE, 'live_fetch'])

// Outcomes that mean the probe never produced a comparison. Anything
// else is judged on whether the record carries a comparison result —
// see classifyProbe.
const PROBE_FAILURE_OUTCOMES = new Set([
  'fetch_failed', 'failed', 'error', 'timeout', 'publish_failed', 'skipped', 'not_found',
])

// ─── Publish state (dimension 1) ─────────────────────────────────────

export const PUBLISH_STATE = {
  PUBLISHED: 'published',
  COMPILED_NOT_PUBLISHED: 'compiled_not_published',
  FAILED: 'failed',
  NEVER: 'never',
}

export const PUBLISH_STATE_LABEL = {
  published: 'Published',
  compiled_not_published: 'Compiled, not published',
  failed: 'Publish failed',
  never: 'Never published',
}

const PUBLISH_STATE_BY_STATUS = {
  published: PUBLISH_STATE.PUBLISHED,
  failed: PUBLISH_STATE.FAILED,
  compiled: PUBLISH_STATE.COMPILED_NOT_PUBLISHED,
  validated: PUBLISH_STATE.COMPILED_NOT_PUBLISHED,
  compiled_not_published: PUBLISH_STATE.COMPILED_NOT_PUBLISHED,
  withdrawn: PUBLISH_STATE.COMPILED_NOT_PUBLISHED,
}

export function publishStateOf(publication) {
  if (!publication) {
    return { state: PUBLISH_STATE.NEVER, reason: null }
  }
  const state = PUBLISH_STATE_BY_STATUS[publication.status] || PUBLISH_STATE.COMPILED_NOT_PUBLISHED
  const reason = publication.status === 'withdrawn'
    ? 'withdrawn'
    : (publication.error || validationReason(publication.validation) || null)
  return { state, reason }
}

function validationReason(validation) {
  if (!validation || validation.ok !== false) return null
  const errors = Array.isArray(validation.errors) ? validation.errors : []
  return errors.length > 0 ? errors.join('; ') : null
}

// ─── Extension status (metadata, not a measurement) ──────────────────

// Whether a channel's extension facet can honestly carry its data, and why
// not when it cannot. Declared per channel by the API; see
// docs/verification-semantics.md, "Extension status".
//
// The four values lead to different next actions, which is the whole point of
// keeping them apart:
//   deferred          -> WE are the reason. Do the work.
//   insufficient_spec -> the MATERIAL is the reason. Get better material.
//   not_applicable    -> the ARTIFACT CLASS is the reason. Neither more
//                        effort nor a better spec would change it.
//
// `not_applicable` renders NEUTRALLY. Nothing is wrong when it is set, and
// colouring it amber would turn a correct, settled statement into a standing
// alarm nobody can clear.
export const EXTENSION_STATUS = {
  POPULATED: 'populated',
  DEFERRED: 'deferred',
  INSUFFICIENT_SPEC: 'insufficient_spec',
  NOT_APPLICABLE: 'not_applicable',
}

export const EXTENSION_STATUS_LABEL = {
  populated: 'Extension populated',
  deferred: 'Extension deferred',
  insufficient_spec: 'Extension: spec material insufficient',
  not_applicable: 'Extension not applicable to this artifact',
}

// Tone, deliberately, in the tick vocabulary this panel already uses.
// insufficient_spec is the only one that is a problem to chase; deferred is
// outstanding work; not_applicable is a settled fact and gets no colour at
// all; populated is good news.
export const EXTENSION_STATUS_TONE = {
  populated: 'ok',
  deferred: 'warn',
  insufficient_spec: 'bad',
  not_applicable: 'neutral',
}

export function extensionStatusOf(channel) {
  const status = channel?.extension_status
  if (typeof status !== 'string' || !status) return null
  return {
    status,
    label: EXTENSION_STATUS_LABEL[status] || `Extension: ${status}`,
    tone: EXTENSION_STATUS_TONE[status] || 'warn',
    // Required for every value but `populated`, so its absence is worth
    // showing rather than hiding behind an empty span.
    reason: channel.extension_status_reason || null,
  }
}

// ─── Verification surface (which dimensions apply at all) ────────────

// What independent surface exists to check a channel against. The API
// declares this per channel (`verification_surface` on /channels); this
// module never decides it from a list of its own, so a channel that
// gains a probe changes one declaration upstream and the classifier,
// the legend, the header counts and the Verify buttons all follow.
//
// See docs/verification-semantics.md, "Verification surface".
export const SURFACE = {
  FETCH_PROBE: 'fetch_probe',   // we can fetch it and compare
  ACCEPTANCE: 'acceptance',     // no surface of ours; a third party judges
  NONE: 'none',                 // nothing to fetch, nobody to ask
}

// Unknown defaults to NONE, never to a probe. A channel nobody has
// declared must not acquire a Verify button by accident.
export function surfaceOf(channel) {
  if (typeof channel === 'string') return channel || SURFACE.NONE
  const declared = channel?.verification_surface
  return typeof declared === 'string' && declared ? declared : SURFACE.NONE
}

// Dimension 2 applies only where something can be fetched and compared.
export function driftApplies(verificationSurface) {
  return surfaceOf(verificationSurface) === SURFACE.FETCH_PROBE
}

// Dimension 3 applies where a third party renders a verdict.
export function hasAcceptanceAuthority(verificationSurface) {
  return surfaceOf(verificationSurface) === SURFACE.ACCEPTANCE
}

// Whether to offer a Verify control for this channel.
export function canVerify(verificationSurface) {
  return driftApplies(verificationSurface)
}

export const NO_SURFACE_TOOLTIP =
  'no independent verification surface for this channel yet'

export const ACCEPTANCE = {
  APPROVED: 'approved',
  PENDING: 'pending',
  DISAPPROVED: 'disapproved',
  NOT_FOUND: 'not_found',
  UNAVAILABLE: 'unavailable',
  UNKNOWN: 'unknown',
}

export const ACCEPTANCE_LABEL = {
  approved: 'Approved',
  pending: 'Pending review',
  disapproved: 'Not approved',
  not_found: 'Not in feed',
  unavailable: 'No opinion available',
  unknown: 'No acceptance record',
}

// Amber for the lifecycle states, red only for a genuine rejection.
export const ACCEPTANCE_TONE = {
  approved: 'sync',
  pending: 'drift',
  disapproved: 'fail',
  not_found: 'hold',
  unavailable: 'hold',
  unknown: 'hold',
}

// ─── Lifecycle codes ─────────────────────────────────────────────────

/**
 * Google reports `pending_initial_policy_review_free_listings` with
 * `severity: "DISAPPROVED"`. It is not a disapproval — it is the first
 * step of publish -> pending -> approved. A lifecycle-shaped code
 * renders amber regardless of what the severity field says.
 *
 * Anything unrecognised is treated as a genuine rejection: failing to
 * surface a real disapproval is worse than over-reporting one.
 */
const LIFECYCLE_CODE_PATTERNS = [
  /^pending_initial_policy_review/i,
  /^image_link_pending_crawl$/i,
  /(^|_)pending(_|$)/i,
  /_crawl(_|$)/i,
  /_processing(_|$)/i,
]

export function isLifecycleCode(code) {
  const value = String(code || '')
  if (!value) return false
  return LIFECYCLE_CODE_PATTERNS.some((pattern) => pattern.test(value))
}

export function normaliseIssue(issue) {
  const raw = typeof issue === 'string' ? { code: issue } : (issue && typeof issue === 'object' ? issue : {})
  const code = raw.code ?? raw.issueCode ?? raw.id ?? raw.title ?? (typeof issue === 'string' ? issue : null)
  const lifecycle = isLifecycleCode(code)

  return {
    code: code == null ? null : String(code),
    description: raw.description ?? raw.title ?? raw.shortDescription ?? null,
    detail: raw.detail ?? raw.detailedDescription ?? raw.documentation ?? null,
    // What Google said, preserved verbatim so the drawer can show that
    // we deliberately disagreed with it.
    reportedSeverity: raw.severity == null ? null : String(raw.severity),
    lifecycle,
    // What we render. Lifecycle always wins over reportedSeverity.
    tone: lifecycle ? 'pending' : 'error',
  }
}

// ─── Freshness (cross-cutting) ───────────────────────────────────────

/**
 * A record is stale when it verified an artifact we have since
 * replaced. Stale records count for nothing, anywhere.
 *
 * Decided once, in the doc:
 *   - missing created_at    -> STALE (we cannot show it is current, and
 *                              withholding a tick is the safe direction)
 *   - no published_at       -> fresh (nothing supersedes anything)
 *   - equal timestamps      -> fresh (strictly "predates")
 *
 * Missing created_at wins over missing published_at.
 */
export function isFresh(createdAt, latestPublishedAt) {
  if (!createdAt) return false
  if (!latestPublishedAt) return true
  return String(createdAt) >= String(latestPublishedAt)
}

export const STALE_NOTE = 'pre-dates latest publish — re-verify'

// ─── classifyRecord ──────────────────────────────────────────────────

/**
 * One verification record -> exactly one of three kinds, plus whether
 * it is fresh.
 *
 *   { kind: 'probe',      fresh, method, createdAt, findings, ... }
 *   { kind: 'acceptance', fresh, method, createdAt, state, issues, ... }
 *   { kind: 'unreadable', fresh, method, createdAt, reason }
 *
 * `unreadable` is a first-class outcome, never a fallback dressed up as
 * a finding. A probe that could not run is unreadable, not a probe that
 * found nothing.
 */
export function classifyRecord(record, latestPublishedAt = null) {
  const createdAt = record && typeof record === 'object' ? (record.created_at ?? null) : null
  const fresh = isFresh(createdAt, latestPublishedAt)
  const method = record && typeof record.method === 'string' ? record.method : null
  const base = { fresh, method, createdAt, record }

  if (!record || typeof record !== 'object') {
    return { ...base, kind: 'unreadable', reason: 'record is not an object' }
  }

  // Prospect observations are recognised so they can be excluded
  // explicitly rather than falling into 'unreadable' and inflating
  // dimension 4 — they are not a gap in this page, they simply answer a
  // different question. See docs/verification-semantics.md §2b.
  if (method === METHOD_PROSPECT_FETCH) {
    return { ...base, kind: 'prospect', reason: 'prospect observation — not a cell dimension' }
  }

  if (method === METHOD_GMC_PROMOTION_REVIEW) {
    return { ...base, kind: 'promotion', reason: 'promotion review — not a listing dimension' }
  }

  if (method === METHOD_GMC_DIAGNOSTICS) return classifyAcceptance(record, base)
  if (FETCH_PROBE_METHODS.has(method)) return classifyProbe(record, base)

  return {
    ...base,
    kind: 'unreadable',
    reason: method ? `no parser for method "${method}"` : 'record carries no method',
  }
}

function classifyProbe(record, base) {
  const drift = record.drift
  const findings = parseFindings(drift)

  if (findings === null) {
    return { ...base, kind: 'unreadable', reason: 'probe payload is not field-level drift' }
  }

  const outcome = pick(drift?.outcome, record.outcome)
  const error = drift && typeof drift === 'object' ? (drift.error ?? null) : null

  // A probe that did not complete measured nothing. Its zero findings
  // are an absence, not a result — dimension 4, never dimension 2.
  //
  // Deliberately NOT "anything that is not 'ok'": a probe that
  // completed and found drift may well report `outcome: "drift"`, and
  // treating every unfamiliar outcome as a failure would discard real
  // findings. The rule is:
  //
  //   error set                  -> failed
  //   outcome in KNOWN_FAILURES  -> failed
  //   outcome 'ok' or absent     -> succeeded (absent = legacy record)
  //   outcome unrecognised       -> succeeded ONLY if the record also
  //                                 carries evidence of a comparison
  //                                 (findings, or an integrity verdict)
  //
  // The last clause keeps the doc's principle intact: an unfamiliar
  // outcome with nothing to show for it is an absence, not a pass.
  if (error != null && error !== '') {
    return { ...base, kind: 'unreadable', reason: String(error), probeFailed: true }
  }
  if (outcome != null && PROBE_FAILURE_OUTCOMES.has(String(outcome).toLowerCase())) {
    return { ...base, kind: 'unreadable', reason: `probe outcome: ${outcome}`, probeFailed: true }
  }
  const knownGood = outcome == null || String(outcome).toLowerCase() === 'ok'
  const hasComparison = findings.length > 0 || typeof drift?.integrity === 'boolean'
  if (!knownGood && !hasComparison) {
    return {
      ...base,
      kind: 'unreadable',
      reason: `unrecognised probe outcome "${outcome}" with no comparison result`,
      probeFailed: true,
    }
  }

  return {
    ...base,
    kind: 'probe',
    findings,
    outcome: outcome ?? null,
    integrity: typeof drift?.integrity === 'boolean' ? drift.integrity : null,
    bytesIdentical: typeof drift?.bytes_identical === 'boolean' ? drift.bytes_identical : null,
    url: typeof drift?.url === 'string' ? drift.url : null,
  }
}

function classifyAcceptance(record, base) {
  const drift = record.drift
  if (!drift || typeof drift !== 'object' || Array.isArray(drift)) {
    return { ...base, kind: 'unreadable', reason: 'acceptance record has no readable payload' }
  }
  if (!('approved' in drift) && !('issues' in drift)) {
    return { ...base, kind: 'unreadable', reason: 'acceptance record has no approved/issues payload' }
  }

  const issues = (Array.isArray(drift.issues) ? drift.issues : []).map(normaliseIssue)
  const httpStatus = typeof drift.httpStatus === 'number' ? drift.httpStatus : null
  const outcome = pick(drift.outcome, record.outcome)
  const reason = drift.reason ?? null

  return {
    ...base,
    kind: 'acceptance',
    state: acceptanceState({ approved: drift.approved === true, issues, httpStatus, outcome, reason }),
    issues,
    httpStatus,
    reason,
    outcome: outcome ?? null,
  }
}

function acceptanceState({ approved, issues, httpStatus, outcome, reason }) {
  if (approved) return ACCEPTANCE.APPROVED

  // No opinion could be obtained, and the record says why. Not a
  // verdict, and not our bug either — so it counts nowhere.
  if (outcome === 'publish_failed' || (reason && outcome && outcome !== 'ok')) {
    return ACCEPTANCE.UNAVAILABLE
  }

  // The ghost: Merchant Center has never heard of this item.
  if (httpStatus === 404) return ACCEPTANCE.NOT_FOUND

  if (issues.length > 0) {
    return issues.every((issue) => issue.lifecycle)
      ? ACCEPTANCE.PENDING
      : ACCEPTANCE.DISAPPROVED
  }

  // Not approved, nothing itemised, no 404, no stated reason. Treated
  // as a genuine rejection per the doc's "when in doubt" rule — the
  // drawer says plainly that no reason was given.
  return ACCEPTANCE.DISAPPROVED
}

/**
 * Field-level findings from a probe payload, or **null** when the
 * payload is not field-level drift at all.
 *
 * The null return is load-bearing: "I cannot read this" and "I read it
 * and found nothing" must not be the same value. Collapsing them is
 * what counted parse failures as catalog drift.
 */
export function parseFindings(drift) {
  if (drift == null) return []
  if (typeof drift !== 'object' || Array.isArray(drift)) return null

  if (Array.isArray(drift.findings)) {
    return drift.findings.map((f) => ({
      variant: f?.variant ?? f?.sku ?? f?.variant_id ?? null,
      field: f?.field ?? f?.name ?? '—',
      expected: f?.expected ?? f?.master ?? null,
      observed: f?.observed ?? f?.surface ?? f?.actual ?? null,
    }))
  }

  const entries = Object.entries(drift)
  if (entries.length === 0) return []

  const structured = entries.filter(
    ([, v]) => v && typeof v === 'object' && !Array.isArray(v) && ('expected' in v || 'observed' in v),
  )
  if (structured.length === 0) return null

  return structured.map(([field, v]) => ({
    variant: v.variant ?? v.sku ?? null,
    field,
    expected: v.expected ?? null,
    observed: v.observed ?? v.actual ?? null,
  }))
}

function pick(...values) {
  for (const value of values) if (value != null) return value
  return null
}

// ─── aggregateCell ───────────────────────────────────────────────────

/**
 * One cell's publication row + its verification records -> the four
 * dimensions, each computed from its own inputs and nothing else.
 *
 * Each dimension reads the newest **fresh** record of its own kind —
 * not the newest record overall. A cell can hold both a probe history
 * and an acceptance history, and neither speaks for the other.
 */
export function aggregateCell(
  publication,
  records = [],
  { channelSlug = null, verificationSurface = SURFACE.NONE } = {},
) {
  const { state: publishState, reason: publishReason } = publishStateOf(publication)
  const latestPublishedAt = publication?.published_at || null

  const classified = (records || [])
    .map((record) => classifyRecord(record, latestPublishedAt))
    .sort(byCreatedAtDesc)

  const fresh = classified.filter((c) => c.fresh)
  const stale = classified.filter((c) => !c.fresh)

  // Dimension 2 — drift. Applies ONLY where something can be fetched and
  // compared. On an acceptance or none channel it does not apply at all,
  // which is a different statement from "null" (not yet verified): null is
  // a prompt to press Verify, and on a channel with no probe that prompt
  // could never be answered.
  const applies = driftApplies(verificationSurface)
  const probe = applies ? (fresh.find((c) => c.kind === 'probe') || null) : null
  const drift = applies ? (probe ? probe.findings.length : null) : null

  // Dimension 3 — acceptance. Only where somebody has the authority to
  // have an opinion.
  const acceptanceRecord = hasAcceptanceAuthority(verificationSurface)
    ? (fresh.find((c) => c.kind === 'acceptance') || null)
    : null
  const acceptance = acceptanceRecord ? acceptanceRecord.state : ACCEPTANCE.UNKNOWN
  const issues = acceptanceRecord ? acceptanceRecord.issues : []

  // Dimension 4 — observability. Fresh unreadable records only: a stale
  // unreadable record is excluded by freshness like everything else.
  // 'prospect' is deliberately absent from every dimension above and
  // from this one — see §2b.
  const unreadable = fresh.filter((c) => c.kind === 'unreadable')
  const prospectRecords = classified.filter((c) => c.kind === 'prospect')
  const promotionRecords = classified.filter((c) => c.kind === 'promotion')

  return {
    channelSlug,
    publishState,
    publishReason,
    publishedAt: latestPublishedAt,
    compiledAt: publication?.compiled_at || null,
    externalRef: publication?.external_ref || null,
    specVersion: publication?.spec_version || null,
    expressiveness: Array.isArray(publication?.expressiveness) ? publication.expressiveness : [],
    validation: publication?.validation || null,
    payload: publication?.payload ?? null,

    drift,
    driftRecord: probe,

    acceptance,
    acceptanceRecord,
    issues,
    issueCount: issues.length,
    hasAcceptanceAuthority: hasAcceptanceAuthority(verificationSurface),

    verificationSurface: surfaceOf(verificationSurface),
    driftApplies: applies,

    unreadableCount: unreadable.length,
    unreadableRecords: unreadable,

    staleCount: stale.length,
    staleRecords: stale,

    // Surfaced so a stray prospect row on a cell is visible rather than
    // silently dropped, but counted in no dimension.
    prospectRecordCount: prospectRecords.length,

    // The promotion reviews on this cell, in no dimension either. The drawer's
    // Promotions section reads them; the listing's four dimensions do not.
    promotionRecords: promotionRecords.map((c) => c.record),
    promotionRecordCount: promotionRecords.length,

    records: classified,
    lastVerifiedAt: fresh.length > 0 ? fresh[0].createdAt : null,
    badge: driftBadge(drift, applies),
  }
}

function byCreatedAtDesc(a, b) {
  return String(b.createdAt || '').localeCompare(String(a.createdAt || ''))
}

// ─── Badge ───────────────────────────────────────────────────────────

export const DRIFT_GLYPH = {
  unknown: '○',
  clean: '✓',
  drift: '⚠',
  // A channel with no probe surface. Muted, and deliberately not ○: ○ means
  // "a probe could run and none has", which is a prompt. This is "there is
  // nothing here to run", which is not.
  not_applicable: '–',
}

export const DRIFT_LABEL = {
  unknown: 'Not yet verified',
  clean: 'Verified — no drift',
  drift: 'Drift found',
}

/**
 * The cell's primary badge, from drift and drift alone. Acceptance and
 * observability get their own markers; merging them into this one is
 * the mistake the whole model is here to prevent.
 */
export function driftBadge(drift, applies = true) {
  if (!applies) {
    return {
      kind: 'not_applicable',
      glyph: DRIFT_GLYPH.not_applicable,
      label: NO_SURFACE_TOOLTIP,
      count: null,
    }
  }
  if (drift == null) return { kind: 'unknown', glyph: DRIFT_GLYPH.unknown, label: DRIFT_LABEL.unknown, count: null }
  if (drift === 0) return { kind: 'clean', glyph: DRIFT_GLYPH.clean, label: DRIFT_LABEL.clean, count: 0 }
  return { kind: 'drift', glyph: DRIFT_GLYPH.drift, label: DRIFT_LABEL.drift, count: drift }
}

// ─── summarize ───────────────────────────────────────────────────────

/**
 * Header counts. The only place counting happens; components render
 * these numbers and compute none of them.
 */
export function summarize(cells = []) {
  const totals = {
    totalCells: 0,
    publishedCells: 0,
    verifiedCells: 0,
    driftingCells: 0,
    driftFindings: 0,
    issueCount: 0,
    cellsWithIssues: 0,
    pendingCells: 0,
    disapprovedCells: 0,
    notFoundCells: 0,
    unreadableCount: 0,
    staleCount: 0,
    // Cells where dimension 2 does not apply at all — acceptance and none
    // channels alike. Distinct from `null` drift, which means a probe
    // could have run and has not.
    driftNotApplicableCells: 0,
    lastVerifiedAt: null,
  }

  for (const cell of cells) {
    if (!cell) continue
    totals.totalCells += 1
    if (cell.publishState === PUBLISH_STATE.PUBLISHED) totals.publishedCells += 1

    // Dimension 2 only, and only on channels where it applies — a cell with
    // no probe surface is neither verified nor drifting, it is out of scope
    // for the question.
    if (cell.driftApplies === false) {
      totals.driftNotApplicableCells += 1
    } else if (cell.drift === 0) totals.verifiedCells += 1
    if (cell.driftApplies !== false && typeof cell.drift === 'number' && cell.drift > 0) {
      totals.driftingCells += 1
      totals.driftFindings += cell.drift
    }

    // Dimension 3 only.
    if (cell.acceptance === ACCEPTANCE.PENDING) totals.pendingCells += 1
    if (cell.acceptance === ACCEPTANCE.DISAPPROVED) totals.disapprovedCells += 1
    if (cell.acceptance === ACCEPTANCE.NOT_FOUND) totals.notFoundCells += 1
    if (cell.acceptance === ACCEPTANCE.PENDING || cell.acceptance === ACCEPTANCE.DISAPPROVED) {
      totals.issueCount += cell.issueCount
      if (cell.issueCount > 0) totals.cellsWithIssues += 1
    }

    // Dimension 4 only.
    totals.unreadableCount += cell.unreadableCount
    totals.staleCount += cell.staleCount

    if (cell.lastVerifiedAt && (!totals.lastVerifiedAt || cell.lastVerifiedAt > totals.lastVerifiedAt)) {
      totals.lastVerifiedAt = cell.lastVerifiedAt
    }
  }

  return totals
}

// ─── §2b. Prospect drift — surface versus surface ────────────────────
//
// A prospect is a brand we have no authorization to publish for. There
// is no master record, so "drift" here means how far several surfaces
// disagree with EACH OTHER, and no side is treated as right.
//
// This lives in the same module as the cell model, and deliberately not
// in a parallel one: the freshness and readability rules are the same
// rules, and the reason this file exists is that the same rule written
// twice becomes two rules.

export const SURFACE_OUTCOME = {
  OK: 'ok',
  NO_STRUCTURED_DATA: 'no_structured_data',
  BLOCKED_FOR_AGENTS: 'blocked_for_agents',
  ROBOTS_DISALLOWED: 'robots_disallowed',
  PARSE_FAILED: 'parse_failed',
  FETCH_FAILED: 'fetch_failed',
}

// The canonical doc names the readable outcome `fetched`; the live API
// emits `ok`. Both are accepted so a rename on either side cannot turn
// a readable surface into an unknown one. Reported as a mismatch.
const READABLE_OUTCOMES = new Set([SURFACE_OUTCOME.OK, 'fetched'])

/**
 * Blocked ≠ absent ≠ disallowed-by-policy. Three different facts about
 * three different parties, and the whole point of this vocabulary is
 * that they never collapse into one grey badge:
 *
 *   no_structured_data  their markup     — a real page carrying no JSON-LD
 *   blocked_for_agents  their edge       — up, and declined to serve us
 *   robots_disallowed   their policy     — a published rule we obeyed
 *   parse_failed        their data       — JSON-LD present, no product in it
 *   fetch_failed        the network      — the page did not load
 */
export const SURFACE_OUTCOME_META = {
  ok: {
    label: 'Read', tone: 'sync',
    detail: 'Fetched and machine-readable data extracted.',
  },
  no_structured_data: {
    label: 'No structured data', tone: 'drift',
    detail: 'A real page came back and carried no machine-readable product data.',
  },
  blocked_for_agents: {
    label: 'Blocked for agents', tone: 'fail',
    detail: 'The surface is up and declined to serve us — a challenge, a 403/429, or a body too short to be a page.',
  },
  robots_disallowed: {
    label: 'Disallowed by robots', tone: 'hold',
    detail: 'robots.txt disallows this path. We did not fetch it — a policy finding, not a fact about their markup.',
  },
  parse_failed: {
    label: 'Parse failed', tone: 'drift',
    detail: 'Machine-readable data was present but described no product.',
  },
  fetch_failed: {
    label: 'Fetch failed', tone: 'hold',
    detail: 'The page did not load.',
  },
}

const UNKNOWN_OUTCOME_META = {
  label: 'Unrecognised outcome', tone: 'hold',
  detail: 'This page has no rendering for this outcome — it is newer than this build.',
}

export function surfaceOutcomeMeta(outcome) {
  if (READABLE_OUTCOMES.has(outcome)) return SURFACE_OUTCOME_META.ok
  return SURFACE_OUTCOME_META[outcome] || UNKNOWN_OUTCOME_META
}

export function isSurfaceReadable(outcome) {
  return READABLE_OUTCOMES.has(outcome)
}

/**
 * One observed surface -> everything the row needs, with the transport
 * evidence kept alongside the verdict.
 *
 * The evidence is not decoration. "403 after 3 attempts", or a 15KB body
 * whose final_url is a /blocked path, is what makes an outcome checkable
 * rather than an assertion — and on live data today it is the only way
 * to see that a surface classified `no_structured_data` actually served
 * a wall. This layer reports both and re-classifies neither: inventing a
 * verdict the API did not give is the thing the model forbids.
 */
export function classifySurface(surface) {
  const outcome = surface?.outcome ?? null
  const transport = surface?.transport || {}
  const redirectChain = Array.isArray(transport.redirect_chain) ? transport.redirect_chain : []
  const finalUrl = transport.final_url ?? null
  const requestedUrl = surface?.url ?? null

  return {
    surface: surface?.surface ?? null,
    url: requestedUrl,
    outcome,
    meta: surfaceOutcomeMeta(outcome),
    readable: isSurfaceReadable(outcome),
    error: surface?.error ?? null,
    summary: surface?.summary && typeof surface.summary === 'object' ? surface.summary : {},
    jsonLdBlocks: Array.isArray(surface?.raw_jsonld) ? surface.raw_jsonld.length : 0,

    transport: {
      httpStatus: typeof transport.http_status === 'number' ? transport.http_status : null,
      bytes: typeof transport.bytes === 'number' ? transport.bytes : null,
      attempts: typeof transport.attempts === 'number' ? transport.attempts : null,
      finalUrl,
      redirectChain,
      userAgent: transport.user_agent ?? null,
      retryAfterSeen: transport.retry_after_seen ?? null,
    },

    // A fetch that ended somewhere other than where it was aimed is
    // worth saying out loud, whatever outcome the fetcher assigned.
    redirected: redirectChain.length > 0 || (
      finalUrl != null && requestedUrl != null && finalUrl !== requestedUrl
    ),

    robotsPolicy: normaliseRobotsPolicy(surface?.robots_policy),
  }
}

export const ROBOTS_STATE = { ALLOWED: 'allowed', BLOCKED: 'blocked', PARTIAL: 'partial', UNKNOWN: 'unknown' }

/**
 * The per-agent robots table for a surface's domain.
 *
 * An independent question from every other outcome on the row: a
 * surface can serve us a perfect page and still be closed to every
 * agent a shopper actually uses. `unknown` means robots.txt could not
 * be read — never a guess in either direction.
 */
export function normaliseRobotsPolicy(policy) {
  if (!policy || typeof policy !== 'object') return null

  const agents = (Array.isArray(policy.agents) ? policy.agents : []).map((a) => ({
    agent: a?.agent ?? null,
    platform: a?.platform ?? null,
    role: a?.role ?? null,
    root: normaliseRobotsState(a?.root),
    productPages: normaliseRobotsState(a?.product_pages),
    rule: a?.rule ?? null,
  }))

  const blockedAgents = agents.filter(
    (a) => a.root === ROBOTS_STATE.BLOCKED || a.productPages === ROBOTS_STATE.BLOCKED,
  )

  return {
    domain: policy.domain ?? null,
    path: policy.path ?? null,
    readable: policy.robots_readable === true,
    agents,
    divergence: Array.isArray(policy.divergence) ? policy.divergence : [],
    blockedCount: blockedAgents.length,
    agentCount: agents.length,
    // Only ever true when robots.txt was actually readable — an
    // unreadable robots.txt is not evidence of openness.
    closedToAllAgents: policy.robots_readable === true
      && agents.length > 0 && blockedAgents.length === agents.length,
  }
}

function normaliseRobotsState(value) {
  const state = typeof value === 'string' ? value.toLowerCase() : null
  return Object.values(ROBOTS_STATE).includes(state) ? state : ROBOTS_STATE.UNKNOWN
}

export const PROSPECT_OUTCOME = {
  OK: 'ok',
  DRIFT_DETECTED: 'drift_detected',
  INSUFFICIENT_SURFACES: 'insufficient_surfaces',
}

export const PROSPECT_OUTCOME_META = {
  ok: { label: 'Surfaces agree', tone: 'sync' },
  drift_detected: { label: 'Drift detected', tone: 'drift' },
  insufficient_surfaces: { label: 'Not comparable', tone: 'hold' },
}

/**
 * One prospect product -> its comparison verdict and its surfaces.
 *
 * `insufficient_surfaces` carries exactly the weight `null` carries in
 * dimension 2: **fewer than two readable surfaces is not agreement.**
 * One surface cannot disagree with itself, so `findings: []` under that
 * outcome means nothing was measured — never that everything matched.
 */
export function aggregateProspectProduct(product) {
  const drift = product?.drift && typeof product.drift === 'object' ? product.drift : {}
  const surfaces = (Array.isArray(product?.surfaces) ? product.surfaces : []).map(classifySurface)

  const outcome = drift.outcome ?? null
  const findings = (Array.isArray(drift.findings) ? drift.findings : []).map(normaliseProspectFinding)
  const insufficient = outcome === PROSPECT_OUTCOME.INSUFFICIENT_SURFACES

  // Prefer the API's own counts; fall back to the surfaces we can see.
  const surfacesRead = typeof drift.surfaces_read === 'number'
    ? drift.surfaces_read
    : surfaces.filter((s) => s.readable).length
  const surfacesTotal = typeof drift.surfaces_total === 'number'
    ? drift.surfaces_total
    : surfaces.length

  return {
    key: product?.product_key ?? null,
    label: product?.product_label ?? product?.product_key ?? 'Unnamed product',
    gtin: product?.gtin ?? null,
    observed: product?.observed === true,
    observedAt: product?.observed_at ?? null,
    verificationId: product?.verification_id ?? null,
    configuredSurfaces: Array.isArray(product?.configured_surfaces) ? product.configured_surfaces : [],

    outcome,
    outcomeMeta: PROSPECT_OUTCOME_META[outcome] || { label: 'No comparison', tone: 'hold' },
    insufficient,

    // null, not 0, when nothing was comparable — the same distinction
    // dimension 2 draws between "no drift" and "not measured".
    findingCount: insufficient ? null : findings.length,
    findings,

    surfacesRead,
    surfacesTotal,
    surfaces,

    // The row's most explanatory fact, when it applies: a surface that
    // served us fine but is closed to every agent a shopper uses.
    agentBlockedSurfaces: surfaces.filter((s) => s.robotsPolicy?.closedToAllAgents),
  }
}

/**
 * A prospect finding. Mirrors dimension 2's schema field-for-field with
 * the expected/observed pair replaced by two named surfaces, because
 * nothing here knows which side is right.
 */
export function normaliseProspectFinding(finding) {
  const f = finding && typeof finding === 'object' ? finding : {}
  return {
    variantKey: f.variant_key ?? null,
    field: f.field ?? null,
    surfaceA: f.surface_a ?? null,
    valueA: f.value_a ?? null,
    surfaceB: f.surface_b ?? null,
    valueB: f.value_b ?? null,
    // `gtin_missing` is a first-class finding, not an alignment problem
    // worked around: the surface that omits the identifier is the one an
    // agent trips over first.
    missingIdentifier: f.field === 'gtin_missing',
    severity: f.severity ?? null,
  }
}

/**
 * Header counts for a prospect. Deliberately its own function and its
 * own numbers: prospect data contributes nothing to the live merchant's
 * counts, and `summarize()` above never sees it.
 */
export function summarizeProspect(products = []) {
  const totals = {
    products: 0,
    observed: 0,
    comparable: 0,
    notComparable: 0,
    withDrift: 0,
    findingsTotal: 0,
    surfaces: 0,
    surfacesReadable: 0,
    outcomeCounts: {},
    agentBlockedDomains: new Set(),
    lastObservedAt: null,
  }

  for (const product of products) {
    if (!product) continue
    totals.products += 1
    if (product.observed) totals.observed += 1
    if (product.insufficient) totals.notComparable += 1
    else if (product.outcome != null) totals.comparable += 1

    if (typeof product.findingCount === 'number' && product.findingCount > 0) {
      totals.withDrift += 1
      totals.findingsTotal += product.findingCount
    }

    for (const surface of product.surfaces) {
      totals.surfaces += 1
      if (surface.readable) totals.surfacesReadable += 1
      const key = surface.outcome ?? 'unknown'
      totals.outcomeCounts[key] = (totals.outcomeCounts[key] || 0) + 1
      if (surface.robotsPolicy?.closedToAllAgents && surface.robotsPolicy.domain) {
        totals.agentBlockedDomains.add(surface.robotsPolicy.domain)
      }
    }

    if (product.observedAt && (!totals.lastObservedAt || product.observedAt > totals.lastObservedAt)) {
      totals.lastObservedAt = product.observedAt
    }
  }

  return { ...totals, agentBlockedDomains: [...totals.agentBlockedDomains] }
}
