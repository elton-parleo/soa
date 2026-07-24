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
 */
import { useState } from 'react'
import {
  accessibilityBadgeText, computeExposure, formatCurrency, formatDateStamp,
  getDominantRivalPayoff, groupDimensionsByFamily, rankDimensionsByGap,
} from './liteDerive.js'
import {
  ENTITY_COLORS, LightCard, DarkCard, SectionHeader, ReportHeaderBar,
  InfoBadge, Chip, useAnimateOnMount, formatScore,
} from './liteTheme.jsx'

const DEFAULT_REVENUE = 1_000_000
const DEFAULT_AI_SHARE_PCT = 20

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

function ExecutiveTiles({ report, exposure }) {
  const accessBadge = accessibilityBadgeText(report.scan_status)
  return (
    <LightCard>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28, justifyContent: 'center' }}>
        <Tile label="Composite score" value={formatScore(report.composite)} />
        <Tile label="Visibility" value={formatScore(report.visibility)} />
        <Tile label="Accessibility" value={formatScore(report.accessibility)} badge={accessBadge} />
        <Tile label="Modeled exposure/mo" value={formatCurrency(exposure)} />
      </div>
    </LightCard>
  )
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

function ShareOfMentionsCard({ shareOfMentions, totals }) {
  const payoff = getDominantRivalPayoff({ share_of_mentions: shareOfMentions, totals })
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Share of mentions</div>
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

function VisibilitySection({ report, ctaUrl }) {
  const vb = report.visibility_breakdown
  return (
    <LightCard>
      <SectionHeader
        label="VISIBILITY · 12 QUERIES · CHATGPT"
        annotation={formatDateStamp()}
        headline="How often agents mention you"
      />
      {vb ? (
        <div className="lite-cols-2" style={{ marginTop: 20 }}>
          <MentionRateCard mentionRate={vb.mention_rate} />
          <ShareOfMentionsCard shareOfMentions={vb.share_of_mentions} totals={vb.totals} />
        </div>
      ) : (
        <div className="lite-body lite-muted" style={{ marginTop: 20 }}>
          Visibility data isn't available for this report yet.
        </div>
      )}
      <FunnelTeaserCard ctaUrl={ctaUrl} />
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

function DimensionRow({ dimension, sharedMax }) {
  const trackPct = sharedMax ? (dimension.max / sharedMax) * 100 : 0
  const fillPct = sharedMax ? (dimension.score / sharedMax) * 100 : 0
  const isZero = dimension.score === 0
  const barColor = dimension.code.startsWith('F') ? 'var(--foundation)' : 'var(--accent)'
  const gridlines = []
  for (let v = 0; v <= sharedMax; v += 5) gridlines.push(v)
  if (gridlines[gridlines.length - 1] !== sharedMax) gridlines.push(sharedMax)

  return (
    <div className="lite-dim-row">
      <div className="lite-dim-label lite-mono">{dimension.code} · {dimension.name.toUpperCase()}</div>
      <div className="lite-dim-bar-cell">
        <div className="lite-dim-track">
          <div className="lite-dim-fill" style={{ width: `${trackPct}%` }} />
          {!isZero && <div className="lite-dim-fill" style={{ width: `${fillPct}%`, background: barColor }} />}
          {isZero && <span className="lite-dim-zero-tick" aria-hidden="true" />}
          {gridlines.map((v) => (
            <span key={v} className="lite-dim-gridline" style={{ left: `${(v / sharedMax) * 100}%` }} aria-hidden="true" />
          ))}
        </div>
      </div>
      <div className="lite-dim-score-cell">
        <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700, color: isZero ? 'var(--bad-ink)' : 'var(--text)' }}>
          {formatScore(dimension.score)}/{dimension.max}
        </span>
        {dimension.linked && <Chip tone="accent">LINKED · {dimension.linked.reason.toUpperCase()}</Chip>}
      </div>
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

function DimensionFamily({ title, subtotal, max, dimensions }) {
  if (dimensions.length === 0) return null
  return (
    <div style={{ marginBottom: 24 }}>
      <div className="lite-label" style={{ marginBottom: 6, fontSize: 12 }}>{title.toUpperCase()} · {formatScore(subtotal)}/{max}</div>
      <DimensionChart dimensions={dimensions} />
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
  return (
    <div>
      {scan.integrity_capped && (
        <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
          One more rule: until offers carry honest machine-readable prices, the score cannot pass 59.
        </div>
      )}
      <DimensionFamily title="Foundation" subtotal={scan.foundation?.subtotal} max={scan.foundation?.max ?? 35} dimensions={foundation} />
      <DimensionFamily title="Value" subtotal={scan.value?.subtotal} max={scan.value?.max ?? 65} dimensions={value} />
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

// ─── Ranked fixes ────────────────────────────────────────────────────────

function FixRow({ dimension, rank, maxGap }) {
  const gap = (dimension.max || 0) - (dimension.score || 0)
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

function FixList({ scan }) {
  if (!scan || scan.status !== 'complete') return null
  const ranked = rankDimensionsByGap(scan.dimensions)
  const maxGap = ranked.length ? (ranked[0].max || 0) - (ranked[0].score || 0) : 0
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

export function LiteFullReport({ report, onAddStoreUrl }) {
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
        />

        <ExecutiveTiles report={report} exposure={exposure} />

        <VisibilitySection report={report} ctaUrl={ctaUrl} />

        <EvidenceGallery examples={report.evidence_examples} />

        <WhySectionCard report={report} onAddStoreUrl={onAddStoreUrl} />

        <DiagnosisCard diagnosis={report.diagnosis} />

        <LightCard>
          <SectionHeader label="RECOMMENDATIONS" annotation="Ordered by modeled impact" headline="Ranked fixes" />
          <FixList scan={report.scan} />
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
