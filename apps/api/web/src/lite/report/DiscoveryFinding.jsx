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
import { FAILURE_POINT_COPY, BLOCKED_STEP_COPY, resolveFailurePointBody } from './reportContent.js'
import { partialReadFailurePoint, buildMeasurableContext } from './reportDerive.js'

const STEP_META = {
  robots: { n: '01', label: 'ROBOTS.TXT' },
  homepage: { n: '02', label: 'HOMEPAGE' },
  sitemaps: { n: '03', label: 'SITEMAPS' },
  productPages: { n: '04', label: 'PRODUCT PAGES' },
}

// Blocked-run copy pass (2c): the blocked path reads its step facts in
// plain verbs from BLOCKED_STEP_COPY (registry-sourced, reportContent.js)
// instead of the generic wording below — the other failure points are
// untouched this session.
function _stepFact(key, good, failurePoint, genericGood, genericBad) {
  const blocked = failurePoint === 'blocked' ? BLOCKED_STEP_COPY[key] : null
  if (blocked) return good ? blocked.good : blocked.bad
  return good ? genericGood : genericBad
}

function _buildSteps(trace, unmeasurablePoints, failurePoint) {
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
    const n = trace.sitemaps_read
    steps.push({
      key: 'sitemaps',
      good: trace.product_urls_found > 0,
      fact: `${n} resolved · ${trace.product_urls_found} product URL${trace.product_urls_found === 1 ? '' : 's'} found.`,
    })
  }
  if (trace.product_pages_fetched != null) {
    const fetched = trace.product_pages_fetched
    const genericBad = `None reached, none parsed${unmeasurablePoints ? ` · ${Math.round(unmeasurablePoints)} points unread.` : '.'}`
    steps.push({
      key: 'productPages',
      good: fetched > 0,
      fact: _stepFact('productPages', fetched > 0, failurePoint, `${fetched} reached and parsed.`, genericBad),
    })
  }
  return steps
}

export function DiscoveryFinding({ report, open, onToggle }) {
  const degradedReason = report.scan?.degraded_reason
  const failurePoint = partialReadFailurePoint(degradedReason)
  const copy = FAILURE_POINT_COPY[failurePoint]
  const trace = report.scan?.discovery_trace
  const bannerFacts = report.scan?.degraded_banner_facts
  const unmeasurablePoints = buildMeasurableContext(report.pillars).unmeasurable_points
  const steps = _buildSteps(trace, unmeasurablePoints, failurePoint)
  const probeSentence = _fetchProbeSentence(bannerFacts, degradedReason, report.scan_status)
  const bodyText = resolveFailurePointBody(copy.body, bannerFacts)

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

      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11, marginTop: 22, padding: '15px 17px', background: 'var(--amber-tint)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 12 }}>
        <Glyph name="filter" size={15} color="var(--amber-deep)" />
        {failurePoint === 'blocked' ? (
          // Blocked-run copy pass (1c): the registry's action line
          // stands on its own here — the causal "why" already lives in
          // bodyText above, so this box doesn't repeat it.
          <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.6 }}>{copy.fixFraming}</div>
        ) : (
          <div style={{ fontSize: 13.5, color: 'var(--text)', lineHeight: 1.6 }}>
            <b style={{ color: 'var(--text-strong)' }}>What this usually means:</b> {copy.explanation} That's fix 01 below — it unlocks the {Math.round(unmeasurablePoints)} points this run couldn't read.
          </div>
        )}
      </div>
    </ReportSection>
  )
}
