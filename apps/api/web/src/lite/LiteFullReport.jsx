/**
 * Full (unlocked) report. Section order is the product (Stage 4) and
 * must not be reshuffled — this stage only restyles each section to
 * the Parleo Scan report design language (see design-refs/): executive
 * tiles, visibility by purchase stage, evidence gallery, why-section
 * (all 8 scan dimensions), an optional diagnosis card, ranked fixes,
 * exposure calculator, the diagnostic-tier "cliff" card, footer.
 *
 * Adaptive by report.scan.status: 'skipped' (or no scan row at all)
 * means no store_url was ever submitted — the why-section becomes a
 * prompt to add one, since there is no API to attach a URL after the
 * fact and no per-dimension data to show either way. 'blocked'/'failed'
 * show an honest, static explanation (Stage 3 returns an empty
 * dimensions array for any non-'complete' scan, so this can't be
 * data-driven). 'complete' renders the full 8-dimension breakdown.
 *
 * report.diagnosis and report.evidence_examples are forward-looking,
 * optional fields — no backend stage emits them yet, so both are read
 * defensively and simply omitted when absent, same pattern as Stage 4's
 * worst_mention_excerpt.
 *
 * Stage 13 (W3/W4/W5): report.competitor_source drives three things in
 * VisibilitySection — a solo run ('none') never shows a fake 100%-share
 * donut or a single-entity incentive-citation "comparison" (both
 * collapse into SoloComparisonNote); a 'generated'/'mixed' run shows
 * CompetitorProvenanceNote; ENTITY_COLORS (liteTheme.jsx) now has 5
 * rival tones so a comparison of up to 6 entities (1 primary + 5
 * auto-generated/manual competitors) stays visually distinguishable.
 */
import { useState } from 'react'
import {
  accessibilityBadgeText, computeExposure, formatCurrency, formatDateStamp,
  getDominantRivalPayoff, getIncentiveCitationPayoff, groupDimensionsByFamily, rankDimensionsByGap,
  seedAnnualRevenue, REVENUE_SLIDER_MIN, REVENUE_SLIDER_MAX,
} from './liteDerive.js'
import {
  ENTITY_COLORS, RIVAL_SLATE_RAMP, LightCard, DarkCard, SectionHeader, ReportHeaderBar,
  InfoBadge, Chip, useAnimateOnMount, formatScore, FullDiagnosticGate, FULL_DIAGNOSTIC_CTA_LABEL,
} from './liteTheme.jsx'
import {
  DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_ACCESSIBILITY, PILLAR_NAMES,
  PILLAR_TRUE_VALUE, PILLAR_VISIBILITY, TOTAL_MAX, LITE_QUERY_COUNT,
  VERDICT_AGENT_READY, VERDICT_COMPOSITE_THRESHOLD, VERDICT_TRUE_VALUE_RATIO_THRESHOLD,
} from './landing/scanDimensionsRegistry.js'

const DEFAULT_REVENUE = 12_000_000
const DEFAULT_AI_SHARE_PCT = 20

// Report redesign (Part 3, M2): one shared hook per accordion group (a
// pillar card) — opening a row's panel always closes whichever other
// row's panel was open in that same group, never more than one at once.
function useSingleOpenAccordion() {
  const [openCode, setOpenCode] = useState(null)
  function toggle(code) {
    setOpenCode((current) => (current === code ? null : code))
  }
  return { openCode, toggle }
}

// ─── v3 pillar helpers (Stage 19) ───────────────────────────────────────
// report.pillars is the single source of truth for a scorer_version "3"
// row's report rendering — present only when the scan itself was v3
// (see public_lite.py::_build_report_payload); every v3-only component
// below keys off it, never off report.scan.dimensions (F1-V5-keyed,
// unusable for a v3 row — see build_pillars_payload's docstring).

function isV3Report(report) {
  return Boolean(report.pillars)
}

// earned = sum over every dimension row (an na dimension's earned/max
// are already zeroed server-side — see lite_pillars.py); max = sum over
// non-na rows only, since an na dimension's *nominal* max (e.g.
// protocol_feed's crawl-side 6) is NOT pre-zeroed the way member_value's
// is — filtering here, uniformly, handles both cases correctly without
// special-casing either.
function pillarEarnedMax(pillar) {
  const dims = pillar?.dimensions || []
  const earned = dims.reduce((sum, d) => sum + (d.earned || 0), 0)
  const max = dims.filter((d) => !d.na).reduce((sum, d) => sum + (d.max || 0), 0)
  return { earned, max }
}

function dimByCode(dims, code) {
  return (dims || []).find((d) => d.code === code) || null
}

// ─── Executive tiles ────────────────────────────────────────────────────

function Tile({ label, value, badge }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 96 }}>
      {badge ? (
        <span className="lite-pill" style={{ fontSize: 11, padding: '5px 12px', cursor: 'default' }}>{badge}</span>
      ) : (
        <div className="lite-numeral lite-numeral--tile">{value}</div>
      )}
      <div className="lite-label" style={{ marginTop: 8 }}>{label}</div>
    </div>
  )
}

// Stage 19 (R6): a row scored under a pre-v3 methodology (report.pillars
// absent, but the scan itself genuinely completed — not skipped/blocked/
// failed) must say so plainly rather than silently rendering the old
// two-family layout with no explanation. No re-run endpoint exists yet,
// so the affordance just starts a fresh submission.
function PreviousMethodologyNotice() {
  return (
    <div style={{ textAlign: 'center', marginBottom: 18 }}>
      <div className="lite-mono lite-muted" style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.04em' }}>
        SCORED UNDER A PREVIOUS METHODOLOGY
      </div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
        This report predates the current three-pillar score.{' '}
        <a href="/" className="lite-mono" style={{ color: 'var(--accent-ink)', fontWeight: 700 }}>
          Re-run for the current three-pillar score
        </a>
      </div>
    </div>
  )
}

function ExecutiveTilesLegacy({ report, exposure }) {
  const accessBadge = accessibilityBadgeText(report.scan_status)
  const showNotice = report.scan?.status === 'complete'
  return (
    <LightCard>
      {showNotice && <PreviousMethodologyNotice />}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28, justifyContent: 'center' }}>
        <Tile label="Composite score" value={formatScore(report.composite)} />
        <Tile label="Visibility" value={formatScore(report.visibility)} />
        <Tile label="Accessibility" value={formatScore(report.accessibility)} badge={accessBadge} />
        <Tile label="Modeled exposure/mo" value={formatCurrency(exposure)} />
      </div>
    </LightCard>
  )
}

// ─── Stage 21 (H): hero verdict template table ──────────────────────────
// ONE deterministic branch per data shape, no LLM — keyed off the
// visibility/True-Value pillar ratios, member_value_na, and (Stage 25,
// Part 5) the actual verdict gate — exactly the inputs a visitor's own
// hero numbers already show. Priority order matters: weak visibility
// overrides everything else (nothing else matters if agents barely know
// you), then the na framing (a different STORY than "zero" —
// normalized, not empty), then the zero/partial/full True Value bands.
//
// Stage 25 (Part 5, G2): "strong_full_tv" is the one branch that reads
// as an unqualified win ("and they get your value right") — the one
// case where a narrative/verdict mismatch would actually mislead a
// visitor, since the gate also weighs Accessibility, which this
// narrative's own visRatio/tvRatio inputs never look at. A store can
// clear both ratio bands here and still land NOT-AGENT-READY on a weak
// Accessibility pillar; verdict-aware branching catches exactly that
// case rather than declaring a win the gate disagrees with. The other
// three bands already read as "not fully there" and never risk this.
const VISIBILITY_WEAK_THRESHOLD = 0.5
const TRUE_VALUE_STRONG_THRESHOLD = 0.75

// Report redesign (Part 2): every branch is now verdict-aware, not just
// the two True-Value-strong ones — whenever pillars.verdict is present
// and the branch hasn't already read it itself (strong_full_tv/
// strong_tv_not_ready do that above, since a win claim there specifically
// needs the gate's own say-so), append the gate's own plain-language
// readiness line. A pre-G1 report (no verdict key at all) appends
// nothing — never a fabricated readiness claim.
function _appendVerdictClause(result, verdict) {
  if (!verdict) return result
  const clause = verdict === VERDICT_AGENT_READY
    ? ' You clear the agent-ready bar.'
    : ' Below the agent-ready bar.'
  return { ...result, support: result.support + clause }
}

function deriveHeroVerdict(pillars) {
  const vis = pillarEarnedMax(pillars.visibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const visRatio = vis.max ? vis.earned / vis.max : 0
  const tvRatio = tv.max ? tv.earned / tv.max : 0

  if (visRatio < VISIBILITY_WEAK_THRESHOLD) {
    return _appendVerdictClause({
      key: 'weak_visibility',
      plain: 'Agents barely know you exist —', bold: 'most answers never mention you at all.',
      support: "Visibility comes before value — that's the first fix.",
    }, pillars.verdict)
  }
  if (pillars.member_value_na) {
    return _appendVerdictClause({
      key: 'tv_na',
      plain: 'Agents talk about you, and', bold: 'your value score is normalized —',
      support: `No membership program was found, so True Value is scored out of ${formatScore(tv.max)}, not 40.`,
    }, pillars.verdict)
  }
  if (tv.earned === 0) {
    return _appendVerdictClause({
      key: 'strong_zero_tv',
      plain: 'Agents talk about you —', bold: 'they never talk about your value.',
      support: `You hold ${formatScore(vis.earned)}/${formatScore(vis.max)} visibility points, but 0 of ${formatScore(tv.max)} True Value points.`,
    }, pillars.verdict)
  }
  if (tvRatio >= TRUE_VALUE_STRONG_THRESHOLD) {
    if (pillars.verdict && pillars.verdict !== VERDICT_AGENT_READY) {
      return {
        key: 'strong_tv_not_ready',
        plain: 'Agents talk about you, and', bold: 'your value comes through —',
        support: "but a gap elsewhere in the storefront still keeps you short of agent-ready.",
      }
    }
    return {
      key: 'strong_full_tv',
      plain: 'Agents talk about you —', bold: 'and they get your value right.',
      support: 'Visibility and True Value are both landing.',
    }
  }
  return _appendVerdictClause({
    key: 'strong_partial_tv',
    plain: 'Agents talk about you, and', bold: 'some of your value gets through —',
    support: "But there's real room left to encode.",
  }, pillars.verdict)
}

// ─── Stage 21 (H1): one segmented bar, three pillars ────────────────────
// Segment WIDTH is the pillar's nominal registry weight (computed live
// from DIMENSIONS, never a cached export — so a perturbed weight moves
// the bar), independent of member_value_na — a stable visual scale.
// Segment FILL is earned/max, where pillarEarnedMax's own max already
// resolves to the applicable (na-adjusted) denominator, same as the
// report's own tiles.
function pillarNominalWeight(pillar) {
  return DIMENSIONS.filter((d) => d.pillar === pillar).reduce((sum, d) => sum + d.weight, 0)
}

function PillarBarSegment({ label, earned, max, weight, isTrueValue }) {
  const pct = max ? Math.max(0, Math.min(100, (earned / max) * 100)) : 0
  const isZero = earned === 0
  return (
    <div style={{ flex: weight, position: 'relative', background: 'var(--ink-2)' }}>
      <div
        style={{
          position: 'absolute', inset: 0, width: `${pct}%`,
          background: isTrueValue ? 'var(--accent)' : 'var(--foundation-on-dark)',
        }}
      />
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span
          className="lite-mono"
          style={{
            fontSize: 10.5, letterSpacing: '0.06em', fontWeight: 700,
            color: isZero && isTrueValue ? 'var(--bad-on-dark)' : '#fff',
          }}
        >
          {label} {formatScore(earned)}/{formatScore(max)}
        </span>
      </div>
    </div>
  )
}

function PillarSegmentedBar({ pillars }) {
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  return (
    <div>
      <div style={{ display: 'flex', height: 40, borderRadius: 10, overflow: 'hidden', gap: 3, margin: '20px 0 6px' }}>
        <PillarBarSegment
          label={PILLAR_NAMES[PILLAR_VISIBILITY].toUpperCase()}
          earned={vis.earned} max={vis.max} weight={pillarNominalWeight(PILLAR_VISIBILITY)}
        />
        <PillarBarSegment
          label={PILLAR_NAMES[PILLAR_ACCESSIBILITY].toUpperCase()}
          earned={acc.earned} max={acc.max} weight={pillarNominalWeight(PILLAR_ACCESSIBILITY)}
        />
        <PillarBarSegment
          label={PILLAR_NAMES[PILLAR_TRUE_VALUE].toUpperCase()}
          earned={tv.earned} max={tv.max} weight={pillarNominalWeight(PILLAR_TRUE_VALUE)} isTrueValue
        />
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6,
        fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.08em', color: 'var(--text-inv-2)',
      }}>
        <span>ONE BAR · THREE PILLARS · FILLED = EARNED</span>
        <span>
          {pillars.member_value_na
            ? `*MEMBER VALUE NOT APPLICABLE — SCORED ON ${formatScore(tv.max + vis.max + acc.max)} POINTS, SHOWN OUT OF 100`
            : 'COMPOSITE = STRAIGHT SUM'}
        </span>
      </div>
    </div>
  )
}

