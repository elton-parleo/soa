/**
 * Partial-read report state (Part 3): the discovery finding — renders
 * only when isPartialRead(pillars, degradedReason) is true (checked by
 * the caller, LiteFullReportV4.jsx), placed directly after the
 * headline-finding band. Heading/body/fix-framing come from the
 * failure-point registry (reportContent.js's FAILURE_POINT_COPY),
 * never hardcoded here. The four-step trace renders only the steps
 * report.scan.discovery_trace can actually support — no step ever
 * asserts an outcome the record doesn't establish.
 */
import { Glyph } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { _fetchProbeSentence } from '../DegradedRunBanner.jsx'
import {
  FAILURE_POINT_COPY, BLOCKED_STEP_COPY, DISCOVERY_OUTCOME_COPY,
  FETCH_PROBE_EVIDENCE_COPY, UNREACHABLE_STEP_COPY, resolveFailurePointBody,
} from './reportContent.js'
import { partialReadFailurePoint, buildMeasurableContext, isWallFailurePoint } from './reportDerive.js'

const STEP_META = {
  robots: { n: '01', label: 'ROBOTS.TXT' },
  homepage: { n: '02', label: 'HOMEPAGE' },
  sitemaps: { n: '03', label: 'SITEMAPS' },
  productPages: { n: '04', label: 'PRODUCT PAGES' },
}

// Discovery follow-up (Part 4): apps/pipeline/scan/discovery_outcome.py's
// tier keys, in the order they're attempted, read next to their
// discovery_outcome.tiers[].outcome string ("found N" / "found 0" /
// "skipped: <reason>") under WHAT WE TRIED.
const TIER_LABELS = {
  sitemap: 'Sitemap walk',
  collection_hop: 'Category page hop',
  platform_endpoint: 'Platform catalog endpoint',
  llm_assisted: 'AI-assisted discovery',
  homepage: 'Homepage links',
}

function _urlFilename(url) {
  if (!url) return null
  try {
    const parts = new URL(url).pathname.split('/').filter(Boolean)
    return parts[parts.length - 1] || url
  } catch {
    return url
  }
}

// Blocked-run copy pass (2c): the blocked path reads its step facts in
// plain verbs from BLOCKED_STEP_COPY (registry-sourced, reportContent.js)
// instead of the generic wording below. Unreachable-host follow-up: the
// unreachable path does the same from UNREACHABLE_STEP_COPY, since
// "turned away" would be the wrong verb for a request nobody answered.
const STEP_COPY_BY_FAILURE_POINT = { blocked: BLOCKED_STEP_COPY, unreachable: UNREACHABLE_STEP_COPY }

function _stepFact(key, good, failurePoint, genericGood, genericBad) {
  const specific = STEP_COPY_BY_FAILURE_POINT[failurePoint]?.[key]
  if (specific) return good ? specific.good : specific.bad
  return good ? genericGood : genericBad
}

// Discovery follow-up (Part 4): the sitemaps/product-pages steps read
// real per-run facts straight off discovery_outcome (recorded on every
// run — see discovery_outcome.py) instead of the older, coarser
// discovery_trace counts, whenever it's present. Falls back to the
// generic trace-only fact when discoveryOutcome is absent (an older
// report) so nothing changes for those.
function _sitemapsStepFact(discoveryOutcome, trace) {
  if (!discoveryOutcome || !(discoveryOutcome.sitemaps || []).length) {
    const n = trace.sitemaps_read
    return `${n} resolved · ${trace.product_urls_found} product URL${trace.product_urls_found === 1 ? '' : 's'} found.`
  }
  const read = discoveryOutcome.sitemaps.filter((s) => s.outcome === 'read')
  const totalProductUrls = read.reduce((sum, s) => sum + (s.product_urls || 0), 0)
  const names = read.map((s) => s.name).slice(0, 2).join(', ')
  const chosen = discoveryOutcome.child_chosen ? _urlFilename(discoveryOutcome.child_chosen) : null
  return `${read.length} read${names ? ` (${names}${read.length > 2 ? ', …' : ''})` : ''}`
    + (chosen ? ` · picked ${chosen}` : '')
    + ` · ${totalProductUrls} product URL${totalProductUrls === 1 ? '' : 's'} found.`
}

