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
} from './liteDerive.js'
import {
  ENTITY_COLORS, RIVAL_SLATE_RAMP, LightCard, DarkCard, SectionHeader, ReportHeaderBar,
  InfoBadge, Chip, useAnimateOnMount, formatScore,
} from './liteTheme.jsx'
import {
  DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_ACCESSIBILITY, PILLAR_NAMES,
  PILLAR_TRUE_VALUE, PILLAR_VISIBILITY, TOTAL_MAX,
} from './landing/scanDimensionsRegistry.js'

const DEFAULT_REVENUE = 1_000_000
const DEFAULT_AI_SHARE_PCT = 20

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
// visibility/True-Value pillar ratios and member_value_na, exactly the
// three inputs a visitor's own hero numbers already show. Priority
// order matters: weak visibility overrides everything else (nothing
// else matters if agents barely know you), then the na framing (a
// different STORY than "zero" — normalized, not empty), then the
// zero/partial/full True Value bands.
const VISIBILITY_WEAK_THRESHOLD = 0.5
const TRUE_VALUE_STRONG_THRESHOLD = 0.75

function deriveHeroVerdict(pillars) {
  const vis = pillarEarnedMax(pillars.visibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const visRatio = vis.max ? vis.earned / vis.max : 0
  const tvRatio = tv.max ? tv.earned / tv.max : 0

  if (visRatio < VISIBILITY_WEAK_THRESHOLD) {
    return {
      key: 'weak_visibility',
      plain: 'Agents barely know you exist —', bold: 'most answers never mention you at all.',
      support: "Visibility comes before value — that's the first fix.",
    }
  }
  if (pillars.member_value_na) {
    return {
      key: 'tv_na',
      plain: 'Agents talk about you, and', bold: 'your value score is normalized —',
      support: `No membership program was found, so True Value is scored out of ${formatScore(tv.max)}, not 40.`,
    }
  }
  if (tv.earned === 0) {
    return {
      key: 'strong_zero_tv',
      plain: 'Agents talk about you —', bold: 'they never talk about your value.',
      support: `You hold ${formatScore(vis.earned)}/${formatScore(vis.max)} visibility points, but 0 of ${formatScore(tv.max)} True Value points.`,
    }
  }
  if (tvRatio >= TRUE_VALUE_STRONG_THRESHOLD) {
    return {
      key: 'strong_full_tv',
      plain: 'Agents talk about you —', bold: 'and they get your value right.',
      support: 'Visibility and True Value are both landing.',
    }
  }
  return {
    key: 'strong_partial_tv',
    plain: 'Agents talk about you, and', bold: 'some of your value gets through —',
    support: "But there's real room left to encode.",
  }
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
        <span>{pillars.member_value_na ? `NORMALIZED · ${formatScore(tv.max + vis.max + acc.max)} PTS APPLICABLE` : 'COMPOSITE = STRAIGHT SUM'}</span>
      </div>
    </div>
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
          <div className="lite-numeral lite-numeral--inv" style={{ fontSize: 56, lineHeight: 1, marginTop: 4 }}>
            {formatScore(report.composite)}
            <span style={{ fontSize: 18, color: 'var(--text-inv-2)', fontWeight: 400 }}>/100</span>
          </div>
          <div className="lite-body--inv" style={{ fontSize: 14, maxWidth: 320, lineHeight: 1.5, marginTop: 6 }}>
            {verdict.plain} <strong style={{ color: '#fff' }}>{verdict.bold}</strong> {verdict.support}
          </div>
        </div>
        <div style={{ background: 'var(--ink-2)', borderRadius: 12, padding: '12px 16px', textAlign: 'right' }}>
          <div style={{ fontSize: 22, fontWeight: 600, color: '#fff' }}>{formatCurrency(exposure)}</div>
          <div className="lite-mono" style={{ fontSize: 10.5, color: 'var(--text-inv-2)', letterSpacing: '0.08em' }}>
            MODELED EXPOSURE / MO
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
        How many of the 12 shopper questions named each brand at least once
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
      <div className="lite-label" style={{ marginBottom: 8 }}>Mention rate · of 12 answers</div>
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
function RecommendationStrengthGauge({ dimension }) {
  if (!dimension) return null
  const pct = dimension.max ? Math.max(0, Math.min(100, (dimension.earned / dimension.max) * 100)) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)', flexWrap: 'wrap' }}>
      <span className="lite-label" style={{ minWidth: 190 }}>
        {dimension.name} · {formatScore(dimension.earned)}/{formatScore(dimension.max)}
      </span>
      <div className="lite-bar-track" style={{ flex: '1 1 120px', position: 'relative' }}>
        <div className="lite-bar-fill" style={{ width: `${pct}%`, background: 'var(--accent)' }} />
        <span
          aria-hidden="true"
          style={{ position: 'absolute', left: `${pct}%`, top: -3, width: 2, height: 14, background: 'var(--text)', transform: 'translateX(-1px)' }}
        />
      </div>
      {dimension.evidence?.[0] && (
        <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 170 }}>{dimension.evidence[0]}</span>
      )}
    </div>
  )
}