// Stage 25 (Part 5/6, G1/A2): the verdict chip is a pass/fail READING of
// the gate (registry-defined thresholds, computed server-side —
// build_pillars_payload/compute_verdict), deliberately distinct styling
// from the narrative verdict LINE below it — that line is color
// commentary, this chip is the strict threshold. Absent entirely for a
// pre-G1 report (no pillars.verdict key at all), never a fabricated
// default.
function VerdictChip({ verdict }) {
  if (!verdict) return null
  const isReady = verdict === VERDICT_AGENT_READY
  return (
    <span
      className="lite-mono"
      style={{
        display: 'inline-block', fontSize: 11, fontWeight: 700, letterSpacing: '0.05em',
        padding: '4px 10px', borderRadius: 999,
        background: isReady ? 'var(--good)' : 'var(--ink-2)',
        color: isReady ? '#fff' : 'var(--bad-on-dark)',
      }}
    >
      {verdict}
    </span>
  )
}

function ExecutiveHeroV3({ report, exposure }) {
  const pillars = report.pillars
  const verdict = deriveHeroVerdict(pillars)
  return (
    <DarkCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div>
          <div className="lite-mono" style={{ fontSize: 10.5, letterSpacing: '0.12em', color: 'var(--text-inv-2)', textTransform: 'uppercase' }}>
            Agent commerce score · {formatDateStamp()}
          </div>
          <div className="lite-numeral lite-numeral--inv" style={{ fontSize: 56, lineHeight: 1, marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
            {formatScore(report.composite)}
            <span style={{ fontSize: 18, color: 'var(--text-inv-2)', fontWeight: 400 }}>/100</span>
            <VerdictChip verdict={pillars.verdict} />
          </div>
          <div className="lite-body--inv" style={{ fontSize: 14, maxWidth: 320, lineHeight: 1.5, marginTop: 6 }}>
            {verdict.plain} <strong style={{ color: '#fff' }}>{verdict.bold}</strong> {verdict.support}
          </div>
        </div>
        <div style={{ background: 'var(--ink-2)', borderRadius: 12, padding: '12px 16px', textAlign: 'right' }}>
          <div style={{ fontSize: 22, fontWeight: 600, color: '#fff' }}>{formatCurrency(exposure)}</div>
          <div className="lite-mono" style={{ fontSize: 10.5, color: 'var(--text-inv-2)', letterSpacing: '0.08em' }}>
            MODELED EXPOSURE / YEAR
          </div>
        </div>
      </div>
      <PillarSegmentedBar pillars={pillars} />
    </DarkCard>
  )
}

function ExecutiveTiles({ report, exposure }) {
  if (isV3Report(report)) {
    return <ExecutiveHeroV3 report={report} exposure={exposure} />
  }
  return <ExecutiveTilesLegacy report={report} exposure={exposure} />
}

// ─── Visibility section (Stage 7 — replaces the old per-stage bars) ────
// G1: no per-stage aggregate ever reaches this component — the API
// stopped serializing them (public_lite.py's by_stage is always null).
// The two cards below render only visibility_breakdown's stage-agnostic
// mention_rate/share_of_mentions aggregates; the funnel teaser (W4)
// shows fixed DECORATIVE_* constants, never real data.

function LegendDot({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-2)' }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: 'inline-block' }} aria-hidden="true" />
      {label}
    </span>
  )
}

function MentionRateCard({ mentionRate }) {
  const animated = useAnimateOnMount()
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Mention rate</div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
        How many of the {LITE_QUERY_COUNT} shopper questions named each brand at least once
      </div>
      {mentionRate.map((r, i) => (
        <div key={r.entity} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text)', marginBottom: 4 }}>
            <span>{r.entity}{r.is_primary ? ' (you)' : ''}</span>
            <span className="lite-mono" style={{ fontWeight: 700 }}>
              {formatScore(r.rate_pct)}% · {r.mentioned_queries}/{r.total_queries}
            </span>
          </div>
          <div className="lite-bar-track">
            <div
              className="lite-bar-fill"
              style={{ width: animated ? `${r.rate_pct}%` : '0%', background: ENTITY_COLORS[i % ENTITY_COLORS.length] }}
            />
          </div>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 16, marginTop: 12 }}>
        <LegendDot color={ENTITY_COLORS[0]} label="You" />
        <LegendDot color={ENTITY_COLORS[1]} label="Rivals" />
      </div>
    </div>
  )
}

// Stage 21 (V1): primary is always --accent, rivals cycle through the
// slate ramp by RANK (not raw array index) — is_primary-aware so a
// comparison-set ordering quirk from the API can never accidentally
// hand the accent color to a rival.
function entityColors(entities, { primaryColor = 'var(--accent)', rivalRamp = ENTITY_COLORS.slice(1) } = {}) {
  let rivalIndex = 0
  return (entities || []).map((e) => {
    if (e.is_primary) return primaryColor
    const color = rivalRamp[rivalIndex % rivalRamp.length]
    rivalIndex += 1
    return color
  })
}

function ShareDonut({ shares, colors }) {
  const size = 116
  const strokeWidth = 16
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const resolvedColors = colors || shares.map((_, i) => ENTITY_COLORS[i % ENTITY_COLORS.length])
  let cumulativePct = 0
  const segments = shares.map((s, i) => {
    const pct = Math.max(0, Math.min(100, s.share_pct || 0))
    const dash = (pct / 100) * circumference
    const seg = {
      key: s.entity,
      color: resolvedColors[i],
      dasharray: `${dash} ${Math.max(0, circumference - dash)}`,
      dashoffset: -((cumulativePct / 100) * circumference),
    }
    cumulativePct += pct
    return seg
  })
  const primaryShare = shares.find((s) => s.is_primary)
  const label = shares
    .map((s) => `${s.entity} ${formatScore(s.share_pct)}% of mentions`)
    .join(', ')

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }} role="img" aria-label={label || 'Share of mentions'}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--track)" strokeWidth={strokeWidth} />
        {segments.map((seg) => (
          <circle
            key={seg.key}
            cx={size / 2} cy={size / 2} r={radius} fill="none"
            stroke={seg.color} strokeWidth={strokeWidth}
            strokeDasharray={seg.dasharray} strokeDashoffset={seg.dashoffset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        ))}
      </svg>
      <div
        aria-hidden="true"
        style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}
      >
        <span className="lite-numeral" style={{ fontSize: 22 }}>
          {primaryShare ? formatScore(primaryShare.share_pct) : '—'}%
        </span>
        <span className="lite-label" style={{ fontSize: 9 }}>Your share</span>
      </div>
    </div>
  )
}

function ShareOfMentionsCard({ shareOfMentions, totals, scoredPoints, title }) {
  const payoff = getDominantRivalPayoff({ share_of_mentions: shareOfMentions, totals })
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{title || 'Share of mentions'}</div>
        {scoredPoints && <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700 }}>{scoredPoints}</span>}
      </div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
        Of every brand mention across all answers, how many were yours
      </div>
      <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
        <ShareDonut shares={shareOfMentions} />
        <div style={{ flex: '1 1 160px' }}>
          {shareOfMentions.map((s, i) => (
            <div key={s.entity} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
              <LegendDot color={ENTITY_COLORS[i % ENTITY_COLORS.length]} label={`${s.entity}${s.is_primary ? ' (you)' : ''}`} />
              <span className="lite-mono" style={{ fontWeight: 700 }}>{formatScore(s.share_pct)}% · {s.mentions}</span>
            </div>
          ))}
        </div>
      </div>
      {payoff && (
        <div className="lite-body" style={{ marginTop: 14, fontWeight: 600 }}>{payoff}</div>
      )}
    </div>
  )
}

// ─── Stage 21 (V1): comparative charts restored as real components ──────
// The originally-approved treatments (comparative horizontal bars +
// donut) that Stage 19 regressed to a muted text list while it was
// busy re-scoping mention rate as "context, not a scored panel" — that
// scoring point stands (mention rate itself isn't a v3 dimension), but
// the VISUAL treatment shouldn't have been downgraded along with it.
// n-competitor safe (2-6): sorted by rate/share descending, primary
// always tagged YOU in --accent, rivals in the slate ramp by rank.

