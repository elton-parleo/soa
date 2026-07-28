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
  ENTITY_COLORS, LightCard, DarkCard, SectionHeader, ReportHeaderBar,
  InfoBadge, Chip, useAnimateOnMount, formatScore,
} from './liteTheme.jsx'
import {
  DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_ACCESSIBILITY, PILLAR_NAMES, PILLAR_ORDER,
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

function PillarTile({ label, earned, max, tone }) {
  const wrapperStyle = tone === 'tv'
    ? { background: 'var(--accent)', color: '#fff', borderRadius: 12, padding: '10px 16px', textAlign: 'center', minWidth: 96 }
    : { textAlign: 'center', minWidth: 96 }
  return (
    <div style={wrapperStyle}>
      <div className="lite-numeral lite-numeral--tile" style={tone === 'tv' ? { color: '#fff' } : undefined}>
        {formatScore(earned)}<span style={{ fontSize: '0.5em', fontWeight: 500 }}>/{formatScore(max)}</span>
      </div>
      <div className="lite-label" style={{ marginTop: 8, color: tone === 'tv' ? '#fff' : undefined }}>{label}</div>
    </div>
  )
}

function ExecutiveTilesV3({ report, exposure }) {
  const pillars = report.pillars
  const visibility = pillarEarnedMax(pillars.visibility)
  const accessibility = pillarEarnedMax(pillars.accessibility)
  const trueValue = pillarEarnedMax(pillars.true_value)
  // Registry-driven, computed fresh (never the cached PILLAR_WEIGHTS-
  // style export) so a perturbed member_value weight moves this caption —
  // same "no cross-version blending" precedent as compute_composite's
  // own applicable_max() (soa_shared/scan_dimensions.py).
  const applicableTotal = pillars.member_value_na
    ? TOTAL_MAX - DIMENSIONS_BY_CODE.member_value.weight
    : TOTAL_MAX

  return (
    <LightCard>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28, justifyContent: 'center', alignItems: 'center' }}>
        <PillarTile label={PILLAR_NAMES[PILLAR_VISIBILITY]} earned={visibility.earned} max={visibility.max} />
        <PillarTile label={PILLAR_NAMES[PILLAR_ACCESSIBILITY]} earned={accessibility.earned} max={accessibility.max} />
        <PillarTile label={PILLAR_NAMES[PILLAR_TRUE_VALUE]} earned={trueValue.earned} max={trueValue.max} tone="tv" />
        <div style={{ textAlign: 'center', minWidth: 96 }}>
          <div className="lite-numeral lite-numeral--tile">{formatScore(report.composite)}</div>
          <div className="lite-label" style={{ marginTop: 8 }}>Composite score</div>
          {pillars.member_value_na && (
            <div className="lite-mono lite-muted" style={{ fontSize: 10, marginTop: 4 }}>
              NORMALIZED · {formatScore(applicableTotal)} PTS APPLICABLE
            </div>
          )}
        </div>
        <Tile label="Modeled exposure/mo" value={formatCurrency(exposure)} />
      </div>
    </LightCard>
  )
}

