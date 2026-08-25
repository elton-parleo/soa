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
export const METHOD_GMC_DIAGNOSTICS = 'gmc_diagnostics'

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

// ─── Acceptance authority (dimension 3 applicability) ────────────────

// A channel has an acceptance authority when a third party can accept
// or reject what we sent. Today only Merchant Center can. Every other
// channel's acceptance is permanently `unknown` and renders nothing —
// there is nobody to have an opinion.
const ACCEPTANCE_AUTHORITY_CHANNELS = new Set(['merchant_center'])

export function hasAcceptanceAuthority(channelSlug) {
  return ACCEPTANCE_AUTHORITY_CHANNELS.has(channelSlug)
}

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
export function aggregateCell(publication, records = [], { channelSlug = null } = {}) {
  const { state: publishState, reason: publishReason } = publishStateOf(publication)
  const latestPublishedAt = publication?.published_at || null

  const classified = (records || [])
    .map((record) => classifyRecord(record, latestPublishedAt))
    .sort(byCreatedAtDesc)

  const fresh = classified.filter((c) => c.fresh)
  const stale = classified.filter((c) => !c.fresh)

  // Dimension 2 — drift. null unless a fresh probe says otherwise.
  const probe = fresh.find((c) => c.kind === 'probe') || null
  const drift = probe ? probe.findings.length : null

  // Dimension 3 — acceptance. Only where somebody has the authority to
  // have an opinion.
  const acceptanceRecord = hasAcceptanceAuthority(channelSlug)
    ? (fresh.find((c) => c.kind === 'acceptance') || null)
    : null
  const acceptance = acceptanceRecord ? acceptanceRecord.state : ACCEPTANCE.UNKNOWN
  const issues = acceptanceRecord ? acceptanceRecord.issues : []

  // Dimension 4 — observability. Fresh unreadable records only: a stale
  // unreadable record is excluded by freshness like everything else.
  const unreadable = fresh.filter((c) => c.kind === 'unreadable')

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
    hasAcceptanceAuthority: hasAcceptanceAuthority(channelSlug),

    unreadableCount: unreadable.length,
    unreadableRecords: unreadable,

    staleCount: stale.length,
    staleRecords: stale,

    records: classified,
    lastVerifiedAt: fresh.length > 0 ? fresh[0].createdAt : null,
    badge: driftBadge(drift),
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
export function driftBadge(drift) {
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
    lastVerifiedAt: null,
  }

  for (const cell of cells) {
    if (!cell) continue
    totals.totalCells += 1
    if (cell.publishState === PUBLISH_STATE.PUBLISHED) totals.publishedCells += 1

    // Dimension 2 only.
    if (cell.drift === 0) totals.verifiedCells += 1
    if (typeof cell.drift === 'number' && cell.drift > 0) {
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