function MentionRateBarsV3({ mentionRate }) {
  const animated = useAnimateOnMount()
  const sorted = [...(mentionRate || [])].sort((a, b) => (b.rate_pct || 0) - (a.rate_pct || 0))
  const colors = entityColors(sorted, { rivalRamp: RIVAL_SLATE_RAMP })
  return (
    <div>
      <div className="lite-label" style={{ marginBottom: 8 }}>Mention rate · of {LITE_QUERY_COUNT} answers</div>
      {sorted.map((r, i) => (
        <div
          key={r.entity}
          style={{ display: 'grid', gridTemplateColumns: '110px 1fr 84px', gap: 10, alignItems: 'center', padding: '5px 0', fontSize: 13 }}
        >
          <span style={{ fontWeight: r.is_primary ? 600 : 400, color: 'var(--text)' }}>
            {r.entity}
            {r.is_primary && (
              <span className="lite-mono" style={{ fontSize: 10, color: 'var(--accent-ink)', marginLeft: 6, fontWeight: 700 }}>YOU</span>
            )}
          </span>
          <div className="lite-bar-track" style={{ height: 9 }}>
            <div className="lite-bar-fill" style={{ width: animated ? `${r.rate_pct}%` : '0%', background: colors[i], height: 9 }} />
          </div>
          <span
            className="lite-mono"
            style={{ fontSize: 11.5, textAlign: 'right', fontWeight: r.is_primary ? 600 : 400, color: r.is_primary ? 'var(--text)' : 'var(--text-2)' }}
          >
            {formatScore(r.rate_pct)}% · {r.mentioned_queries}/{r.total_queries}
          </span>
        </div>
      ))}
    </div>
  )
}

// Legend groups everything past the top rival into "N others" (summed)
// so the card stays compact from 2 competitors up to 6 — a real rival
// name always gets its own line except when there's more than one left
// after the top one.
function groupedShareLegend(shareOfMentions) {
  const sorted = [...(shareOfMentions || [])].sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))
  const primary = sorted.find((s) => s.is_primary) || null
  const rivals = sorted.filter((s) => !s.is_primary)
  const topRival = rivals[0] || null
  const rest = rivals.slice(1)
  const restGroup = rest.length
    ? { entity: `${rest.length} other${rest.length > 1 ? 's' : ''}`, share_pct: rest.reduce((s, r) => s + (r.share_pct || 0), 0), mentions: rest.reduce((s, r) => s + (r.mentions || 0), 0) }
    : null
  return { primary, topRival, restGroup }
}

function ShareOfMentionsCardV3({ shareOfMentions, totals, scoredPoints }) {
  const payoff = getDominantRivalPayoff({ share_of_mentions: shareOfMentions, totals })
  const sorted = [...(shareOfMentions || [])].sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))
  const colors = entityColors(sorted, { rivalRamp: RIVAL_SLATE_RAMP })
  const { primary, topRival, restGroup } = groupedShareLegend(shareOfMentions)
  const legendRows = [primary, topRival, restGroup].filter(Boolean)
  const legendColors = entityColors(
    legendRows.map((r) => ({ is_primary: r === primary })),
    { rivalRamp: RIVAL_SLATE_RAMP },
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Share of mentions</div>
        {scoredPoints && <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700 }}>{scoredPoints}</span>}
      </div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
        Of every brand mention across all answers, how many were yours
      </div>
      <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
        <ShareDonut shares={sorted} colors={colors} />
        <div style={{ flex: '1 1 160px' }}>
          {legendRows.map((r, i) => (
            <div key={r.entity} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
              <LegendDot color={legendColors[i]} label={r === primary ? `${r.entity} (you)` : r.entity} />
              <span className="lite-mono" style={{ fontWeight: 700 }}>{formatScore(r.share_pct)}% · {r.mentions}</span>
            </div>
          ))}
        </div>
      </div>
      {payoff && (
        <div className="lite-body" style={{ marginTop: 14, fontWeight: 600 }}>{payoff}</div>
      )}
    </div>
  )
}

// ─── Stage 21 (V2): recommendation-strength band gauge ──────────────────
// Points + a single fill gauge + one plain-language line — the raw
// rsi_score and its -1..+3 scale never reach the visitor (bug fix 2:
// score_recommendation_strength's own evidence is now the banded plain-
// language line itself, not a second client-side template of it).
// Fixed, illustrative constants — never derived from report data (G2).
// A blurred REAL number in the DOM would be a leak, not a gate; these
// are the only values this card ever renders. Report redesign (Part 6,
// G2): the per-bar labels are redacted glyph blocks, never the real
// purchase-stage names — a grep test asserts none of QUERY_STAGES'
// values ever appear in this component's rendered output.
const DECORATIVE_BAR_HEIGHT_PCT = [62, 41, 27, 14]
const DECORATIVE_REDACTED_GLYPHS = ['▮▮▮▮', '▮▮▮', '▮▮▮▮▮', '▮▮▮']