function _productPagesStepFact(discoveryOutcome, failurePoint, fetched, unmeasurablePoints) {
  const genericBad = `None reached, none parsed${unmeasurablePoints ? ` · ${Math.round(unmeasurablePoints)} points unread.` : '.'}`
  if (discoveryOutcome && (discoveryOutcome.product_pages_attempted || 0) > 0) {
    const attempted = discoveryOutcome.product_pages_attempted
    if (fetched > 0) return `${fetched} of ${attempted} reached and parsed.`
    if (discoveryOutcome.code === 'product_pages_refused') return `Found ${attempted}, refused every request.`
    if (discoveryOutcome.code === 'product_pages_unreadable') return `Found ${attempted}, none could be read (network error or timeout).`
  }
  return _stepFact('productPages', fetched > 0, failurePoint, `${fetched} reached and parsed.`, genericBad)
}

function _buildSteps(trace, unmeasurablePoints, failurePoint, discoveryOutcome) {
  if (!trace) return []
  const steps = []
  if (trace.robots_ok != null) {
    steps.push({
      key: 'robots',
      good: trace.robots_ok,
      fact: _stepFact('robots', trace.robots_ok, failurePoint, 'Read fine. Product paths allowed, no blocks on readers.', 'Blocked or rate-limited before we could read it.'),
    })
  }
  if (trace.homepage_fetched != null) {
    steps.push({
      key: 'homepage',
      good: trace.homepage_fetched,
      fact: _stepFact('homepage', trace.homepage_fetched, failurePoint, 'Fetched fine.', 'Could not be fetched this run.'),
    })
  }
  if (trace.sitemaps_read != null && trace.product_urls_found != null) {
    steps.push({
      key: 'sitemaps',
      good: trace.product_urls_found > 0,
      fact: _sitemapsStepFact(discoveryOutcome, trace),
    })
  }
  if (trace.product_pages_fetched != null) {
    const fetched = trace.product_pages_fetched
    steps.push({
      key: 'productPages',
      good: fetched > 0,
      fact: _productPagesStepFact(discoveryOutcome, failurePoint, fetched, unmeasurablePoints),
    })
  }
  return steps
}

// Blocked-run evidence (this session): the probe's own fact block.
// Renders only for the three decisive outcomes, and only on a wall run
// — blocked, or (unreachable-host follow-up) one that never answered.
// On a sampler miss the probe says nothing about a wall (see
// DegradedRunBanner's _fetchProbeSentence, which keeps that
// distinction) and this would overclaim. Copy is registry-sourced;
// this only decides whether there is a fact to show.
function FetchProbeEvidence({ probe, failurePoint }) {
  if (!probe || !isWallFailurePoint(failurePoint)) return null
  const line = FETCH_PROBE_EVIDENCE_COPY[probe.outcome]
  if (!line) return null
  const kindPhrase = probe.kind === 'store_root' ? 'your homepage' : 'your product page'
  const note = probe.outcome === 'quoted_price'
    ? FETCH_PROBE_EVIDENCE_COPY.quoted_price_note
    : probe.outcome === 'could_not_access'
      ? FETCH_PROBE_EVIDENCE_COPY.could_not_access_note
      : null
  return (
    <div style={{ marginTop: 18, padding: '15px 17px', background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12 }}>
      <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', marginBottom: 8 }}>{FETCH_PROBE_EVIDENCE_COPY.label}</div>
      <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.6 }}>
        {line({ kindPhrase, price: probe.price })}
      </div>
      {note && (
        <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 7 }}>{note}</div>
      )}
    </div>
  )
}