// Fixed, illustrative constants — never derived from report data (G2).
// A blurred REAL number in the DOM would be a leak, not a gate; these
// are the only values this card ever renders.
const DECORATIVE_STAGE_LABELS = ['Awareness', 'Research', 'Comparison', 'Ready to Buy']
const DECORATIVE_BAR_HEIGHT_PCT = [62, 41, 27, 14]

function FunnelTeaserCard({ ctaUrl }) {
  return (
    <div style={{ marginTop: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <div>
          <div className="lite-headline" style={{ fontSize: 16, marginBottom: 4 }}>Where you disappear in the funnel</div>
          <div className="lite-body lite-muted" style={{ fontSize: 13 }}>Stage-by-stage mention rates, from awareness to ready-to-buy.</div>
        </div>
        <span
          className="lite-chip lite-mono"
          style={{ border: '1px solid var(--warn)', color: 'var(--warn-ink)', background: 'transparent' }}
        >
          Full analysis
        </span>
      </div>

      <div
        aria-hidden="true"
        style={{ display: 'flex', gap: 8, marginBottom: 20, filter: 'blur(3px)', opacity: 0.55, pointerEvents: 'none' }}
      >
        {DECORATIVE_STAGE_LABELS.map((label, i) => (
          <div key={label} style={{ flex: 1 }}>
            <div style={{ height: 56, background: 'var(--track)', borderRadius: 4, display: 'flex', alignItems: 'flex-end', overflow: 'hidden' }}>
              <div style={{ width: '100%', height: `${DECORATIVE_BAR_HEIGHT_PCT[i]}%`, background: 'var(--foundation)' }} />
            </div>
            <div className="lite-mono" style={{ fontSize: 9, textAlign: 'center', marginTop: 4, color: 'var(--text-2)' }}>
              {label.toUpperCase()}
            </div>
          </div>
        ))}
      </div>

      <DarkCard style={{ textAlign: 'center' }}>
        <div style={{ color: 'var(--text-inv)', fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
          See which stage you vanish from
        </div>
        <div className="lite-body--inv" style={{ marginBottom: 14, fontSize: 13 }}>
          Stage-by-stage rates are measured in the full diagnostic.
        </div>
        {ctaUrl && (
          <a href={ctaUrl} target="_blank" rel="noreferrer" className="lite-pill lite-pill--solid">
            Request a working session
          </a>
        )}
      </DarkCard>
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
  const totalQueries = mentionRateEntry?.total_queries ?? 12
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

  return (
    <LightCard id="viz">
      <SectionHeader
        label="VISIBILITY · 12 QUERIES · CHATGPT"
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
            <RecommendationStrengthGauge dimension={rsiDim} />
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

// ─── Stage 21 (T): True Value butterfly — the report's centerpiece ─────
// The three dual-lens dimensions (price_truth, member_value,
// deal_citability), each a mirrored pair of tracks meeting at a
// centered name + n/max: WHAT YOU ENCODE fills leftward from the
// center, WHAT AGENTS SAID fills rightward — both anchored AT the
// center and growing outward, so the two wings' sizes compare at a
// glance. Card is solid --accent (the "blue = ours" convention) —
// per Stage 18's contrast finding, white is the mathematical ceiling
// on this background (nothing dimmer clears AA), so hierarchy here
// comes from size/weight, never a dimmer text color.

const TRUE_VALUE_CODES = ['price_truth', 'member_value', 'deal_citability']

function ButterflyWing({ side, subLens }) {
  if (!subLens) return null
  const align = side === 'left' ? 'right' : 'left'
  if (subLens.na) {
    return (
      <div style={{ textAlign: align }}>
        <div className="lite-mono" style={{ fontSize: 12, fontWeight: 700, color: '#fff' }}>
          — · not enough mentions to measure
        </div>
      </div>
    )
  }
  const pct = subLens.max ? Math.max(0, Math.min(100, (subLens.earned / subLens.max) * 100)) : 0
  const isZero = subLens.earned === 0
  return (
    <div style={{ textAlign: align }}>
      <div style={{ position: 'relative', height: 10, borderRadius: 5, background: 'rgba(255,255,255,0.22)', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, [align === 'right' ? 'right' : 'left']: 0, height: 10, borderRadius: 5, width: `${pct}%`, background: '#fff' }} />
        {isZero && (
          <span
            aria-hidden="true"
            className="lite-butterfly-zero-tick"
            style={{ position: 'absolute', top: -2, [align === 'right' ? 'right' : 'left']: 0, width: 2, height: 14, background: 'var(--bad-on-dark)' }}
          />
        )}
      </div>
      {subLens.evidence?.[0] && (
        <div style={{ fontSize: 11, color: '#fff', marginTop: 3 }}>{subLens.evidence[0]}</div>
      )}
    </div>
  )
}

function ButterflyRow({ dimension }) {
  if (dimension.code === 'member_value' && dimension.na) {
    return (
      <div style={{ padding: '10px 0', textAlign: 'center', opacity: 0.85 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: '#fff' }}>{dimension.name}</div>
        <div className="lite-mono" style={{ fontSize: 10, fontWeight: 700, color: '#fff', marginTop: 2 }}>NOT APPLICABLE</div>
        <div style={{ fontSize: 12, color: '#fff', marginTop: 6, maxWidth: 420, marginLeft: 'auto', marginRight: 'auto' }}>
          No loyalty or membership program found — neither the site crawl nor a direct model probe located one.
        </div>
        {dimension.evidence?.[0] && (
          <div className="lite-mono" style={{ fontSize: 11, color: '#fff', marginTop: 4 }}>{dimension.evidence[0]}</div>
        )}
      </div>
    )
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 150px 1fr', gap: 10, alignItems: 'center', padding: '8px 0' }}>
      <ButterflyWing side="left" subLens={dimension.seen} />
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: '#fff' }}>{dimension.name}</div>
        <div className="lite-mono" style={{ fontSize: 10.5, color: '#fff' }}>
          {formatScore(dimension.earned)}/{formatScore(dimension.max)}
        </div>
      </div>
      <ButterflyWing side="right" subLens={dimension.said} />
    </div>
  )
}

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

// T4: computed from the SAME ranked-fix ordering the Fixes section
// itself renders (fix->dimension keys), never a hard-coded "01-03" —
// only the ranks that are (a) unlocked and (b) True-Value-coded appear.
function trueValueFixPointer(report) {
  const ranked = rankDimensionsByGap([
    ...(report.pillars.accessibility?.dimensions || []),
    ...(report.pillars.true_value?.dimensions || []),
  ])
  const matchingRanks = ranked
    .map((d, i) => ({ code: d.code, rank: i + 1, locked: d.locked }))
    .filter((d) => !d.locked && TRUE_VALUE_CODES.includes(d.code))
  if (matchingRanks.length === 0) return null
  const label = matchingRanks.map((d) => String(d.rank).padStart(2, '0')).join(', ')
  return `${matchingRanks.length > 1 ? 'FIXES' : 'FIX'} ${label} TARGET THIS PILLAR ↓`
}

function TrueValueSection({ report }) {
  const trueValue = report.pillars?.true_value
  if (!trueValue) return null
  const { seen, said } = trueValueAggregateSeenSaid(trueValue.dimensions)
  const quadrant = classifySeenSaidQuadrant(seen, said)
  const footerPayoff = trueValueFooterPayoff(report)
  const fixPointer = trueValueFixPointer(report)
  const tv = pillarEarnedMax(trueValue)

  return (
    <DarkCard id="tv" style={{ background: 'var(--accent)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 16 }}>
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 150px 1fr', gap: 10, fontFamily: 'var(--mono)', fontSize: 9.5, letterSpacing: '0.1em', color: '#fff', marginBottom: 6 }}>
        <span style={{ textAlign: 'right' }}>WHAT YOU ENCODE</span>
        <span />
        <span style={{ textAlign: 'left' }}>WHAT AGENTS SAID</span>
      </div>
      {trueValue.dimensions.map((d) => <ButterflyRow key={d.code} dimension={d} />)}

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

// ─── Stage 21 (A): accessibility tiles ──────────────────────────────────
// Three tiles replace the shared-scale dimension chart for a v3 row —
// the composition story now lives in the hero's segmented bar, so this
// section is just "how are these three doing," independently at a
// glance. good >=80%, bad at exactly 0%, warn in between — matching
// the thresholds Stage 21's mock renders (Agent Access 83% good,
// Protocol & Feed 33% warn, Catalog & Context 0% bad).
const ACCESSIBILITY_GOOD_THRESHOLD = 0.8

function accessibilityTone(earned, max) {
  if (!max || earned === 0) return 'bad'
  const ratio = earned / max
  return ratio >= ACCESSIBILITY_GOOD_THRESHOLD ? 'good' : 'warn'
}

function AccessibilityTile({ dimension }) {
  const tone = accessibilityTone(dimension.earned, dimension.max)
  const pct = dimension.max ? Math.max(0, Math.min(100, (dimension.earned / dimension.max) * 100)) : 0
  return (
    <div style={{ background: 'var(--paper)', borderRadius: 12, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>{dimension.name}</div>
        <span className="lite-mono" style={{ fontSize: 11, fontWeight: 700, color: tone === 'bad' ? 'var(--bad-ink)' : 'var(--text-2)' }}>
          {formatScore(dimension.earned)}/{formatScore(dimension.max)}
        </span>
      </div>
      <div className="lite-bar-track" style={{ marginTop: 8, height: 6 }}>
        {pct > 0 && (
          <div
            className="lite-bar-fill"
            style={{ width: `${pct}%`, height: 6, background: tone === 'good' ? 'var(--good)' : tone === 'warn' ? 'var(--warn)' : 'var(--bad)' }}
          />
        )}
      </div>
      {dimension.evidence?.[0] && (
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 5 }}>{dimension.evidence[0]}</div>
      )}
      {dimension.linked && <Chip tone="accent">LINKED · {dimension.linked.reason.toUpperCase()}</Chip>}
    </div>
  )
}

function AccessibilityCardV3({ report }) {
  const accessibility = report.pillars?.accessibility
  const dims = (accessibility?.dimensions || []).filter((d) => !d.na)
  if (dims.length === 0) return null
  const { earned, max } = pillarEarnedMax(accessibility)
  return (
    <LightCard id="acc">
      <SectionHeader
        label={`${PILLAR_NAMES[PILLAR_ACCESSIBILITY].toUpperCase()} · ${formatScore(earned)}/${formatScore(max)}`}
        headline="Agents can knock, but can't read much"
      />
      <div className="lite-acc-grid">
        {dims.map((d) => <AccessibilityTile key={d.code} dimension={d} />)}
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

// ─── Stage 21 (F1): ranked fixes ─────────────────────────────────────────

// A fix string sometimes carries an inline "e.g. {snippet}" clause
// (see lite_pillars.py's crawl-derived fix text) — split it so the
// snippet can collapse behind its own toggle instead of always showing
// inline. No snippet marker found -> the whole string is the title,
// nothing to collapse.
function splitFixSnippet(fix) {
  if (!fix) return { title: '', snippet: null }
  const idx = fix.search(/[{<]/)
  if (idx === -1) return { title: fix, snippet: null }
  const title = fix.slice(0, idx).trim().replace(/,?\s*e\.g\.?:?\s*$/i, '').trim()
  const snippet = fix.slice(idx).trim()
  return { title: title || fix, snippet }
}

function FixRow({ dimension, rank, maxGap }) {
  const [snippetOpen, setSnippetOpen] = useState(false)
  // Stage 19: dimension is either a legacy scan.dimensions row (`score`)
  // or a v3 pillars.dimensions row (`earned`) — see rankDimensionsByGap.
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

// Headline computed from the SAME ranked list the table renders — the
// unlocked rows' impacts summed, spelled out for small counts to match
// the design mock's voice ("Three moves recover up to 41 points").
function fixesHeadline(ranked) {
  const unlocked = ranked.filter((d) => !d.locked)
  const sum = unlocked.reduce((total, d) => total + ((d.max || 0) - (d.score ?? d.earned ?? 0)), 0)
  const count = unlocked.length
  const word = IMPACT_COUNT_WORDS[count] || String(count)
  return `${word} move${count === 1 ? '' : 's'} recover up to ${formatScore(sum)} points`
}

function FixList({ report }) {
  const isV3 = isV3Report(report)
  let ranked
  if (isV3) {
    // Stage 19 (R5): scan.dimensions is unusable for a v3 row (F1-V5
    // keys never match a v3-keyed dimensions dict — see
    // build_pillars_payload's docstring) — fix text and ranking come
    // from pillars instead, already computed server-side.
    ranked = rankDimensionsByGap([
      ...(report.pillars.accessibility?.dimensions || []),
      ...(report.pillars.true_value?.dimensions || []),
    ])
  } else {
    const scan = report.scan
    if (!scan || scan.status !== 'complete') return null
    ranked = rankDimensionsByGap(scan.dimensions)
  }
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
      {ranked.map((d, i) => <FixRow key={d.code} dimension={d} rank={i + 1} maxGap={maxGap} />)}
      <div className="lite-body" style={{ marginTop: 16, fontWeight: 600 }}>
        Showing {unlockedCount} of {ranked.length} fixes. The rest unlock with your email below.
      </div>
    </LightCard>
  )
}

// ─── Exposure calculator ────────────────────────────────────────────────

function ExposureCalculator({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure }) {
  return (
    <div>
      <label className="lite-label" style={{ display: 'block', marginBottom: 8 }}>
        Monthly revenue: {formatCurrency(revenue)}
      </label>
      <input
        type="range" min={10000} max={10000000} step={10000} value={revenue}
        onChange={(e) => onRevenueChange(Number(e.target.value))}
        className="lite-slider" style={{ marginBottom: 22 }}
        aria-label="Monthly revenue"
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
          <span className="lite-mono lite-muted" style={{ fontSize: 14, fontWeight: 400, marginLeft: 6 }}>/ mo</span>
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
function ExposureCard({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <LightCard id="exp">
      <SectionHeader label="EXPOSURE · MODELED, NOT MEASURED" headline="What this could be costing you" />
      {!expanded ? (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div className="lite-numeral lite-numeral--calc" style={{ marginBottom: 2 }}>
              {formatCurrency(exposure)}
              <span className="lite-mono lite-muted" style={{ fontSize: 14, fontWeight: 400, marginLeft: 6 }}>/ month</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
              {formatCurrency(revenue)} monthly revenue · {aiSharePct}% AI-assisted share ·{' '}
              <button
                type="button"
                onClick={() => setExpanded(true)}
                className="lite-mono"
                style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-ink)', fontWeight: 700, cursor: 'pointer', fontSize: 12 }}
              >
                adjust
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
  { title: '3 more AI platforms', body: 'See how Gemini, Perplexity, and Claude answer the same 12 queries.' },
  { title: 'Full category run', body: 'Hundreds of queries across your whole category, not a 12-query sample.' },
  { title: 'Net price accuracy', body: 'The gap between list price and true member price across your catalog.' },
]
const REMAINING_LOCKED_TOPICS = [
  'Funnel stage analysis — where you vanish, stage by stage',
  'Persona-level breakdowns', 'Trend over time', 'Retail shelf comparison',
  'Feed & protocol verification — Merchant Center, Deal Directory, ACP',
  'Price-history integrity — was-prices verified over time',
]

function DiagnosticCliff({ ctaUrl }) {
  return (
    <DarkCard>
      <div style={{ marginBottom: 22 }}>
        <div className="lite-label lite-label--inv" style={{ marginBottom: 10 }}>Live agent answers across</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {PLATFORM_LABELS.map((p) => <span key={p} className="lite-platform-chip">{p}</span>)}
        </div>
      </div>
      <div className="lite-cols-3" style={{ marginBottom: 20 }}>
        {HIGHLIGHT_PANELS.map((panel) => (
          <div key={panel.title}>
            <div style={{ color: 'var(--text-inv)', fontWeight: 700, fontSize: 14, marginBottom: 6 }}>{panel.title}</div>
            <div className="lite-body--inv">{panel.body}</div>
          </div>
        ))}
      </div>
      <div className="lite-mono lite-muted--inv" style={{ fontSize: 12, marginBottom: 20 }}>
        Also in the full diagnostic: {REMAINING_LOCKED_TOPICS.join(' · ')}
      </div>
      <div className="lite-divider lite-divider--inv" />
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginTop: 20 }}>
        {ctaUrl && (
          <a href={ctaUrl} target="_blank" rel="noreferrer" className="lite-pill lite-pill--solid">
            Request a working session
          </a>
        )}
        <span className="lite-body--inv" style={{ fontSize: 13 }}>
          45 minutes with your report. We bring live agent answers for two of your categories. No integration, nothing to install.
        </span>
      </div>
    </DarkCard>
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
        12 QUERIES · 1 PLATFORM · 1 RUN EACH · {formatDateStamp().toUpperCase()} · SAMPLE, NOT A CATEGORY STUDY
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
      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>
        {brandOrDomain} <span className="lite-muted" style={{ fontWeight: 400 }}>· {formatScore(composite)}/100</span>
      </span>
      <div className="lite-mini-nav-pills">
        {MINI_NAV_ANCHORS.map((a) => (
          <a key={a.href} href={a.href} className="lite-mono lite-mini-nav-pill">{a.label}</a>
        ))}
      </div>
    </nav>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────

export function LiteFullReport({ report, onAddStoreUrl, token }) {
  const entities = report.overall || []
  const ctaUrl = import.meta.env.VITE_LITE_CTA_URL

  const [revenue, setRevenue] = useState(DEFAULT_REVENUE)
  const [aiSharePct, setAiSharePct] = useState(DEFAULT_AI_SHARE_PCT)
  const exposure = computeExposure({ revenue, aiSharePct, visibility: report.visibility })

  const primaryEntity = entities.find((e) => e.role === 'primary')

  return (
    <div className="lite-root">
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

        <FixList report={report} />

        <ExposureCard
          revenue={revenue} onRevenueChange={setRevenue}
          aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
          exposure={exposure}
        />

        <DiagnosticCliff ctaUrl={ctaUrl} />

        <Footer />
      </div>
    </div>
  )
}