function FunnelTeaserCard({ ctaUrl }) {
  return (
    <div style={{ marginTop: 28 }}>
      <div style={{ marginBottom: 16 }}>
        <div className="lite-headline" style={{ fontSize: 16, marginBottom: 4 }}>Where you disappear in the funnel</div>
        <div className="lite-body lite-muted" style={{ fontSize: 13 }}>Stage-by-stage mention rates, from awareness to ready-to-buy.</div>
      </div>

      <div className="lite-funnel-decor" aria-hidden="true" style={{ marginBottom: 20, filter: 'blur(5px)', opacity: 0.55, pointerEvents: 'none' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {DECORATIVE_BAR_HEIGHT_PCT.map((heightPct, i) => (
            <div key={i} style={{ flex: 1 }}>
              <div style={{ height: 56, background: 'var(--track)', borderRadius: 4, display: 'flex', alignItems: 'flex-end', overflow: 'hidden' }}>
                <div style={{ width: '100%', height: `${heightPct}%`, background: 'var(--foundation)' }} />
              </div>
              <div className="lite-mono" style={{ fontSize: 9, textAlign: 'center', marginTop: 4, color: 'var(--text-2)' }}>
                {DECORATIVE_REDACTED_GLYPHS[i]}
              </div>
            </div>
          ))}
        </div>
      </div>
      <FullDiagnosticGate
        ctaUrl={ctaUrl}
        message="See which stage you vanish from — measured stage by stage in the full diagnostic."
      />
    </div>
  )
}

// ─── Incentive citation rate (Stage 8 — full-width, between the donut
// and the funnel teaser) ────────────────────────────────────────────
// Powered entirely by the existing, unmodified deal_cited ->
// deal_citation_rate pipeline (H1: the instrument is frozen this
// stage) — this card only renders it.

// Reasons emitted by lite_crosswalk.py::link_incentive_citation — used
// to find which scan dimension (if any) the crosswalk linked, so the
// header chip is always sourced from crosswalk data, never hard-coded.
const INCENTIVE_LINKED_REASONS = new Set(['value never cited', 'value rarely cited'])

function findIncentiveCitationChip(scan) {
  const dim = (scan?.dimensions || []).find((d) => d.linked && INCENTIVE_LINKED_REASONS.has(d.linked.reason))
  if (!dim) return null
  return `LINKED · ${dim.code} ${dim.name.toUpperCase()} ${formatScore(dim.score)}/${dim.max}`
}

function IncentiveCitationRow({ entity, mentionRateEntry, color }) {
  const hasMentions = entity.mentions > 0
  const isZeroPrimary = entity.is_primary && entity.rate_pct === 0
  const totalQueries = mentionRateEntry?.total_queries ?? LITE_QUERY_COUNT
  const mentionRateWidth = mentionRateEntry?.rate_pct ?? 0
  const citedWidth = hasMentions ? ((entity.cited_answers || 0) / totalQueries) * 100 : 0
  const animated = useAnimateOnMount()

  const label = hasMentions
    ? `${formatScore(entity.rate_pct)}% · ${entity.cited_answers} of ${entity.mentions} mentions`
    : '— · no mentions'
  const ariaLabel = hasMentions
    ? `${entity.entity}: ${entity.mentions} mentions, ${entity.cited_answers} of those cited a live, actionable incentive`
    : `${entity.entity}: no mentions, incentive citation rate not applicable`

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
        <span style={{ color: isZeroPrimary ? 'var(--bad-ink)' : 'var(--text)' }}>
          {entity.entity}{entity.is_primary ? ' (you)' : ''}
        </span>
        <span className="lite-mono" style={{ fontWeight: 700, color: isZeroPrimary ? 'var(--bad-ink)' : 'var(--text)' }}>
          {label}
        </span>
      </div>
      <div
        role="img"
        aria-label={ariaLabel}
        style={{ position: 'relative', height: 8, borderRadius: 4, overflow: 'hidden', background: 'var(--track)' }}
      >
        {hasMentions && (
          <>
            <div style={{ position: 'absolute', inset: 0, width: `${mentionRateWidth}%`, background: 'var(--track-darker)' }} />
            <div
              style={{
                position: 'absolute', top: 0, left: 0, bottom: 0,
                width: animated ? `${citedWidth}%` : '0%',
                background: isZeroPrimary ? 'var(--bad)' : color,
                transition: 'width 0.8s ease',
              }}
            />
            {isZeroPrimary && (
              <span
                aria-hidden="true"
                style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 2, background: 'var(--bad)' }}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function IncentiveCitationCard({ mentionRate, incentiveCitation, scan }) {
  if (!incentiveCitation || incentiveCitation.length === 0) return null

  const chipText = findIncentiveCitationChip(scan)
  const payoff = getIncentiveCitationPayoff(incentiveCitation)
  const mentionRateByEntity = {}
  ;(mentionRate || []).forEach((r) => { mentionRateByEntity[r.entity] = r })

  return (
    <div style={{ marginTop: 28, paddingTop: 28, borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Incentive citation rate</div>
        {chipText && <Chip tone="accent">{chipText}</Chip>}
      </div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 18 }}>
        When an answer names the brand, how often it also cites a live, actionable deal or member offer
      </div>

      {incentiveCitation.map((entity, i) => (
        <IncentiveCitationRow
          key={entity.entity}
          entity={entity}
          mentionRateEntry={mentionRateByEntity[entity.entity]}
          color={ENTITY_COLORS[i % ENTITY_COLORS.length]}
        />
      ))}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <LegendDot color="var(--track-darker)" label="Mentioned" />
          <LegendDot color={ENTITY_COLORS[0]} label="With an incentive cited" />
        </div>
        {payoff && (
          <div className="lite-body" style={{ fontWeight: 600, textAlign: 'right', maxWidth: 360 }}>{payoff}</div>
        )}
      </div>
    </div>
  )
}

// Stage 13 (W4): solo runs (no competitors at all — competitor_source
// 'none') never show a fake 100%-share donut or a single-entity
// incentive-citation "comparison" — both collapse into this one quiet
// note instead. Mention rate still renders (primary-only) above it.
function SoloComparisonNote() {
  return (
    <div className="lite-body lite-muted" style={{ marginTop: 16 }}>
      Competitor comparison unavailable for this run.
    </div>
  )
}

// Stage 13 (W5): the tool now CHOOSES which brands it publicly compares
// you against when competitor_source is 'generated'/'mixed' — this
// provenance line is non-negotiable wherever that comparison appears.
function CompetitorProvenanceNote() {
  return (
    <div className="lite-mono lite-muted" style={{ fontSize: 11, marginTop: 8, marginBottom: 4 }}>
      Competitors auto-selected by ChatGPT
    </div>
  )
}

function VisibilitySection({ report, ctaUrl }) {
  const vb = report.visibility_breakdown
  const isSolo = report.competitor_source === 'none'
  const isAutoSelected = report.competitor_source === 'generated' || report.competitor_source === 'mixed'
  const isV3 = isV3Report(report)
  const rsiDim = isV3 ? dimByCode(report.pillars.visibility.dimensions, 'recommendation_strength') : null
  const somDim = isV3 ? dimByCode(report.pillars.visibility.dimensions, 'share_of_mentions') : null
  const somScoredPoints = somDim ? `${formatScore(somDim.earned)}/${formatScore(somDim.max)} pts` : null
  const accordion = useSingleOpenAccordion()

  return (
    <LightCard id="viz">
      <SectionHeader
        label={`VISIBILITY · ${LITE_QUERY_COUNT} QUERIES · CHATGPT`}
        annotation={formatDateStamp()}
        headline="How often agents mention you — and your value"
      />
      {isAutoSelected && <CompetitorProvenanceNote />}
      {vb ? (
        isV3 ? (
          <div style={{ marginTop: 20 }}>
            {isSolo ? (
              <>
                <MentionRateBarsV3 mentionRate={vb.mention_rate} />
                <SoloComparisonNote />
              </>
            ) : (
              <div className="lite-cols-2">
                <MentionRateBarsV3 mentionRate={vb.mention_rate} />
                <ShareOfMentionsCardV3
                  shareOfMentions={vb.share_of_mentions} totals={vb.totals}
                  scoredPoints={somScoredPoints}
                />
              </div>
            )}
            {somDim && (
              <DimensionRowV4
                dimension={somDim} open={accordion.openCode === somDim.code}
                onToggleOpen={() => accordion.toggle(somDim.code)}
              />
            )}
            {rsiDim && (
              <DimensionRowV4
                dimension={rsiDim} open={accordion.openCode === rsiDim.code}
                onToggleOpen={() => accordion.toggle(rsiDim.code)}
              />
            )}
          </div>
        ) : isSolo ? (
          <div style={{ marginTop: 20 }}>
            <MentionRateCard mentionRate={vb.mention_rate} />
            <SoloComparisonNote />
          </div>
        ) : (
          <div className="lite-cols-2" style={{ marginTop: 20 }}>
            <MentionRateCard mentionRate={vb.mention_rate} />
            <ShareOfMentionsCard shareOfMentions={vb.share_of_mentions} totals={vb.totals} />
          </div>
        )
      ) : (
        <div className="lite-body lite-muted" style={{ marginTop: 20 }}>
          Visibility data isn't available for this report yet.
        </div>
      )}
      {!isSolo && !isV3 && (
        <IncentiveCitationCard
          mentionRate={vb?.mention_rate}
          incentiveCitation={vb?.incentive_citation}
          scan={report.scan}
        />
      )}
      <FunnelTeaserCard ctaUrl={ctaUrl} />
    </LightCard>
  )
}

// ─── Stage 21 (T), restyled Report redesign Part 4: True Value card ────
// price_truth/member_value/deal_citability's mirrored seen/said bars and
// value_protocols' single site-only row now render via the shared
// DimensionRowV4 (see TrueValueSection below) — this card's own
// aggregate quadrant verdict/footer payoff/fix pointer are unchanged.

const TRUE_VALUE_CODES = ['price_truth', 'member_value', 'deal_citability', 'value_protocols']

// Working / distribution gap / encoding gap / cited-from-elsewhere —
// generic seen-vs-said quadrant classifier: earned/max ratio (payload-
// derived, never a fixed point threshold, so it holds under a registry
// weight change) decides which quadrant applies. Used both at the
// PILLAR-aggregate level (T3's verdict chip) and, previously, row-level
// (Deal Citability) — same thresholds/verdict names either way, one
// definition.
const SEEN_SAID_QUADRANT_COPY = {
  working: 'Encoded and cited — this is working.',
  distribution_gap: 'Encoded, but agents rarely cite it — a distribution gap, not an encoding gap.',
  encoding_gap: "Little encoded to cite, and agents aren't citing it.",
  cited_elsewhere: 'Agents cite value despite little encoded on the page — likely sourced from elsewhere.',
}
const QUADRANT_LABEL = {
  working: 'WORKING',
  distribution_gap: 'DISTRIBUTION GAP',
  encoding_gap: 'ENCODING GAP',
  cited_elsewhere: 'CITED ELSEWHERE',
}

function classifySeenSaidQuadrant(seen, said) {
  const seenHigh = seen && seen.max > 0 && seen.earned / seen.max >= 0.5
  const saidHigh = said && said.max > 0 && said.earned / said.max >= 0.5
  if (seenHigh && saidHigh) return 'working'
  if (seenHigh && !saidHigh) return 'distribution_gap'
  if (!seenHigh && saidHigh) return 'cited_elsewhere'
  return 'encoding_gap'
}

// Aggregate seen/said totals across the True Value pillar's dimensions —
// member_value is excluded entirely when na (nothing to aggregate, same
// exclusion the pillar's own earned/max total already applies), and a
// guard-na said sub-lens contributes nothing to the said side (an
// unmeasured outcome isn't a zero one).
function trueValueAggregateSeenSaid(dimensions) {
  const totals = { seen: { earned: 0, max: 0 }, said: { earned: 0, max: 0 } }
  dimensions.forEach((d) => {
    if (d.na) return
    if (d.seen) { totals.seen.earned += d.seen.earned; totals.seen.max += d.seen.max }
    if (d.said && !d.said.na) { totals.said.earned += d.said.earned; totals.said.max += d.said.max }
  })
  return totals
}

// Stage 8 (W5) discipline, applied at the pillar level (T3): the first-
// mover sentence only when EVERY competitor's value-citation signal is
// zero/undefined; otherwise name the leading rival's edge — never both,
// never neither.
function trueValueFooterPayoff(report) {
  const incentiveCitation = report.visibility_breakdown?.incentive_citation || []
  const rivalRates = incentiveCitation.filter((e) => !e.is_primary && e.rate_pct !== null && e.rate_pct !== undefined)
  const topRival = [...rivalRates].sort((a, b) => b.rate_pct - a.rate_pct)[0]
  if (!topRival || topRival.rate_pct === 0) {
    return 'No rival cites value either — the first mover in this set takes the whole lane.'
  }
  return `${topRival.entity} cites value in ${Math.round(topRival.rate_pct)}% of mentions — the pace to beat.`
}

// T4: computed from the SAME visible-fixes list the Fixes section
// itself renders (report.pillars.fixes.visible — Part 3), never a
// hard-coded "01-03" — only ranks that are ACTUALLY shown there (top 2,
// since Part 3) and True-Value-coded appear. Reading the same server-
// computed list FixListV3 renders (rather than re-deriving locked/
// unlocked from pillars.*.dimensions, which still uses the older top-3
// threshold kept only for rule-6 back-compat) keeps this pointer from
// citing a fix rank the visitor can no longer actually see.
function trueValueFixPointer(report) {
  const visible = report.pillars.fixes?.visible || []
  const matchingRanks = visible
    .map((entry, i) => ({ code: entry.code, rank: i + 1 }))
    .filter((d) => TRUE_VALUE_CODES.includes(d.code))
  if (matchingRanks.length === 0) return null
  const label = matchingRanks.map((d) => String(d.rank).padStart(2, '0')).join(', ')
  return `${matchingRanks.length > 1 ? 'FIXES' : 'FIX'} ${label} TARGET THIS PILLAR ↓`
}

// Report redesign (Part 4, T2): the probe's verbatim answer is the
// dimension's own evidence[0], formatted "probe: '...'" by lite_pillars.
// py — extracted here rather than re-shaped server-side, since this is
// purely a display concern (M2: the raw quote lives only inside the
// WHY panel).
function extractProbeQuote(evidence) {
  const match = (evidence || [])[0]?.match(/^probe: '(.*)'$/)
  return match ? match[1] : null
}

// Report redesign (Part 4, T2): the decision sentence's numbers are
// registry-derived, never hard-coded — a future weight change moves
// both the "these N points" and "remaining M" figures automatically.
// Report redesign (Part 4): the row's one-line evidence summary for a
// dual-lens dimension — the said outcome's own evidence line (the more
// informative half — "1 deal cited when shoppers were ready to buy"),
// falling back to the seen line only when said itself has nothing (an
// N/A said sub-lens reads as an honest "not enough mentions," never a
// fabricated 0%). value_protocols has no said half at all, so its row
// summary is always its seen evidence.
function trueValueRowSummary(dimension) {
  if (!dimension.said) return dimension.seen?.evidence?.[0] || null
  if (dimension.said.na) return 'not enough mentions to measure'
  return dimension.said.evidence?.[0] || dimension.seen?.evidence?.[0] || null
}

function memberValueNaDecision() {
  const weight = DIMENSIONS_BY_CODE.member_value.weight
  const applicable = TOTAL_MAX - weight
  return `Neither the site crawl nor a direct model check found a program — so these ${weight} points are skipped and your score is calculated on the remaining ${applicable}.`
}

// Report redesign (Part 4, T4): the gate strip renders the RUN'S ACTUAL
// numbers against the registry's own verdict thresholds (soa_shared.
// scan_dimensions.compute_verdict) — never a restatement of the pass/
// fail chip, always the arithmetic that produced it.
function VerdictGateStrip({ pillars }) {
  const tv = pillarEarnedMax(pillars.true_value)
  const tvPct = tv.max ? (tv.earned / tv.max) * 100 : 0
  const isReady = pillars.verdict === VERDICT_AGENT_READY
  return (
    <div className={`lite-v4-gate${isReady ? ' lite-v4-gate--positive' : ''}`}>
      <b>{isReady ? 'Why agent-ready:' : 'Why not agent-ready:'}</b>{' '}
      readiness needs a score of {VERDICT_COMPOSITE_THRESHOLD}+ AND True Value above{' '}
      {Math.round(VERDICT_TRUE_VALUE_RATIO_THRESHOLD * 100)}% of its applicable points.
      You're at {formatScore(pillars.composite)} — and True Value is at {Math.round(tvPct)}%.
    </div>
  )
}

function TrueValueSection({ report }) {
  const trueValue = report.pillars?.true_value
  const accordion = useSingleOpenAccordion()
  if (!trueValue) return null
  const { seen, said } = trueValueAggregateSeenSaid(trueValue.dimensions)
  const quadrant = classifySeenSaidQuadrant(seen, said)
  const footerPayoff = trueValueFooterPayoff(report)
  const fixPointer = trueValueFixPointer(report)
  const tv = pillarEarnedMax(trueValue)

  return (
    <DarkCard id="tv" style={{ background: 'var(--accent)' }} className="lite-v4-tv">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 8 }}>
        <div>
          {/* Stage 18 finding, reused: white is the AA ceiling on
              --accent — no dimmer inverse-text token clears 4.5:1 here,
              so both lines stay full white, differentiated by size only
              (never SectionHeader's inv mode, which uses --text-inv-2). */}
          <div className="lite-mono" style={{ fontSize: 10.5, letterSpacing: '0.12em', color: '#fff', textTransform: 'uppercase' }}>
            {PILLAR_NAMES[PILLAR_TRUE_VALUE]} · {formatScore(tv.earned)}/{formatScore(pillarNominalWeight(PILLAR_TRUE_VALUE))} · only we score this
          </div>
          <div className="lite-headline" style={{ color: '#fff', marginTop: 2 }}>The value only we score</div>
        </div>
        <span
          className="lite-mono"
          style={{ background: '#fff', color: 'var(--bad)', fontSize: 10, letterSpacing: '0.1em', fontWeight: 700, padding: '4px 12px', borderRadius: 999 }}
        >
          VERDICT · {QUADRANT_LABEL[quadrant]}
        </span>
      </div>

      {trueValue.dimensions.map((d) => (
        d.code === 'member_value' && d.na ? (
          <DimensionRowV4
            key={d.code} dimension={d}
            evOverride="NOT APPLICABLE · no loyalty program found"
            naDecision={memberValueNaDecision()}
            naQuote={extractProbeQuote(d.evidence)}
            open={accordion.openCode === d.code} onToggleOpen={() => accordion.toggle(d.code)}
          />
        ) : (
          <DimensionRowV4
            key={d.code} dimension={d} siteOnly={d.code === 'value_protocols'}
            evOverride={trueValueRowSummary(d)}
            open={accordion.openCode === d.code} onToggleOpen={() => accordion.toggle(d.code)}
          />
        )
      ))}

      <VerdictGateStrip pillars={report.pillars} />

      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.25)', display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', fontSize: 12.5, color: '#fff' }}>
        <span><strong>{SEEN_SAID_QUADRANT_COPY[quadrant]}</strong> {footerPayoff}</span>
        {fixPointer && <span className="lite-mono" style={{ fontSize: 10, letterSpacing: '0.08em' }}>{fixPointer}</span>}
      </div>
    </DarkCard>
  )
}