export function DiscoveryFinding({ report, open, onToggle }) {
  const degradedReason = report.scan?.degraded_reason
  const discoveryOutcome = report.scan?.discovery_outcome
  const failurePoint = partialReadFailurePoint(degradedReason, discoveryOutcome)
  // Discovery follow-up (Part 4): a code-specific registry entry, when
  // discovery_outcome is present and covers this exact run's code —
  // falls back to the coarser 3-bucket FAILURE_POINT_COPY otherwise
  // (an older report, or a code this table doesn't (yet) cover), same
  // as before this session.
  const outcomeCopy = discoveryOutcome && DISCOVERY_OUTCOME_COPY[discoveryOutcome.code]
  const copy = outcomeCopy || FAILURE_POINT_COPY[failurePoint]
  const trace = report.scan?.discovery_trace
  const bannerFacts = report.scan?.degraded_banner_facts
  const edgeVendor = report.scan?.edge_vendor
  const unmeasurablePoints = buildMeasurableContext(report.pillars).unmeasurable_points
  const steps = _buildSteps(trace, unmeasurablePoints, failurePoint, discoveryOutcome)
  // Blocked-run evidence: on a wall run the probe gets its own fact
  // block below, so the trailing sentence would be the same claim
  // twice — it stays only where it is the ONLY place the probe speaks.
  const wall = isWallFailurePoint(failurePoint)
  const probeSentence = wall
    ? ''
    : _fetchProbeSentence(bannerFacts, degradedReason, report.scan_status)
  // outcomeCopy has no `body` of its own — discoveryOutcome.summary IS
  // that body, already first-person fact-grounded prose from this run
  // (see reportContent.js's DISCOVERY_OUTCOME_COPY doc comment).
  const bodyText = outcomeCopy ? (discoveryOutcome.summary || '') : resolveFailurePointBody(copy.body, bannerFacts, edgeVendor)
  const tiers = discoveryOutcome?.tiers || []
  const exampleUrls = discoveryOutcome?.example_urls || []

  return (
    <ReportSection
      id="why" eyebrow="FINDING 00 · DISCOVERY · MEASURED" title={copy.heading}
      open={open} onToggle={onToggle} accentColor="var(--amber)"
    >
      <div style={{ fontSize: 14, color: 'var(--muted)', lineHeight: 1.6, marginTop: 4 }}>
        {bodyText}{probeSentence}
      </div>

      {steps.length > 0 && (
        <div className="lite-discovery-steps-grid" style={{ display: 'grid', gridTemplateColumns: `repeat(${steps.length},1fr)`, gap: 14, marginTop: 20 }}>
          {steps.map((s) => {
            const meta = STEP_META[s.key]
            return (
              <div key={s.key} style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <Glyph name={s.good ? 'check' : 'x'} size={13} color={s.good ? 'var(--green)' : 'var(--red-deep)'} />
                  <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>{meta.n} · {meta.label}</span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text)', marginTop: 8, lineHeight: 1.5 }}>{s.fact}</div>
              </div>
            )
          })}
        </div>
      )}

      {tiers.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', marginBottom: 8 }}>WHAT WE TRIED</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {tiers.map((t, i) => (
              <div key={`${t.tier}-${i}`} style={{ fontSize: 12.5, color: 'var(--muted)', display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span>{TIER_LABELS[t.tier] || t.tier}</span>
                <span style={{ color: 'var(--text)' }}>{t.outcome}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <FetchProbeEvidence probe={bannerFacts?.fetch_probe} failurePoint={failurePoint} />

      {exampleUrls.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', marginBottom: 8 }}>EXAMPLE URLS WE FOUND</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--muted)', background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 8, padding: '10px 12px', lineHeight: 1.7, wordBreak: 'break-all' }}>
            {exampleUrls.map((u) => <div key={u}>{u}</div>)}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11, marginTop: 22, padding: '15px 17px', background: 'var(--amber-tint)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 12 }}>
        <Glyph name="filter" size={15} color="var(--amber-deep)" />
        {wall ? (
          // Blocked-run copy pass (1c): the registry's action line
          // stands on its own here — the causal "why" already lives in
          // bodyText above, so this box doesn't repeat it.
          <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.6 }}>{resolveFailurePointBody(copy.fixFraming, bannerFacts, edgeVendor)}</div>
        ) : (
          <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.6 }}>
            <b style={{ color: 'var(--text-strong)' }}>What this usually means:</b> {copy.explanation} That's fix 01 below — it unlocks the {Math.round(unmeasurablePoints)} points this run couldn't read.
          </div>
        )}
      </div>
    </ReportSection>
  )
}