function ExecutiveTiles({ report, exposure }) {
  if (isV3Report(report)) {
    return <ExecutiveTilesV3 report={report} exposure={exposure} />
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

function ShareDonut({ shares }) {
  const size = 116
  const strokeWidth = 16
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  let cumulativePct = 0
  const segments = shares.map((s, i) => {
    const pct = Math.max(0, Math.min(100, s.share_pct || 0))
    const dash = (pct / 100) * circumference
    const seg = {
      key: s.entity,
      color: ENTITY_COLORS[i % ENTITY_COLORS.length],
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

// Stage 19 (R3): folds the old standalone MentionRateCard's bars in as
// secondary context underneath the (now scored) Share of Mentions card,
// rather than presenting mention rate as its own scored-looking panel —
// the mention-rate metric itself isn't a v3-scored dimension.
function MentionRateContextRows({ mentionRate }) {
  if (!mentionRate || mentionRate.length === 0) return null
  const animated = useAnimateOnMount()
  return (
    <div style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
      <div className="lite-mono lite-muted" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', marginBottom: 10 }}>
        MENTION RATE
      </div>
      {mentionRate.map((r, i) => (
        <div key={r.entity} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--text-2)', marginBottom: 3 }}>
            <span>{r.entity}{r.is_primary ? ' (you)' : ''}</span>
            <span className="lite-mono">{formatScore(r.rate_pct)}% · {r.mentioned_queries}/{r.total_queries}</span>
          </div>
          <div className="lite-bar-track" style={{ height: 5 }}>
            <div
              className="lite-bar-fill"
              style={{ width: animated ? `${r.rate_pct}%` : '0%', background: ENTITY_COLORS[i % ENTITY_COLORS.length] }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function ShareOfMentionsCard({ shareOfMentions, totals, scoredPoints, mentionRate, title }) {
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
      {mentionRate && <MentionRateContextRows mentionRate={mentionRate} />}
    </div>
  )
}

// Stage 19 (R3): recommendation_strength has no bars of its own (it's a
// -1..+3 rescale, not a %-based rate) — a scored panel with its points
// in the header and the registry evidence sentence underneath.
function RecommendationStrengthCard({ dimension }) {
  if (!dimension) return null
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{dimension.name}</div>
        <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700 }}>
          {formatScore(dimension.earned)}/{formatScore(dimension.max)} pts
        </span>
      </div>
      <div className="lite-body lite-muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
        Whether agents single you out as the best pick, or just list you among others
      </div>
      {dimension.evidence?.[0] && (
        <div className="lite-body" style={{ fontSize: 13 }}>{dimension.evidence[0]}</div>
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
    <LightCard>
      <SectionHeader
        label="VISIBILITY · 12 QUERIES · CHATGPT"
        annotation={formatDateStamp()}
        headline="How often agents mention you — and your value"
      />
      {isAutoSelected && <CompetitorProvenanceNote />}
      {vb ? (
        isSolo ? (
          <div style={{ marginTop: 20 }}>
            {isV3 ? <RecommendationStrengthCard dimension={rsiDim} /> : <MentionRateCard mentionRate={vb.mention_rate} />}
            {isV3 && <MentionRateContextRows mentionRate={vb.mention_rate} />}
            <SoloComparisonNote />
          </div>
        ) : (
          <div className="lite-cols-2" style={{ marginTop: 20 }}>
            {isV3 ? <RecommendationStrengthCard dimension={rsiDim} /> : <MentionRateCard mentionRate={vb.mention_rate} />}
            <ShareOfMentionsCard
              shareOfMentions={vb.share_of_mentions} totals={vb.totals}
              scoredPoints={isV3 ? somScoredPoints : null}
              mentionRate={isV3 ? vb.mention_rate : null}
              title={somDim?.name}
            />
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

// ─── True Value section (Stage 19, R2) — the report's centerpiece ──────
// The three dual-lens dimensions (price_truth, member_value,
// deal_citability), each split into what the crawl found encoded
// ("what you encode") vs. what agents actually said back ("what agents
// said") — reusing the landing page's SEEN/SAID framing. Deal
// Citability's outcome half absorbs the old standalone incentive-
// citation card entirely (its layered-bar visual + competitor
// comparison move here; VisibilitySection no longer renders it for a
// v3 report — see VisibilitySection above).

function SubLensTile({ label, subLens }) {
  if (!subLens) return null
  return (
    <div>
      <div className="lite-mono lite-muted" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.04em' }}>{label}</div>
      {subLens.na ? (
        <div className="lite-mono lite-muted" style={{ fontSize: 13, fontWeight: 700, marginTop: 4 }}>
          — · not enough mentions to measure
        </div>
      ) : (
        <>
          <div className="lite-mono" style={{ fontSize: 15, fontWeight: 700, marginTop: 4 }}>
            {formatScore(subLens.earned)}/{formatScore(subLens.max)}
          </div>
          {subLens.evidence?.[0] && (
            <div className="lite-body lite-muted" style={{ fontSize: 11.5, marginTop: 4 }}>{subLens.evidence[0]}</div>
          )}
        </>
      )}
    </div>
  )
}

// Working / distribution gap / encoding gap / cited-from-elsewhere —
// each sub-lens's own earned/max ratio (payload-derived, not a fixed
// point threshold, so it holds up under a registry weight change)
// decides which quadrant applies. A guard-na said sub-lens has no
// outcome to classify at all — its tile above already says so.
const DEAL_CITABILITY_QUADRANT_COPY = {
  working: 'Encoded and cited — this is working.',
  distribution_gap: 'Encoded, but agents rarely cite it — a distribution gap, not an encoding gap.',
  encoding_gap: "Little encoded to cite, and agents aren't citing it.",
  cited_elsewhere: 'Agents cite a deal despite little encoded on the page — likely sourced from elsewhere.',
}

function classifyDealCitability(seen, said) {
  const seenHigh = seen && seen.max > 0 && seen.earned / seen.max >= 0.5
  const saidHigh = said && said.max > 0 && said.earned / said.max >= 0.5
  if (seenHigh && saidHigh) return 'working'
  if (seenHigh && !saidHigh) return 'distribution_gap'
  if (!seenHigh && saidHigh) return 'cited_elsewhere'
  return 'encoding_gap'
}

function DealCitabilityOutcome({ dimension, report }) {
  const { seen, said } = dimension
  const vb = report.visibility_breakdown
  const incentiveCitation = vb?.incentive_citation
  const mentionRateByEntity = {}
  ;(vb?.mention_rate || []).forEach((r) => { mentionRateByEntity[r.entity] = r })
  const verdictText = said && !said.na ? DEAL_CITABILITY_QUADRANT_COPY[classifyDealCitability(seen, said)] : null

  return (
    <div style={{ marginTop: 18, paddingTop: 18, borderTop: '1px solid var(--line)' }}>
      {verdictText && <div className="lite-body" style={{ fontWeight: 600, marginBottom: 14 }}>{verdictText}</div>}
      {incentiveCitation && incentiveCitation.length > 0 && (
        <>
          {incentiveCitation.map((entity, i) => (
            <IncentiveCitationRow
              key={entity.entity}
              entity={entity}
              mentionRateEntry={mentionRateByEntity[entity.entity]}
              color={ENTITY_COLORS[i % ENTITY_COLORS.length]}
            />
          ))}
          <div style={{ display: 'flex', gap: 16 }}>
            <LegendDot color="var(--track-darker)" label="Mentioned" />
            <LegendDot color={ENTITY_COLORS[0]} label="With an incentive cited" />
          </div>
        </>
      )}
    </div>
  )
}

function TrueValueDimensionRow({ dimension, report }) {
  if (dimension.code === 'member_value' && dimension.na) {
    return (
      <div style={{ opacity: 0.7, marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{dimension.name}</span>
          <span className="lite-mono lite-muted" style={{ fontSize: 12, fontWeight: 700 }}>NOT APPLICABLE</span>
        </div>
        <div className="lite-body lite-muted" style={{ marginTop: 6 }}>
          No loyalty or membership program found — neither the site crawl nor a direct model probe located one.
        </div>
        {dimension.evidence?.[0] && (
          <div className="lite-mono lite-muted" style={{ fontSize: 11.5, marginTop: 6 }}>{dimension.evidence[0]}</div>
        )}
      </div>
    )
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 12 }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>{dimension.name}</span>
        <span className="lite-mono" style={{ fontSize: 13, fontWeight: 700 }}>
          {formatScore(dimension.earned)}/{formatScore(dimension.max)}
        </span>
      </div>
      <div className="lite-cols-2">
        <SubLensTile label="WHAT YOU ENCODE" subLens={dimension.seen} />
        <SubLensTile label="WHAT AGENTS SAID" subLens={dimension.said} />
      </div>
      {dimension.code === 'deal_citability' && <DealCitabilityOutcome dimension={dimension} report={report} />}
    </div>
  )
}

function TrueValueSection({ report }) {
  const trueValue = report.pillars?.true_value
  if (!trueValue) return null
  return (
    <LightCard>
      <SectionHeader
        label={`${PILLAR_NAMES[PILLAR_TRUE_VALUE].toUpperCase()} · WHAT YOU ENCODE VS. WHAT AGENTS SAID`}
        headline="The value only we score"
      />
      {trueValue.dimensions.map((d) => (
        <TrueValueDimensionRow key={d.code} dimension={d} report={report} />
      ))}
    </LightCard>
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

// ─── v3 accessibility section + methodology explainer (Stage 19, R4) ──
// True Value's own three dimensions now live in the dedicated section
// above (TrueValueSection) — this "why" chart only carries accessibility
// going forward for a v3 row.

function DimensionRowV3({ dimension, sharedMax }) {
  const isNa = dimension.na
  const trackPct = sharedMax ? (dimension.max / sharedMax) * 100 : 0
  const fillPct = sharedMax ? (dimension.earned / sharedMax) * 100 : 0
  const isZero = dimension.earned === 0
  const gridlines = []
  for (let v = 0; v <= sharedMax; v += 5) gridlines.push(v)
  if (gridlines[gridlines.length - 1] !== sharedMax) gridlines.push(sharedMax)

  return (
    <div>
      <div className="lite-dim-row">
        <div className="lite-dim-label lite-mono">{dimension.name.toUpperCase()}</div>
        <div className="lite-dim-bar-cell">
          <div className="lite-dim-track" style={isNa ? { opacity: 0.35 } : undefined}>
            {!isNa && <div className="lite-dim-fill" style={{ width: `${trackPct}%` }} />}
            {!isNa && !isZero && <div className="lite-dim-fill" style={{ width: `${fillPct}%`, background: 'var(--accent)' }} />}
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
                {formatScore(dimension.earned)}/{dimension.max}
              </span>
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
    </div>
  )
}

function DimensionChartV3({ dimensions }) {
  const sharedMax = Math.max(...dimensions.map((d) => d.max || 0), 1)
  const axisValues = []
  for (let v = 0; v <= sharedMax; v += 5) axisValues.push(v)
  if (axisValues[axisValues.length - 1] !== sharedMax) axisValues.push(sharedMax)

  return (
    <div>
      {dimensions.map((d) => <DimensionRowV3 key={d.code} dimension={d} sharedMax={sharedMax} />)}
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

function AccessibilitySectionV3({ accessibility }) {
  const dims = accessibility?.dimensions || []
  if (dims.length === 0) return null
  const { earned, max } = pillarEarnedMax(accessibility)
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="lite-label" style={{ marginBottom: 6, fontSize: 12 }}>
        {PILLAR_NAMES[PILLAR_ACCESSIBILITY].toUpperCase()} · {formatScore(earned)}/{formatScore(max)}
      </div>
      <DimensionChartV3 dimensions={dims} />
    </div>
  )
}

function WhySectionV3({ report }) {
  return (
    <div>
      <AccessibilitySectionV3 accessibility={report.pillars.accessibility} />
      <div className="lite-body lite-muted" style={{ fontSize: 12.5 }}>
        Price Truth, Member Value, and Deal Citability have their own section above — see "The value only we score."
      </div>
    </div>
  )
}

// Three-pillar totals, computed live from the registry's own per-
// dimension weights (never a cached export) so a perturbed weight moves
// this line — composite is their straight sum, no separate blend.
function MethodologyLegend() {
  const totals = PILLAR_ORDER.map((pillar) => ({
    pillar,
    total: DIMENSIONS.filter((d) => d.pillar === pillar).reduce((sum, d) => sum + d.weight, 0),
  }))
  const grandTotal = totals.reduce((sum, t) => sum + t.total, 0)
  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
      {totals.map(({ pillar, total }) => (
        <span key={pillar} className="lite-mono lite-muted" style={{ fontSize: 11 }}>
          {PILLAR_NAMES[pillar].toUpperCase()} {total}
        </span>
      ))}
      <span className="lite-mono" style={{ fontSize: 11, fontWeight: 700 }}>= {grandTotal}</span>
    </div>
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

function WhySectionCard({ report, onAddStoreUrl }) {
  const status = report.scan?.status
  const showLegend = status === 'complete'
  const isV3 = isV3Report(report)
  return (
    <LightCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHeader
          label={isV3 ? 'SCORE COMPOSITION · 3 PILLARS' : 'SCORE COMPOSITION · 8 DIMENSIONS'}
          headline={report.composite === null || report.composite === undefined ? 'Why' : `Where ${formatScore(report.composite)} comes from`}
        />
        {showLegend && (isV3 ? <MethodologyLegend /> : <FamilyLegend />)}
      </div>
      {isV3 ? <WhySectionV3 report={report} /> : <WhySection report={report} onAddStoreUrl={onAddStoreUrl} />}
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

// ─── Ranked fixes ────────────────────────────────────────────────────────

function FixRow({ dimension, rank, maxGap }) {
  // Stage 19: dimension is either a legacy scan.dimensions row (`score`)
  // or a v3 pillars.dimensions row (`earned`) — see rankDimensionsByGap.
  const earned = dimension.score ?? dimension.earned ?? 0
  const gap = (dimension.max || 0) - earned
  const impactPct = maxGap ? Math.max(0, Math.min(100, (gap / maxGap) * 100)) : 0
  const hasSnippet = !dimension.locked && /[{<]/.test(dimension.fix || '')

  return (
    <div className="lite-fix-row" style={dimension.locked ? { color: 'var(--text-2)' } : undefined}>
      <div className="lite-mono lite-muted" style={{ fontSize: 12 }}>{String(rank).padStart(2, '0')}</div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: dimension.locked ? 'var(--text-2)' : 'var(--text)' }}>
          {dimension.locked ? 'Unlocks with your email' : dimension.fix || 'No issue found here.'}
        </div>
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
        {dimension.locked ? 'Locked' : hasSnippet ? 'Included in fix' : 'No snippet needed'}
      </div>
    </div>
  )
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
    <div>
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
    </div>
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

        <EvidenceGallery examples={report.evidence_examples} />

        <WhySectionCard report={report} onAddStoreUrl={onAddStoreUrl} />

        <DiagnosisCard diagnosis={report.diagnosis} />

        <LightCard>
          <SectionHeader label="RECOMMENDATIONS" annotation="Ordered by modeled impact" headline="Ranked fixes" />
          <FixList report={report} />
        </LightCard>

        <LightCard>
          <SectionHeader label="EXPOSURE · MODELED" headline="What this could be costing you" />
          <ExposureCalculator
            revenue={revenue} onRevenueChange={setRevenue}
            aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
            exposure={exposure}
          />
        </LightCard>

        <DiagnosticCliff ctaUrl={ctaUrl} />

        <Footer />
      </div>
    </div>
  )
}