// ─── Evidence gallery (speculative field, hidden when absent) ──────────
// V6: per-quote stage tags ("Q7 · COMPARISON STAGE") stay here on purpose.
// A single verbatim quote's stage is evidence for that one answer, not
// the stage-rate ANALYSIS (aggregated mention rates across the funnel)
// that Stage 7 moved behind the paid gate — see FunnelTeaserCard below.
// Never add stage tags anywhere beyond these existing up-to-3 free quotes.

function annotationTone(annotation) {
  const a = (annotation || '').toLowerCase()
  if (/omit|invisible|never|absent|missing/.test(a)) return 'bad'
  if (/quote|partial|list price|described/.test(a)) return 'warn'
  return 'accent'
}

function EvidenceGallery({ examples }) {
  if (!examples || examples.length === 0) return null
  return (
    <LightCard>
      <SectionHeader label="EVIDENCE" headline="What agents actually said" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {examples.map((ex, i) => (
          <div key={i}>
            {ex.annotation && (
              <div style={{ marginBottom: 8 }}>
                <Chip tone={annotationTone(ex.annotation)}>{ex.annotation}</Chip>
              </div>
            )}
            {ex.excerpt && <div style={{ fontSize: 16, lineHeight: 1.6, color: 'var(--text)', marginBottom: 6 }}>"{ex.excerpt}"</div>}
            {(ex.platform || ex.stage) && (
              <div className="lite-mono lite-muted" style={{ fontSize: 11 }}>
                {[ex.platform, ex.stage && `${ex.stage} stage`].filter(Boolean).join(' · ').toUpperCase()}
              </div>
            )}
          </div>
        ))}
      </div>
    </LightCard>
  )
}

// ─── Why section: all 8 scan dimensions, grouped Foundation/Value ──────

function AddStoreUrlPrompt({ onAddStoreUrl }) {
  return (
    <div style={{
      background: 'var(--paper)', border: `1px dashed var(--line)`, borderRadius: 12,
      padding: 24, textAlign: 'center',
    }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
        Add your store URL to see why
      </div>
      <div className="lite-body lite-muted" style={{ marginBottom: 16, maxWidth: 420, marginLeft: 'auto', marginRight: 'auto' }}>
        We can only score how an AI shopping agent reads your storefront with
        a URL to read. Run a fresh diagnostic with your store URL included to
        unlock the full breakdown.
      </div>
      {onAddStoreUrl && (
        <button onClick={onAddStoreUrl} className="lite-pill lite-pill--solid">Add store URL</button>
      )}
    </div>
  )
}

function ScanDegradedExplanation({ status }) {
  const message = status === 'blocked'
    ? "Your store blocked our reader — that's itself a finding. Many AI shopping agents will hit the same wall."
    : "We couldn't finish reading your store this time. We'll try again on your next diagnostic."
  return (
    <div>
      <InfoBadge message={message} />
      <div className="lite-body" style={{ marginTop: 14 }}>
        This affects <strong>Agent Access (F1)</strong>, one of the 8 dimensions
        we score: whether an AI shopping agent can even reach your product
        pages at all — robots.txt rules, bot-detection, and sitemap
        availability all factor in. A store that's unreachable scores 0 here
        regardless of how good everything else is.
      </div>
    </div>
  )
}

// Stage 10 (W1): deferred items are never a gate — amber + working-session
// language only, no email-unlock wording anywhere near them (consistent
// with the Stage 7 funnel teaser: full analysis = the paid diagnostic).
function DeferredItemsList({ items }) {
  if (!items || items.length === 0) return null
  return (
    <div style={{ paddingLeft: 4, marginTop: 2, marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {items.map((item) => (
        <div key={item.label} className="lite-mono lite-muted" style={{ fontSize: 11, display: 'flex', gap: 6 }}>
          <span aria-hidden="true">🔒</span>
          <span>{item.label} — verified in the full analysis</span>
        </div>
      ))}
    </div>
  )
}

function DimensionRow({ dimension, sharedMax }) {
  const isNa = dimension.coverage === 'na'
  const isPartial = dimension.coverage === 'partial'
  const trackPct = sharedMax ? (dimension.max / sharedMax) * 100 : 0
  const fillPct = sharedMax ? (dimension.score / sharedMax) * 100 : 0
  const isZero = dimension.score === 0
  const barColor = dimension.code.startsWith('F') ? 'var(--foundation)' : 'var(--accent)'
  const gridlines = []
  for (let v = 0; v <= sharedMax; v += 5) gridlines.push(v)
  if (gridlines[gridlines.length - 1] !== sharedMax) gridlines.push(sharedMax)

  return (
    <div>
      <div className="lite-dim-row">
        <div className="lite-dim-label lite-mono">{dimension.code} · {dimension.name.toUpperCase()}</div>
        <div className="lite-dim-bar-cell">
          <div className="lite-dim-track" style={isNa ? { opacity: 0.35 } : undefined}>
            {!isNa && <div className="lite-dim-fill" style={{ width: `${trackPct}%` }} />}
            {!isNa && !isZero && <div className="lite-dim-fill" style={{ width: `${fillPct}%`, background: barColor }} />}
            {!isNa && isZero && <span className="lite-dim-zero-tick" aria-hidden="true" />}
            {gridlines.map((v) => (
              <span key={v} className="lite-dim-gridline" style={{ left: `${(v / sharedMax) * 100}%` }} aria-hidden="true" />
            ))}
          </div>
        </div>
        <div className="lite-dim-score-cell">
          {isNa ? (
            <span className="lite-mono lite-muted" style={{ fontSize: 12, fontWeight: 700 }}>— · NOT APPLICABLE</span>
          ) : (
            <>
              <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700, color: isZero ? 'var(--bad-ink)' : 'var(--text)' }}>
                {formatScore(dimension.score)}/{dimension.max}
              </span>
              {isPartial && (
                <span
                  className="lite-chip lite-mono"
                  style={{ border: '1px solid var(--warn)', color: 'var(--warn-ink)', background: 'transparent' }}
                >
                  Partial · full analysis
                </span>
              )}
              {dimension.linked && <Chip tone="accent">LINKED · {dimension.linked.reason.toUpperCase()}</Chip>}
            </>
          )}
        </div>
      </div>
      {isNa && dimension.evidence?.[0] && (
        <div className="lite-mono lite-muted" style={{ fontSize: 11, paddingLeft: 4, marginTop: 2, marginBottom: 8 }}>
          {dimension.evidence[0]}
        </div>
      )}
      {isPartial && <DeferredItemsList items={dimension.deferred_items} />}
    </div>
  )
}

function DimensionChart({ dimensions }) {
  const sharedMax = Math.max(...dimensions.map((d) => d.max || 0), 1)
  const axisValues = []
  for (let v = 0; v <= sharedMax; v += 5) axisValues.push(v)
  if (axisValues[axisValues.length - 1] !== sharedMax) axisValues.push(sharedMax)

  return (
    <div>
      {dimensions.map((d) => <DimensionRow key={d.code} dimension={d} sharedMax={sharedMax} />)}
      <div className="lite-dim-row" aria-hidden="true" style={{ paddingTop: 4, marginTop: 2, borderTop: '1px solid var(--line)' }}>
        <div className="lite-dim-label" />
        <div className="lite-dim-bar-cell lite-dim-axis-track">
          {axisValues.map((v) => (
            <span
              key={v}
              className="lite-mono lite-muted"
              style={{ position: 'absolute', left: `${(v / sharedMax) * 100}%`, transform: 'translateX(-50%)', fontSize: 11 }}
            >
              {v}
            </span>
          ))}
        </div>
        <div className="lite-dim-score-cell" />
      </div>
    </div>
  )
}

function DimensionFamily({ title, subtotal, max, applicableMax, dimensions }) {
  if (dimensions.length === 0) return null
  // Stage 10 (W2): "n/{applicable_max} applicable" only when this family
  // actually has a 'na' dimension — otherwise the familiar /35 · /65.
  const hasNa = dimensions.some((d) => d.coverage === 'na')
  const denominator = hasNa && applicableMax ? applicableMax : max
  const suffix = hasNa && applicableMax ? ' APPLICABLE' : ''
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="lite-label" style={{ marginBottom: 6, fontSize: 12 }}>
        {title.toUpperCase()} · {formatScore(subtotal)}/{formatScore(denominator)}{suffix}
      </div>
      <DimensionChart dimensions={dimensions} />
    </div>
  )
}

// ─── Report redesign (Part 3, M1): the shared v4 dimension row ─────────
// ONE row component reused across Visibility/Accessibility/True Value —
// name + earned/max + a one-line evidence summary + a HOW IT'S SCORED
// pill opening an inline two-cell panel. All prose beyond that one-line
// summary (probe quotes, band sentences, per-check evidence) lives ONLY
// inside the panel (M2) — row surfaces never grow a second paragraph.
// Every label/caption/chip renders from scanDimensionsRegistry.js's per-
// dimension detail fields (M3), never a literal re-wording here.
//
// checks[]/your_value/your_band/seen/said all come from report.pillars
// (lite_pillars.py, Part 1) — this component only decides HOW to draw
// them, never re-derives a score or a band from raw evidence itself.

function CheckChip({ check }) {
  const glyph = { pass: '✓', fail: '✕', na: '—', advisory: '·' }[check.state] || '—'
  return (
    <span className={`lite-v4-chip lite-mono lite-v4-chip--${check.state}`}>
      <i aria-hidden="true">{glyph}</i>{check.label}
    </span>
  )
}

function V4Meter({ fillPct, capPct, capLabel, youPct, youValueLabel }) {
  // Report redesign (Part 3): the meter's own coordinate system runs to
  // a fixed visual ceiling above the scored cap (not 0-100 directly) so
  // the cap tick reads as a real threshold partway across the bar,
  // rather than sitting at the meter's right edge — a display choice
  // only, the underlying fillPct/capPct/youPct are the real values.
  const VISUAL_CEILING = 70
  const scale = (pct) => Math.max(0, Math.min(100, (pct / VISUAL_CEILING) * 100))
  return (
    <div className="lite-v4-meter">
      <div className="lite-v4-meter-fill" style={{ width: `${scale(fillPct)}%` }} />
      <span className="lite-v4-meter-tick" style={{ left: `${scale(capPct)}%` }} aria-hidden="true" />
      <span className="lite-v4-meter-you" style={{ left: `${scale(youPct)}%` }}>YOU · {youValueLabel}</span>
      <span className="lite-v4-meter-you lite-v4-meter-you--tick" style={{ left: `${scale(capPct)}%` }}>{capLabel}</span>
    </div>
  )
}

function V4Ladder({ bands, youIndex }) {
  return (
    <div className="lite-v4-dots">
      {bands.map((band, i) => (
        <span key={band.label} className={`lite-v4-rung${i === youIndex ? ' lite-v4-rung--you' : ''}`}>
          <i>{band.label}</i>{band.value}
        </span>
      ))}
    </div>
  )
}

function V4Pips({ pips, checks }) {
  return (
    <div className="lite-v4-pips">
      {pips.map((pip, i) => {
        const ok = checks?.[i] ? checks[i].state === 'pass' : Boolean(pip.ok)
        return (
          <span key={pip.label} className={`lite-v4-pip${ok ? '' : ' lite-v4-pip--off'}`}>
            <i aria-hidden="true">{ok ? '✓' : '✕'}</i>{pip.label}
          </span>
        )
      })}
    </div>
  )
}

function V4Grid({ total, ok }) {
  return (
    <div className="lite-v4-grid4">
      {Array.from({ length: total }, (_, i) => (
        <i key={i} className={i < ok ? 'lite-v4-grid4-ok' : ''} />
      ))}
    </div>
  )
}

// Mirrored seen/said bars — True Value's dual-lens dimensions, always
// visible above the accordion (T1) using the same zero-tick convention
// as the pre-existing ButterflyWing, just restyled to the v4 card.
function V4Duo({ seen, said, leftLabel, rightLabel }) {
  const leftPct = seen.max ? Math.max(0, Math.min(100, (seen.earned / seen.max) * 100)) : 0
  const rightPct = said.max ? Math.max(0, Math.min(100, (said.earned / said.max) * 100)) : 0
  return (
    <div>
      <div className="lite-v4-duo">
        <span className="lite-v4-duo-track lite-v4-duo-track--l">
          <span className="lite-v4-duo-fill" style={{ width: `${leftPct}%` }} />
          {seen.earned === 0 && <span className="lite-v4-duo-zero" aria-hidden="true" />}
        </span>
        <span className="lite-v4-duo-mid" aria-hidden="true">⇄</span>
        <span className="lite-v4-duo-track lite-v4-duo-track--r">
          <span className="lite-v4-duo-fill" style={{ width: `${rightPct}%` }} />
          {said.earned === 0 && <span className="lite-v4-duo-zero" aria-hidden="true" />}
        </span>
      </div>
      <div className="lite-v4-duolab">
        <span>{leftLabel} · {formatScore(seen.earned)}/{formatScore(seen.max)}</span>
        <span>{rightLabel} · {said.na ? '—' : `${formatScore(said.earned)}/${formatScore(said.max)}`}</span>
      </div>
    </div>
  )
}

// The registry's one-line HOW IT'S SCORED/YOUR BAND caption — an ordered
// array of {text, bold} segments (Stage 26 convention) so the component
// never hand-assembles bold/plain copy itself.
function ScoredCaption({ segments }) {
  return (
    <span className="lite-v4-mcap">
      {(segments || []).map((seg, i) => (seg.bold ? <b key={i}>{seg.text}</b> : <span key={i}>{seg.text}</span>))}
    </span>
  )
}

// Report redesign (Part 3, M2): "open" is a controlled prop, not local
// state — the parent section owns which ONE row's panel is open (see
// useSingleOpenAccordion below), so expanding a second row's panel
// always collapses whichever one was open before it, section-wide.
function DimensionRowV4({ dimension, evOverride, siteOnly, naDecision, naQuote, open, onToggleOpen }) {
  const registryDim = DIMENSIONS_BY_CODE[dimension.code]
  if (!registryDim) return null

  const isNa = dimension.na
  const hasSplit = Boolean(dimension.seen && dimension.said)
  const panelId = `v4-meth-${dimension.code}`

  const pt = isNa ? 'N/A' : `${formatScore(dimension.earned)}/${formatScore(dimension.max)}`
  const ev = evOverride !== undefined ? evOverride : (dimension.evidence?.[0] || '')

  return (
    <div className="lite-v4-dim">
      <div className="lite-v4-dim-h">
        <span className="lite-v4-nm">{registryDim.name}</span>
        <span className="lite-v4-pt">{pt}</span>
        {siteOnly && <span className="lite-v4-sitetag">SITE ONLY</span>}
        {ev && <span className={`lite-v4-ev${isNa ? ' lite-v4-na-line' : ''}`}>{ev}</span>}
        <button
          type="button"
          className="lite-v4-how"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggleOpen}
        >
          {isNa ? 'WHY' : "HOW IT'S SCORED"}
        </button>
      </div>

      {!isNa && hasSplit && (
        <V4Duo
          seen={dimension.seen} said={dimension.said}
          leftLabel="ON YOUR SITE" rightLabel="IN ANSWERS"
        />
      )}
      {!isNa && !hasSplit && registryDim.visualKind === 'meter' && (
        <V4Meter
          fillPct={dimension.your_value ?? 0} capPct={50} capLabel="50% = ALL 25"
          youPct={dimension.your_value ?? 0} youValueLabel={`${formatScore(dimension.your_value ?? 0)}%`}
        />
      )}
      {!isNa && !hasSplit && registryDim.visualKind === 'pips' && (
        <V4Pips pips={registryDim.visualParams.pips} checks={dimension.checks} />
      )}
      {!isNa && !hasSplit && registryDim.visualKind === 'grid' && (
        <V4Grid
          total={registryDim.visualParams.total}
          ok={dimension.max ? Math.round((dimension.earned / dimension.max) * registryDim.visualParams.total) : 0}
        />
      )}

      <div id={panelId} className={`lite-v4-meth${open ? ' lite-v4-meth--open' : ''}`}>
        {isNa ? (
          <>
            <div>
              <span className="lite-v4-meth-k">HOW WE DECIDED</span>
              <span className="lite-v4-mcap">{naDecision}</span>
            </div>
            {naQuote && (
              <div>
                <span className="lite-v4-meth-k">WHAT THE MODEL SAID</span>
                <span className="lite-v4-mcap lite-mono">"{naQuote}"</span>
              </div>
            )}
          </>
        ) : (
          <>
            <div>
              <span className="lite-v4-meth-k">{dimension.checks ? 'WHAT WE CHECK · YOUR RESULT' : registryDim.leftLabel}</span>
              <div className="lite-v4-chips">
                {dimension.checks
                  ? dimension.checks.map((c) => <CheckChip key={c.code} check={c} />)
                  : registryDim.chips.map((chip) => (
                    <span key={typeof chip === 'string' ? chip : chip.label} className="lite-v4-chip lite-mono">{typeof chip === 'string' ? chip : chip.label}</span>
                  ))}
              </div>
            </div>
            <div>
              <span className="lite-v4-meth-k">{registryDim.visualKind === 'ladder' ? 'YOUR BAND' : registryDim.rightLabel}</span>
              {registryDim.visualKind === 'ladder' ? (
                <V4Ladder bands={registryDim.visualParams.bands} youIndex={dimension.your_band ?? dimension.said?.your_band} />
              ) : (
                <ScoredCaption segments={registryDim.scoredCaption} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Stage 21 (A), restyled Report redesign (Part 5): accessibility
// tiles — three tiles, the composition story lives in the hero's
// segmented bar, so this section is just "how are these three doing,"
// independently at a glance. Each tile's body is the same shared
// DimensionRowV4 used everywhere else (live pips/grid, the checks[]
// panel behind HOW IT'S SCORED) — no bespoke tone-bar rendering.

function AccessibilityTile({ dimension, open, onToggleOpen }) {
  return (
    <div style={{ background: 'var(--paper)', borderRadius: 12, padding: '4px 12px 12px' }}>
      <DimensionRowV4 dimension={dimension} open={open} onToggleOpen={onToggleOpen} />
      {dimension.linked && <Chip tone="accent">LINKED · {dimension.linked.reason.toUpperCase()}</Chip>}
    </div>
  )
}

function AccessibilityCardV3({ report }) {
  const accessibility = report.pillars?.accessibility
  const dims = (accessibility?.dimensions || []).filter((d) => !d.na)
  const accordion = useSingleOpenAccordion()
  if (dims.length === 0) return null
  const { earned, max } = pillarEarnedMax(accessibility)
  return (
    <LightCard id="acc">
      <SectionHeader
        label={`${PILLAR_NAMES[PILLAR_ACCESSIBILITY].toUpperCase()} · ${formatScore(earned)}/${formatScore(max)}`}
        headline="Agents can knock, but can't read much"
      />
      <div className="lite-acc-grid">
        {dims.map((d) => (
          <AccessibilityTile
            key={d.code} dimension={d}
            open={accordion.openCode === d.code} onToggleOpen={() => accordion.toggle(d.code)}
          />
        ))}
      </div>
    </LightCard>
  )
}

function WhySection({ report, onAddStoreUrl }) {
  const scan = report.scan
  const status = scan?.status

  if (!status || status === 'skipped') {
    return <AddStoreUrlPrompt onAddStoreUrl={onAddStoreUrl} />
  }
  if (status === 'blocked' || status === 'failed') {
    return <ScanDegradedExplanation status={status} />
  }

  const { foundation, value } = groupDimensionsByFamily(scan.dimensions)
  const v5 = (scan.dimensions || []).find((d) => d.code === 'V5')

  return (
    <div>
      {scan.integrity_capped && (
        <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
          <div>One more rule: until offers carry honest machine-readable prices, the score cannot pass 59.</div>
          {v5?.cap_basis?.length > 0 && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              {v5.cap_basis.map((line) => (
                <li key={line} className="lite-mono" style={{ fontSize: 11 }}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <DimensionFamily
        title="Foundation" subtotal={scan.foundation?.subtotal} max={scan.foundation?.max ?? 35}
        applicableMax={scan.foundation?.applicable_max} dimensions={foundation}
      />
      <DimensionFamily
        title="Value" subtotal={scan.value?.subtotal} max={scan.value?.max ?? 65}
        applicableMax={scan.value?.applicable_max} dimensions={value}
      />
    </div>
  )
}

function FamilyLegend() {
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="lite-mono lite-muted" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
        <span style={{ width: 10, height: 10, background: 'var(--foundation)', display: 'inline-block', borderRadius: 2 }} aria-hidden="true" />
        FOUNDATION
      </span>
      <span className="lite-mono lite-muted" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
        <span style={{ width: 10, height: 10, background: 'var(--accent)', display: 'inline-block', borderRadius: 2 }} aria-hidden="true" />
        VALUE
      </span>
    </div>
  )
}

// Stage 21: a v3 row no longer has a separate "why"/methodology-
// composition card — the hero's segmented bar already tells that story,
// and Accessibility now has its own dedicated section (AccessibilityCardV3)
// matching the mock's section list (no methodology/why card at all).
// This stays legacy-only (v1/v2 rows keep their exact existing layout).
function WhySectionCard({ report, onAddStoreUrl }) {
  if (isV3Report(report)) return null
  const showLegend = report.scan?.status === 'complete'
  return (
    <LightCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHeader
          label="SCORE COMPOSITION · 8 DIMENSIONS"
          headline={report.composite === null || report.composite === undefined ? 'Why' : `Where ${formatScore(report.composite)} comes from`}
        />
        {showLegend && <FamilyLegend />}
      </div>
      <WhySection report={report} onAddStoreUrl={onAddStoreUrl} />
    </LightCard>
  )
}

// ─── Combined diagnosis (speculative — omitted unless report.diagnosis exists) ──

function DiagnosisCard({ diagnosis }) {
  if (!diagnosis) return null
  return (
    <DarkCard>
      <div className="lite-cols-2">
        <div>
          {diagnosis.crawlSummary && (
            <div className="lite-label lite-label--inv" style={{ marginBottom: 12 }}>{diagnosis.crawlSummary}</div>
          )}
          <div className="lite-headline lite-headline--inv lite-headline--hero">{diagnosis.headline}</div>
        </div>
        <div>
          <div className="lite-label lite-label--inv" style={{ marginBottom: 12 }}>Diagnosis</div>
          <div className="lite-body--inv" style={{ marginBottom: 16 }}>{diagnosis.body}</div>
          {diagnosis.startHere && (
            <div className="lite-callout">
              <div style={{ color: 'var(--text-inv)', fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Start here</div>
              <div className="lite-body--inv">{diagnosis.startHere.body}</div>
            </div>
          )}
        </div>
      </div>
    </DarkCard>
  )
}

// ─── Ranked fixes ─────────────────────────────────────────────────────
// Part 3/5: v3 reports read the server-computed, plain-language-only
// report.pillars.fixes (top 2 free, rest a bare count — see
// lite_pillars.py::_build_fixes_section) instead of re-deriving ranking
// client-side from pillars.*.dimensions, which is how ranks 3+ genuinely
// never reach this component at all, not just get styled as "locked".
//
// Legacy (pre-v3) reports keep their original scan.dimensions-driven
// rendering untouched below (LegacyFixRow) — those are frozen historical
// rows, same "renders exactly as it always has" precedent used
// throughout this codebase for pre-v3 data.

// A fix string sometimes carries an inline "e.g. {snippet}" clause
// (see lite_pillars.py's crawl-derived fix text) — split it so the
// snippet can collapse behind its own toggle instead of always showing
// inline. No snippet marker found -> the whole string is the title,
// nothing to collapse. Legacy-only (see module comment above).
function splitFixSnippet(fix) {
  if (!fix) return { title: '', snippet: null }
  const idx = fix.search(/[{<]/)
  if (idx === -1) return { title: fix, snippet: null }
  const title = fix.slice(0, idx).trim().replace(/,?\s*e\.g\.?:?\s*$/i, '').trim()
  const snippet = fix.slice(idx).trim()
  return { title: title || fix, snippet }
}

function LegacyFixRow({ dimension, rank, maxGap }) {
  const [snippetOpen, setSnippetOpen] = useState(false)
  const earned = dimension.score ?? dimension.earned ?? 0
  const gap = (dimension.max || 0) - earned
  const impactPct = maxGap ? Math.max(0, Math.min(100, (gap / maxGap) * 100)) : 0
  const { title, snippet } = dimension.locked ? { title: '', snippet: null } : splitFixSnippet(dimension.fix)

  return (
    <div className="lite-fix-row" style={dimension.locked ? { color: 'var(--text-2)' } : undefined}>
      <div className="lite-mono lite-muted" style={{ fontSize: 12 }}>{String(rank).padStart(2, '0')}</div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: dimension.locked ? 'var(--text-2)' : 'var(--text)' }}>
          {dimension.locked ? 'Unlocks with your email' : title || 'No issue found here.'}
        </div>
        {snippet && (
          <div style={{ marginTop: 6 }}>
            <button
              type="button"
              onClick={() => setSnippetOpen((v) => !v)}
              aria-expanded={snippetOpen}
              className="lite-mono lite-snippet-toggle"
            >
              {snippetOpen ? 'HIDE SNIPPET' : 'VIEW SNIPPET'}
            </button>
            {snippetOpen && <pre className="lite-mono lite-snippet-pre">{snippet}</pre>}
          </div>
        )}
      </div>
      <div className="lite-muted" style={{ fontSize: 13 }}>{dimension.locked ? '—' : dimension.name}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700, color: dimension.locked ? 'var(--text-2)' : 'var(--text)' }}>
          {dimension.locked ? '+?' : `+${gap}`}
        </span>
        {!dimension.locked && (
          <span className="lite-bar-track" style={{ width: 44, height: 5 }}>
            <span className="lite-bar-fill" style={{ width: `${impactPct}%`, background: 'var(--foundation)' }} />
          </span>
        )}
      </div>
      <div className="lite-mono lite-muted" style={{ fontSize: 12 }}>
        {dimension.locked ? 'Locked' : snippet ? 'Included in fix' : 'No snippet needed'}
      </div>
    </div>
  )
}

const IMPACT_COUNT_WORDS = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six']

function LegacyFixList({ report }) {
  const scan = report.scan
  if (!scan || scan.status !== 'complete') return null
  const ranked = rankDimensionsByGap(scan.dimensions)
  const maxGap = ranked.length ? (ranked[0].max || 0) - (ranked[0].score ?? ranked[0].earned ?? 0) : 0
  const unlockedCount = ranked.filter((d) => !d.locked).length

  return (
    <LightCard id="fix">
      <SectionHeader
        label="RANKED FIXES · ORDERED BY MODELED IMPACT"
        headline={fixesHeadline(ranked)}
      />
      <div className="lite-fix-table-header lite-label" style={{ fontSize: 11 }}>
        <span />
        <span>Fix</span>
        <span>Dimension</span>
        <span>Impact</span>
        <span>Snippet</span>
      </div>
      {ranked.map((d, i) => <LegacyFixRow key={d.code} dimension={d} rank={i + 1} maxGap={maxGap} />)}
      <div className="lite-body" style={{ marginTop: 16, fontWeight: 600 }}>
        Showing {unlockedCount} of {ranked.length} fixes. The rest unlock with your email below.
      </div>
    </LightCard>
  )
}

// Headline computed from the SAME ranked list the table renders — the
// unlocked rows' impacts summed, spelled out for small counts to match
// the design mock's voice ("Three moves recover up to 41 points").
// Legacy-only — see fixesHeadlineV3 below for the v3 equivalent.
function fixesHeadline(ranked) {
  const unlocked = ranked.filter((d) => !d.locked)
  const sum = unlocked.reduce((total, d) => total + ((d.max || 0) - (d.score ?? d.earned ?? 0)), 0)
  const count = unlocked.length
  const word = IMPACT_COUNT_WORDS[count] || String(count)
  return `${word} move${count === 1 ? '' : 's'} recover up to ${formatScore(sum)} points`
}

// Part 3 (F2): headline recomputed over just the visible (top 2) fixes
// — never over remaining_count, which carries no impact data at all.
function fixesHeadlineV3(visible) {
  const sum = visible.reduce((total, f) => total + (f.impact || 0), 0)
  const count = visible.length
  const word = IMPACT_COUNT_WORDS[count] || String(count)
  return `${word} move${count === 1 ? '' : 's'} recover up to ${formatScore(sum)} points`
}

function FixRow({ entry, rank, maxImpact }) {
  const impactPct = maxImpact ? Math.max(0, Math.min(100, (entry.impact / maxImpact) * 100)) : 0
  return (
    <div className="lite-fix-row lite-fix-row--v3">
      <div className="lite-mono lite-muted" style={{ fontSize: 12 }}>{String(rank).padStart(2, '0')}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{entry.fix_human}</div>
      <div className="lite-muted" style={{ fontSize: 13 }}>{entry.name}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
          +{formatScore(entry.impact)}
        </span>
        <span className="lite-bar-track" style={{ width: 44, height: 5 }}>
          <span className="lite-bar-fill" style={{ width: `${impactPct}%`, background: 'var(--foundation)' }} />
        </span>
      </div>
    </div>
  )
}

// Fixed, illustrative rows — never derived from real dimension data
// (same G2 discipline as the funnel teaser's DECORATIVE_* constants).
const DECORATIVE_FIX_ROWS = [
  { label: 'Catalog data', impactPct: 78 },
  { label: 'Deal terms', impactPct: 52 },
  { label: 'Feed presence', impactPct: 31 },
]

function DecorativeFixRows() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {DECORATIVE_FIX_ROWS.map((row) => (
        <div key={row.label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="lite-mono" style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 90 }}>{row.label}</span>
          <span className="lite-bar-track" style={{ flex: 1, height: 6 }}>
            <span className="lite-bar-fill" style={{ width: `${row.impactPct}%`, background: 'var(--foundation)' }} />
          </span>
        </div>
      ))}
    </div>
  )
}

function FixListV3({ report, ctaUrl }) {
  const fixes = report.pillars.fixes
  if (!fixes) return null
  const { visible, remaining_count: remainingCount } = fixes
  const maxImpact = visible.length ? Math.max(...visible.map((f) => f.impact || 0)) : 0

  return (
    <LightCard id="fix">
      <SectionHeader
        label="RANKED FIXES · ORDERED BY MODELED IMPACT"
        headline={fixesHeadlineV3(visible)}
      />
      {visible.length > 0 && (
        <>
          <div className="lite-fix-table-header lite-fix-table-header--v3 lite-label" style={{ fontSize: 11 }}>
            <span />
            <span>Fix</span>
            <span>Dimension</span>
            <span>Impact</span>
          </div>
          {visible.map((entry, i) => (
            <FixRow key={entry.code} entry={entry} rank={i + 1} maxImpact={maxImpact} />
          ))}
        </>
      )}
      {remainingCount > 0 && (
        <>
          <div aria-hidden="true" style={{ marginTop: 16, filter: 'blur(5px)', opacity: 0.55, pointerEvents: 'none' }}>
            <DecorativeFixRows />
          </div>
          <FullDiagnosticGate
            ctaUrl={ctaUrl}
            message="Two fixes get you started. The full ranked list — every fix, quantified and sequenced for your store — comes with a custom Full Diagnostic."
            subMessage={`${remainingCount} MORE FIX${remainingCount === 1 ? '' : 'ES'} IDENTIFIED`}
          />
        </>
      )}
    </LightCard>
  )
}

function FixList({ report, ctaUrl }) {
  return isV3Report(report) ? <FixListV3 report={report} ctaUrl={ctaUrl} /> : <LegacyFixList report={report} />
}

// ─── Exposure calculator ────────────────────────────────────────────────

function ExposureCalculator({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure }) {
  return (
    <div>
      <label className="lite-label" style={{ display: 'block', marginBottom: 8 }}>
        Annual revenue: {formatCurrency(revenue)}
      </label>
      <input
        type="range" min={REVENUE_SLIDER_MIN} max={REVENUE_SLIDER_MAX} step={10000} value={revenue}
        onChange={(e) => onRevenueChange(Number(e.target.value))}
        className="lite-slider" style={{ marginBottom: 22 }}
        aria-label="Annual revenue"
      />

      <label className="lite-label" style={{ display: 'block', marginBottom: 8 }}>
        AI-assisted share of purchases: {aiSharePct}%
      </label>
      <input
        type="range" min={0} max={100} step={1} value={aiSharePct}
        onChange={(e) => onAiShareChange(Number(e.target.value))}
        className="lite-slider" style={{ marginBottom: 26 }}
        aria-label="AI-assisted share of purchases"
      />

      <div style={{ background: 'var(--paper)', borderRadius: 12, padding: 22, textAlign: 'center' }}>
        <div className="lite-numeral lite-numeral--calc">
          {formatCurrency(exposure)}
          <span className="lite-mono lite-muted" style={{ fontSize: 14, fontWeight: 400, marginLeft: 6 }}>/ year</span>
        </div>
        <div className="lite-mono lite-muted" style={{ fontSize: 11, marginTop: 8 }}>Modeled, not measured.</div>
      </div>
    </div>
  )
}

// Stage 21 (F2): compact one-line summary by default (value + inputs
// summary + a mono "full analysis" note) — the interactive calculator
// stays exactly as it was, just collapsed behind an "Adjust" toggle
// rather than always open.
function ExposureCard({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure, isEstimated }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <LightCard id="exp">
      <SectionHeader label="EXPOSURE · MODELED, NOT MEASURED" headline="What this could be costing you" />
      {!expanded ? (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div className="lite-numeral lite-numeral--calc" style={{ marginBottom: 2 }}>
              {formatCurrency(exposure)}
              <span className="lite-mono lite-muted" style={{ fontSize: 14, fontWeight: 400, marginLeft: 6 }}>/ year</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
              {formatCurrency(revenue)} annual revenue · {aiSharePct}% AI-assisted share ·{' '}
              <button
                type="button"
                onClick={() => setExpanded(true)}
                className="lite-mono"
                style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-ink)', fontWeight: 700, cursor: 'pointer', fontSize: 12 }}
              >
                {isEstimated ? 'revenue estimated by ChatGPT · adjust' : 'adjust'}
              </button>
            </div>
          </div>
          <span className="lite-mono lite-muted" style={{ fontSize: 10, letterSpacing: '0.08em' }}>
            FULL PRICE-GAP MEASUREMENT · FULL ANALYSIS
          </span>
        </div>
      ) : (
        <>
          <ExposureCalculator
            revenue={revenue} onRevenueChange={onRevenueChange}
            aiSharePct={aiSharePct} onAiShareChange={onAiShareChange}
            exposure={exposure}
          />
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="lite-mono lite-snippet-toggle"
            style={{ marginTop: 16 }}
          >
            COLLAPSE
          </button>
        </>
      )}
    </LightCard>
  )
}

// ─── Diagnostic-tier cliff ───────────────────────────────────────────────

const PLATFORM_LABELS = ['ChatGPT', 'Gemini', 'Perplexity', 'Claude']
const HIGHLIGHT_PANELS = [
  { title: '3 more AI platforms', body: `See how Gemini, Perplexity, and Claude answer the same ${LITE_QUERY_COUNT} queries.` },
  { title: 'Full category run', body: `Hundreds of queries across your whole category, not a ${LITE_QUERY_COUNT}-query sample.` },
  { title: 'Net price accuracy', body: 'The gap between list price and true member price across your catalog.' },
]
const REMAINING_LOCKED_TOPICS = [
  'Funnel stage analysis — where you vanish, stage by stage',
  'Persona-level breakdowns', 'Trend over time', 'Retail shelf comparison',
  'Feed & protocol verification — Merchant Center, Deal Directory, ACP',
  'Price-history integrity — was-prices verified over time',
]

// Report redesign (Part 6, G4): the closing module — a block-variant
// FullDiagnosticGate replacing the old bespoke cliff card entirely.
// Heading + the 3 highlighted items are the mock's exact copy; the
// platform chips and remaining-topics line are kept as additional
// content inside the same block (the gate's content slot is free-form,
// not limited to exactly those 3 items).
function ClosingDiagnosticModule({ ctaUrl }) {
  return (
    <FullDiagnosticGate
      variant="block"
      ctaUrl={ctaUrl}
      heading={`This report is a ${LITE_QUERY_COUNT}-question sample. The full picture is bigger.`}
    >
      <div className="lite-cols-3" style={{ margin: '12px 0 16px' }}>
        {HIGHLIGHT_PANELS.map((panel) => (
          <div key={panel.title}>
            <div style={{ color: 'var(--text-inv)', fontWeight: 700, fontSize: 14, marginBottom: 6 }}>{panel.title}</div>
            <div className="lite-body--inv">{panel.body}</div>
          </div>
        ))}
      </div>
      <div style={{ marginBottom: 16 }}>
        <div className="lite-label lite-label--inv" style={{ marginBottom: 10 }}>Live agent answers across</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {PLATFORM_LABELS.map((p) => <span key={p} className="lite-platform-chip">{p}</span>)}
        </div>
      </div>
      <div className="lite-mono lite-muted--inv" style={{ fontSize: 12, marginBottom: 16 }}>
        Also in the full diagnostic: {REMAINING_LOCKED_TOPICS.join(' · ')}
      </div>
      <div className="lite-body--inv" style={{ fontSize: 13, marginBottom: 16 }}>
        45 minutes with your report. We bring live agent answers for two of your categories. No integration, nothing to install.
      </div>
    </FullDiagnosticGate>
  )
}

// ─── Footer ──────────────────────────────────────────────────────────────

function Footer() {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <span className="lite-mono lite-muted" style={{ fontSize: 11 }}>
        We'll re-run this diagnostic monthly if you keep your report link.
      </span>
      <span className="lite-mono lite-muted" style={{ fontSize: 11 }}>
        {LITE_QUERY_COUNT} QUERIES · 1 PLATFORM · 1 RUN EACH · {formatDateStamp().toUpperCase()} · SAMPLE, NOT A CATEGORY STUDY
      </span>
    </div>
  )
}

// ─── Stage 21 (F3): sticky mini-nav ──────────────────────────────────────
// Additional to, not a replacement for, ReportHeaderBar (which keeps the
// existing Copy-link/scan-status affordances the mini-nav doesn't carry).
// v3-only: legacy rows have no #tv/#acc anchors to point at (TrueValueSection/
// AccessibilityCardV3 both render null for a v1/v2 report).
const MINI_NAV_ANCHORS = [
  { href: '#viz', label: 'Visibility' },
  { href: '#tv', label: 'True Value' },
  { href: '#acc', label: 'Accessibility' },
  { href: '#fix', label: 'Fixes' },
  { href: '#exp', label: 'Exposure' },
]

function MiniNav({ brandOrDomain, composite }) {
  return (
    <nav className="lite-mini-nav" aria-label="Report sections">
      <div className="lite-mini-nav-inner">
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>
          {brandOrDomain} <span className="lite-muted" style={{ fontWeight: 400 }}>· {formatScore(composite)}/100</span>
        </span>
        <div className="lite-mini-nav-pills">
          {MINI_NAV_ANCHORS.map((a) => (
            <a key={a.href} href={a.href} className="lite-mono lite-mini-nav-pill">{a.label}</a>
          ))}
        </div>
      </div>
    </nav>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────

export function LiteFullReport({ report, onAddStoreUrl, token }) {
  const entities = report.overall || []
  const ctaUrl = import.meta.env.VITE_LITE_CTA_URL

  // Part 5 (R3), annual throughout since Report redesign Part 7: seeds
  // from the revenue probe's own annual estimate (clamped to the
  // slider's range) when present; falls back to the existing static
  // default otherwise, unchanged.
  // revenueTouched flips the instant the visitor drags the slider
  // themselves — "user adjustment overrides the estimate for that
  // session" — which also drops the ESTIMATED provenance label, since
  // the value on screen is no longer the estimate.
  const [revenue, setRevenue] = useState(() => seedAnnualRevenue(report.revenue_estimate_usd) ?? DEFAULT_REVENUE)
  const [revenueTouched, setRevenueTouched] = useState(false)
  const [aiSharePct, setAiSharePct] = useState(DEFAULT_AI_SHARE_PCT)
  const exposure = computeExposure({ revenue, aiSharePct, visibility: report.visibility })
  const revenueIsEstimated = report.revenue_estimate_usd != null && !revenueTouched

  function handleRevenueChange(value) {
    setRevenueTouched(true)
    setRevenue(value)
  }

  const primaryEntity = entities.find((e) => e.role === 'primary')

  return (
    <div className="lite-root">
      <div className="lite-page">
        {isV3Report(report) && (
          <MiniNav brandOrDomain={primaryEntity?.name || 'Your brand'} composite={report.composite} />
        )}
        <div className="lite-shell" style={{ maxWidth: 720 }}>
        <ReportHeaderBar
          brandOrDomain={primaryEntity?.name || 'Your brand'}
          scannedDateLabel={formatDateStamp()}
          scanStatus={report.scan_status}
          token={token}
        />

        <ExecutiveTiles report={report} exposure={exposure} />

        <VisibilitySection report={report} ctaUrl={ctaUrl} />

        <TrueValueSection report={report} />

        <AccessibilityCardV3 report={report} />

        <EvidenceGallery examples={report.evidence_examples} />

        <WhySectionCard report={report} onAddStoreUrl={onAddStoreUrl} />

        <DiagnosisCard diagnosis={report.diagnosis} />

        <FixList report={report} ctaUrl={ctaUrl} />

        <ExposureCard
          revenue={revenue} onRevenueChange={handleRevenueChange}
          aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
          exposure={exposure}
          isEstimated={revenueIsEstimated}
        />

        <ClosingDiagnosticModule ctaUrl={ctaUrl} />

        <Footer />
        </div>
      </div>
    </div>
  )
}
