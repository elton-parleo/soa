import { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from './Sidebar.jsx'
import { api } from '../api.js'
import { PUBLIC_AUDIT_BASE_URL, reportUrl } from '../lite/publicUrls.js'

// ─── Design tokens ────────────────────────────────────────────────────────────
// Copied verbatim from CycleDashboard.jsx — this page introduces no new
// colors. `blue`/`blueLight` are the two the mock names for in-progress
// pills; they are the same pair CycleDashboard's STATUS.running already
// uses, lifted into T rather than invented here.
const T = {
  navy:        '#0D1829',
  navyMid:     '#162032',
  navyBdr:     '#1E2D42',
  white:       '#FFFFFF',
  offWhite:    '#F8FAFC',
  slate:       '#64748B',
  slateLight:  '#94A3B8',
  border:      '#E2E8F0',
  borderDark:  '#CBD5E1',
  text:        '#0F172A',
  textMid:     '#334155',
  teal:        '#0D9488',
  tealLight:   '#CCFBF1',
  indigo:      '#4F46E5',
  green:       '#16A34A',
  greenLight:  '#DCFCE7',
  amber:       '#D97706',
  amberLight:  '#FEF3C7',
  red:         '#DC2626',
  redLight:    '#FEE2E2',
  blue:        '#1D4ED8',
  blueLight:   '#DBEAFE',
  sidebarText: '#94A3B8',
}

const FONT = "'DM Sans', sans-serif"
const MONO = 'monospace'

// Matches app/routers/lite_requests.py::LITE_IN_PROGRESS_STATUSES.
export const IN_PROGRESS_STATUSES = [
  'pending', 'identifying_competitors', 'generating', 'running',
]

export const POLL_INTERVAL_MS = 30000
const SEARCH_DEBOUNCE_MS = 300
const PAGE_SIZE = 25

// Below this the score bar reads amber rather than teal, per the mock.
const LOW_SCORE_THRESHOLD = 40

const DATE_RANGES = [
  { value: '7',   label: 'Last 7 days'  },
  { value: '30',  label: 'Last 30 days' },
  { value: '90',  label: 'Last 90 days' },
  { value: 'all', label: 'All time'     },
]

const COMPETITOR_SOURCES = [
  { value: '',          label: 'Competitor source' },
  { value: 'generated', label: 'Generated'         },
  { value: 'manual',    label: 'Manual'            },
  { value: 'mixed',     label: 'Mixed'             },
  { value: 'none',      label: 'None'              },
]

const STATUS_CHIPS = [
  { value: '',            label: 'All'         },
  { value: 'complete',    label: 'Complete'    },
  { value: 'in_progress', label: 'In progress' },
  { value: 'failed',      label: 'Failed'      },
]

// ─── Pure helpers (exported for tests) ────────────────────────────────────────

/**
 * One pill per LITE_STATUSES. Takes a bare status, so it maps the DB's
 * own vocabulary and nothing else — the mock's amber "Partial read"
 * pill is NOT a status and lives in rowPill below.
 */
export function statusPill(status) {
  switch (status) {
    case 'complete':
      return { label: 'Complete', bg: T.greenLight, color: '#166534', pulse: false }
    case 'running':
      return { label: 'Running', bg: T.blueLight, color: T.blue, pulse: true }
    case 'generating':
      return { label: 'Generating', bg: T.blueLight, color: T.blue, pulse: false }
    case 'identifying_competitors':
      return { label: 'Identifying competitors', bg: T.blueLight, color: T.blue, pulse: false }
    case 'pending':
      return { label: 'Pending', bg: '#F1F5F9', color: T.slate, pulse: false }
    case 'failed':
      return { label: 'Failed', bg: T.redLight, color: '#991B1B', pulse: false }
    default:
      return { label: status || 'Unknown', bg: '#F1F5F9', color: T.slate, pulse: false }
  }
}

/**
 * The flags under the lead email. Ordered so the two "it happened"
 * facts come first and the "waiting on something" ones read last.
 */
export function leadFlags(row) {
  const flags = []
  if (row.report_email_sent_at) flags.push({ text: 'Report emailed', tone: 'ok' })
  if (row.lead_notified_at)     flags.push({ text: 'Team notified', tone: 'ok' })

  const complete = row.status === 'complete'
  if (complete && !row.email) {
    flags.push({ text: 'Report ready, not sent', tone: 'muted' })
  }
  if (complete && row.email && !row.report_email_sent_at) {
    flags.push({ text: 'Report email queued', tone: 'wait' })
  }
  return flags
}

/**
 * The Score cell's five states. score_state comes straight from the
 * API (app/services/lite_score_batch.py) — this only decides how each
 * one renders.
 */
export function scoreCell(row) {
  switch (row.score_state) {
    case 'available':
      if (row.composite_score === null || row.composite_score === undefined) {
        return { kind: 'none', label: '—' }
      }
      return {
        kind: 'score',
        value: Math.round(row.composite_score),
        low: row.composite_score < LOW_SCORE_THRESHOLD,
      }
    case 'pending':
      return { kind: 'muted', label: 'Pending' }
    case 'not_measurable':
      return { kind: 'muted', label: 'Not measurable' }
    case 'expired':
      return { kind: 'muted', label: 'Expired' }
    case 'partial_read':
      // A degraded crawl usually leaves no composite at all, but a
      // legacy-scorer row still produces its visibility-only figure —
      // show the number when there is one, exactly as the mock does,
      // and let the amber pill carry the caveat.
      if (row.composite_score === null || row.composite_score === undefined) {
        return { kind: 'muted', label: 'Partial read' }
      }
      return {
        kind: 'score',
        value: Math.round(row.composite_score),
        low: row.composite_score < LOW_SCORE_THRESHOLD,
        partial: true,
      }
    default:
      return { kind: 'none', label: '—' }
  }
}

/**
 * Where Open (and Copy link) point. A finished audit opens its report;
 * anything else opens the status page, which is the only page that
 * exists for it yet.
 */
export function openUrl(row) {
  if (!row || !row.token) return null
  if (row.status === 'complete') return reportUrl(row.token)
  return `${PUBLIC_AUDIT_BASE_URL}/s/${encodeURIComponent(row.token)}`
}

/**
 * The pill a ROW actually shows. Identical to statusPill for every row
 * whose crawl read the store, and the mock's amber "Partial read"
 * for one whose crawl came up short.
 *
 * Partial read is deliberately not a seventh LITE_STATUSES value — such
 * a row IS complete, and its status pill saying so while the score says
 * nothing is exactly the gap this fills. degraded_reason is the same
 * string the visitor's own status page showed them.
 */
export function rowPill(row) {
  if (row && row.score_state === 'partial_read') {
    return { label: 'Partial read', bg: T.amberLight, color: '#92400E', pulse: false }
  }
  return statusPill(row && row.status)
}

/** Poll only while something on screen can actually change. */
export function shouldPoll(items) {
  return (items || []).some(row => IN_PROGRESS_STATUSES.includes(row.status))
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return null
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes === 0) return `${rest}s`
  return `${minutes}m ${String(rest).padStart(2, '0')}s`
}

export function formatAbsolute(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export function formatRelative(value, now = Date.now()) {
  if (!value) return ''
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days === 1) return 'Yesterday'
  return `${days} d ago`
}

/** ISO cutoff for the date-range select, or null for "all time". */
export function rangeCutoff(range, now = Date.now()) {
  if (!range || range === 'all') return null
  const days = Number(range)
  if (!Number.isFinite(days)) return null
  return new Date(now - days * 86400000).toISOString()
}

/**
 * The competitors cell. The manual count is only shown where the API
 * could derive it exactly — 'mixed' rows carry null and show the bare
 * source tag. See manual_competitor_count in the router.
 */
export function competitorTag(row) {
  if (!row.competitor_source) return null

  const count = row.manual_competitor_count
  // Null for 'mixed' rows, whose split the API cannot recover — the
  // bare source tag is all there is to say about those.
  if (count === null || count === undefined) return row.competitor_source
  // Everywhere the count IS derivable it is either none of them or all
  // of them, so "manual · 2 manual" would just stutter the source word
  // back. Name the count only when it adds something.
  if (count === 0) return row.competitor_source
  return `${row.competitor_source} · all ${count}`
}

/** The status column's second line. */
export function statusSubline(row) {
  // The reason the crawl came up short outranks the duration: it is
  // the thing a partial-read row exists to tell you.
  if (row.degraded_reason) return row.degraded_reason
  if (IN_PROGRESS_STATUSES.includes(row.status)) {
    const parts = []
    if (row.current_task_text) parts.push(row.current_task_text)
    if (row.queries_total) parts.push(`${row.queries_done ?? 0}/${row.queries_total} queries done`)
    return parts.join(' · ') || null
  }
  if (row.status === 'complete') {
    const duration = formatDuration(row.duration_seconds)
    if (!duration) return null
    return row.duration_is_estimate ? `Ran in ~${duration}` : `Ran in ${duration}`
  }
  if (row.status === 'failed' && row.current_task_text) return row.current_task_text
  return null
}

// ─── Small presentational pieces ──────────────────────────────────────────────

function Pill({ row }) {
  const pill = rowPill(row)
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 8px',
      borderRadius: 999, fontSize: 11, fontWeight: 600,
      // NOT nowrap: "Identifying competitors" is wider than the 12%
      // Status column at 1280px and would otherwise bleed into Score.
      maxWidth: '100%',
      background: pill.bg, color: pill.color,
    }}>
      <i style={{
        width: 6, height: 6, borderRadius: '50%', background: 'currentColor',
        display: 'inline-block',
      }} />
      {pill.label}
    </span>
  )
}

/**
 * Same palette and shape as the Cycles card's error trace (CycleDashboard
 * FailedBody), compacted to sit inside a table cell.
 *
 * Clamped to three lines, which the mock does not do: a real trace
 * wrapped inside a 12%-wide column made the failed row three times
 * taller than every other row and broke the scan-down rhythm of the
 * list. The full, unclamped text is one click away in the drawer.
 */
function ErrorTrace({ message, clamp = true }) {
  if (!message) return null
  return (
    <div style={{
      marginTop: 6, background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 6,
      padding: '6px 8px', fontFamily: MONO, fontSize: 11, color: '#991B1B',
      ...(clamp ? {
        display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      } : { whiteSpace: 'pre-wrap' }),
    }}>
      {message}
    </div>
  )
}

function ScoreCell({ row }) {
  const cell = scoreCell(row)
  if (cell.kind === 'score') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 15, minWidth: 24 }}>{cell.value}</span>
        <div style={{
          height: 6, width: 64, background: T.border, borderRadius: 3, overflow: 'hidden',
        }}>
          <div style={{
            display: 'block', height: '100%',
            width: `${Math.min(100, Math.max(0, cell.value))}%`,
            background: cell.low || cell.partial ? T.amber : T.teal,
          }} />
        </div>
      </div>
    )
  }
  return (
    <div style={{ color: T.slateLight, fontSize: cell.kind === 'muted' ? 12 : 13 }}>
      {cell.label}
    </div>
  )
}

function Stat({ label, value, detail }) {
  return (
    <div style={{
      background: T.white, border: `1px solid ${T.border}`, borderRadius: 10, padding: '14px 16px',
    }}>
      <div style={{ fontSize: 12, color: T.slate }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, marginTop: 2, lineHeight: 1.1 }}>{value}</div>
      {detail && <div style={{ fontSize: 12, color: T.slate, marginTop: 4 }}>{detail}</div>}
    </div>
  )
}

function CopyLinkButton({ row, small = false }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef(null)

  useEffect(() => () => clearTimeout(timer.current), [])

  function copy(event) {
    event.stopPropagation()
    const url = openUrl(row)
    if (!url) return
    Promise.resolve(navigator.clipboard?.writeText(url)).catch(() => {})
    setCopied(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopied(false), 1500)
  }

  if (small) {
    return (
      <button onClick={copy} style={btnStyle(false, true)}>
        {copied ? 'Copied' : 'Copy link'}
      </button>
    )
  }
  return (
    <span
      onClick={copy}
      title="Copy link"
      style={{
        width: copied ? 'auto' : 28, height: 28, padding: copied ? '0 8px' : 0,
        border: `1px solid ${T.border}`, borderRadius: 6, background: T.white,
        display: 'grid', placeItems: 'center', color: copied ? T.teal : T.textMid,
        cursor: 'pointer', fontSize: copied ? 11 : 13, fontWeight: copied ? 600 : 400,
      }}
    >
      {copied ? 'Copied' : '⧉'}
    </span>
  )
}

function btnStyle(primary, small) {
  return {
    padding: small ? '6px 10px' : '10px 16px',
    borderRadius: 8,
    border: `1px solid ${primary ? T.navy : T.border}`,
    background: primary ? T.navy : T.white,
    color: primary ? T.white : T.textMid,
    fontWeight: small ? 500 : 600,
    fontSize: small ? 12 : 13,
    cursor: 'pointer',
    fontFamily: FONT,
  }
}

// ─── Detail drawer ────────────────────────────────────────────────────────────

function KV({ k, v, mono, muted }) {
  return (
    <>
      <div style={{ color: T.slate }}>{k}</div>
      <div style={{
        color: muted ? T.slateLight : T.text, minWidth: 0, wordBreak: 'break-word',
        fontFamily: mono ? MONO : FONT, fontSize: mono ? 12 : 13,
      }}>
        {v ?? '—'}
      </div>
    </>
  )
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ fontSize: 12, fontWeight: 600, color: T.slate, margin: '0 0 8px' }}>{title}</h3>
      {children}
    </div>
  )
}

const KV_GRID = {
  display: 'grid', gridTemplateColumns: '130px 1fr', rowGap: 7, columnGap: 12, fontSize: 13,
}

function Dim({ label, value, max }) {
  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: 8, padding: '8px 10px' }}>
      <div style={{ fontSize: 11, color: T.slate }}>{label}</div>
      <div style={{ fontWeight: 700, fontSize: 15 }}>
        {value ?? '—'}
        {max != null && (
          <small style={{ fontWeight: 400, color: T.slateLight, fontSize: 11 }}> / {max}</small>
        )}
      </div>
    </div>
  )
}

function Drawer({ detail, loading, error, onClose }) {
  const row = detail
  const pillars = row?.pillars || {}
  const discoveryOutcome = row?.discovery_outcome

  return (
    <aside style={{
      position: 'fixed', top: 0, right: 0, width: 440, height: '100vh', background: T.white,
      borderLeft: `1px solid ${T.border}`, boxShadow: '-8px 0 24px rgba(15,23,42,.06)',
      display: 'flex', flexDirection: 'column', zIndex: 20, fontFamily: FONT,
    }}>
      <div style={{ padding: '20px 22px 14px', borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
              {row?.brand_name || (loading ? 'Loading…' : 'Audit')}
            </h2>
            {row && (
              <div style={{ fontFamily: MONO, fontSize: 11, color: T.slate, marginTop: 4 }}>
                token {row.token}{row.study_type ? ` · ${row.study_type}` : ''}
              </div>
            )}
          </div>
          <span
            onClick={onClose}
            title="Close"
            style={{
              width: 28, height: 28, border: `1px solid ${T.border}`, borderRadius: 6,
              background: T.white, display: 'grid', placeItems: 'center',
              color: T.textMid, cursor: 'pointer', fontSize: 13, flex: 'none',
            }}
          >
            ✕
          </span>
        </div>
        {row && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
            <a
              href={openUrl(row)}
              target="_blank"
              rel="noopener noreferrer"
              style={{ ...btnStyle(true, true), textDecoration: 'none', display: 'inline-block' }}
            >
              {row.status === 'complete' ? 'Open report' : 'Open status page'}
            </a>
            <CopyLinkButton row={row} small />
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '16px 22px 24px' }}>
        {error && <div style={{ color: T.red, fontSize: 13 }}>{error}</div>}
        {loading && !row && <div style={{ color: T.slate, fontSize: 13 }}>Loading…</div>}

        {row && (
          <>
            <Section title="Lead">
              <div style={KV_GRID}>
                <KV k="Email" v={row.email} muted={!row.email} />
                <KV k="Team notified" v={row.lead_notified_at ? formatAbsolute(row.lead_notified_at) : 'Not notified'} muted={!row.lead_notified_at} />
                <KV k="Report emailed" v={row.report_email_sent_at ? formatAbsolute(row.report_email_sent_at) : 'Not sent'} muted={!row.report_email_sent_at} />
              </div>
            </Section>

            <Section title="Result">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <Dim label="Agentic Value" value={row.composite_score != null ? Math.round(row.composite_score) : scoreCell(row).label} max={row.composite_score != null ? 100 : null} />
                <Dim label="Visibility" value={pillars.visibility?.earned} max={pillars.visibility?.applicable_max} />
                <Dim label="Accessibility" value={pillars.accessibility?.earned} max={pillars.accessibility?.applicable_max} />
                <Dim label="True Value" value={pillars.true_value?.earned} max={pillars.true_value?.applicable_max} />
                <Dim label="Scan score" value={row.scan_total_score} />
                <Dim label="Pages fetched" value={row.scan_pages_fetched_count} />
              </div>
              {row.scan_integrity_capped && (
                <div style={{
                  marginTop: 8, background: T.amberLight, border: '1px solid #FDE68A',
                  borderRadius: 8, padding: '8px 10px', fontSize: 12, color: '#92400E',
                }}>
                  Integrity-capped — dishonest pricing signals held this score at 59.
                </div>
              )}
            </Section>

            {discoveryOutcome && (
              <Section title="Discovery">
                <div style={{
                  background: T.amberLight, border: '1px solid #FDE68A',
                  borderRadius: 8, padding: '8px 10px', fontSize: 12, color: '#92400E',
                }}>
                  {discoveryOutcome.summary || discoveryOutcome.code}
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: T.slate, marginTop: 6 }}>
                  {discoveryOutcome.code}
                </div>
              </Section>
            )}

            {row.error_message && (
              <Section title="Error">
                <ErrorTrace message={row.error_message} clamp={false} />
              </Section>
            )}

            <Section title="Request">
              <div style={KV_GRID}>
                <KV k="Submitted" v={formatAbsolute(row.created_at)} />
                <KV k="Store URL" v={row.store_url || 'no store URL given'} muted={!row.store_url} />
                <KV
                  k="Competitors"
                  v={(row.competitor_names || []).join(', ') || 'none'}
                  muted={!(row.competitor_names || []).length}
                />
                <KV k="Source" v={competitorTag(row) || '—'} />
                <KV k="Brand entity" v={row.brand_entity_id ? `soa_entities #${row.brand_entity_id}` : null} mono />
                <KV
                  k="Competitor entities"
                  v={(row.competitor_entity_ids || []).map(id => `#${id}`).join(', ') || null}
                  mono
                />
                <KV k="Cycle" v={row.cycle_id ? `soa_cycles #${row.cycle_id}` : null} mono />
                <KV
                  k="Scan"
                  v={row.scan_status ? `${row.scan_status}${row.scan_integrity_capped ? ' · integrity-capped' : ''}` : null}
                />
                {/* Non-commerce report: a brand_only row scoring 10-22
                    is a correct reading of a non-store site, not a
                    broken crawl. Triaging the two apart needed the raw
                    dimensions JSON before this. */}
                <KV k="Site type" v={row.site_type} mono muted={!row.site_type} />
                {/* Scan reuse: present only when this row's crawl data
                    was copied from a recent scan of the same host. */}
                <KV
                  k="Crawl"
                  v={row.reused_from_scan_id
                    ? `reused from soa_lite_scan_results #${row.reused_from_scan_id}${row.reused_at ? ` · ${formatAbsolute(row.reused_at)}` : ''}`
                    : null}
                  mono
                />
                <KV k="Scorer" v={row.scorer_version ? `v${row.scorer_version}` : null} mono />
                <KV k="Rate-limit key" v={row.ip_hash_truncated ? `ip_hash ${row.ip_hash_truncated}` : null} mono muted />
              </div>
            </Section>

            <Section title="Full Analysis">
              <div style={KV_GRID}>
                <KV
                  k="Continuation"
                  v={row.continuation_cycle_code
                    ? `${row.continuation_cycle_code} · ${row.continuation_cycle_status || 'unknown'}`
                    : 'None started'}
                  muted={!row.continuation_cycle_code}
                />
                <KV k="Study series" v={row.study_series_id} mono muted={!row.study_series_id} />
              </div>
            </Section>

            <Section title="Run log">
              {(row.events || []).length === 0 && (
                <div style={{ color: T.slateLight, fontSize: 12 }}>
                  No events recorded for this audit.
                </div>
              )}
              {(row.events || []).length > 0 && (
                <div style={{
                  borderLeft: `2px solid ${T.border}`, marginLeft: 5, paddingLeft: 14,
                  display: 'flex', flexDirection: 'column', gap: 10,
                }}>
                  {/* Newest last — the log reads top to bottom in the
                      order the run actually happened. */}
                  {[...(row.events || [])]
                    .sort((a, b) => (a.seq || 0) - (b.seq || 0))
                    .map((event, index) => (
                      <div key={event.seq ?? index} style={{ position: 'relative', fontSize: 12 }}>
                        <span style={{
                          position: 'absolute', left: -20, top: 5, width: 8, height: 8,
                          borderRadius: '50%',
                          background: event.kind === 'done' ? T.teal : T.borderDark,
                        }} />
                        <span style={{
                          color: T.slateLight, fontFamily: MONO, fontSize: 11, marginRight: 8,
                        }}>
                          {event.ts ? new Date(event.ts).toLocaleTimeString('en-US', { hour12: false }) : ''}
                        </span>
                        <span style={{ fontWeight: 600, color: T.textMid, marginRight: 6 }}>
                          {event.task}
                        </span>
                        {event.text}
                      </div>
                    ))}
                </div>
              )}
            </Section>
          </>
        )}
      </div>
    </aside>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AuditsPage({ onNavigate }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const [page, setPage]                 = useState(1)
  const [searchInput, setSearchInput]   = useState('')
  const [q, setQ]                       = useState('')
  const [status, setStatus]             = useState('')
  const [leadsOnly, setLeadsOnly]       = useState(false)
  const [range, setRange]               = useState('30')
  const [source, setSource]             = useState('')

  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail]         = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError]     = useState(null)

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(searchInput)
      setPage(1)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchInput])

  const load = useCallback((background = false) => {
    if (!background) setLoading(true)
    return api.getLiteRequests({
      page,
      page_size: PAGE_SIZE,
      q,
      status,
      leads_only: leadsOnly,
      competitor_source: source,
      created_after: rangeCutoff(range),
    })
      .then(result => { setData(result); setError(null) })
      .catch(err => { if (!background) { setData(null); setError(err.message) } })
      .finally(() => { if (!background) setLoading(false) })
  }, [page, q, status, leadsOnly, source, range])

  useEffect(() => { load() }, [load])

  // Poll only while a visible row is still in flight; the interval is
  // torn down the moment none are.
  const items = data?.items || []
  const polling = shouldPoll(items)
  useEffect(() => {
    if (!polling) return undefined
    const timer = setInterval(() => load(true), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [polling, load])

  useEffect(() => {
    if (selectedId === null) { setDetail(null); return }
    setDetailLoading(true)
    setDetailError(null)
    api.getLiteRequest(selectedId)
      .then(result => setDetail(result))
      .catch(err => setDetailError(err.message))
      .finally(() => setDetailLoading(false))
  }, [selectedId])

  const summary = data?.summary || {}
  const totalCount = data?.total_count || 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const firstRow = totalCount === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const lastRow = Math.min(page * PAGE_SIZE, totalCount)

  const leadsPct = summary.audits_count
    ? Math.round((summary.leads_count / summary.audits_count) * 100)
    : 0

  function pickStatus(value) {
    setStatus(value)
    setPage(1)
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: FONT, background: T.offWhite }}>
      <Sidebar activeView="audits" onNavigate={onNavigate} />

      <div style={{ flex: 1, marginLeft: 200, padding: '32px 36px 60px', minWidth: 0 }}>

        {/* Page header */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          gap: 24, marginBottom: 20,
        }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 4px' }}>Audits</h1>
            <p style={{ margin: 0, color: T.slate, fontSize: 13, maxWidth: '60ch' }}>
              Every audit submitted at {PUBLIC_AUDIT_BASE_URL.replace(/^https?:\/\//, '')}, with
              the email the visitor left on the status page. One row per soa_lite_requests row.
            </p>
          </div>
          <a
            href={PUBLIC_AUDIT_BASE_URL}
            target="_blank"
            rel="noopener noreferrer"
            style={{ ...btnStyle(true, false), textDecoration: 'none', whiteSpace: 'nowrap' }}
          >
            Open audit tool
          </a>
        </div>

        {/* Summary strip */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20,
        }}>
          <Stat label="Audits" value={summary.audits_count ?? 0} detail="in the current filter" />
          <Stat
            label="Leads captured"
            value={summary.leads_count ?? 0}
            detail={summary.audits_count ? `${leadsPct}% of audits left an email` : null}
          />
          <Stat label="In progress now" value={summary.in_progress_count ?? 0} />
          <Stat label="Failed" value={summary.failed_count ?? 0} />
          <Stat label="Full Analyses started" value={summary.continuation_count ?? 0} />
        </div>

        {/* Filters */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12,
        }}>
          <input
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            placeholder="Search brand, email, token, store URL"
            aria-label="Search audits"
            style={{
              flex: 1, minWidth: 260, maxWidth: 420, background: T.white,
              border: `1px solid ${T.border}`, borderRadius: 8, padding: '8px 12px',
              fontSize: 13, color: T.text, fontFamily: FONT,
            }}
          />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {STATUS_CHIPS.map(chip => {
              const on = status === chip.value
              const count = {
                '':            summary.audits_count,
                complete:      (summary.audits_count ?? 0) - (summary.in_progress_count ?? 0) - (summary.failed_count ?? 0),
                in_progress:   summary.in_progress_count,
                failed:        summary.failed_count,
              }[chip.value]
              return (
                <span
                  key={chip.value || 'all'}
                  onClick={() => pickStatus(chip.value)}
                  style={{
                    padding: '6px 10px', borderRadius: 999,
                    border: `1px solid ${on ? T.navy : T.border}`,
                    background: on ? T.navy : T.white,
                    color: on ? T.white : T.textMid,
                    fontSize: 12, cursor: 'pointer',
                    display: 'inline-flex', gap: 6, alignItems: 'center',
                  }}
                >
                  {chip.label}
                  <span style={{ color: T.slateLight }}>{count ?? 0}</span>
                </span>
              )
            })}
          </div>

          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12,
            color: T.textMid, cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={leadsOnly}
              onChange={e => { setLeadsOnly(e.target.checked); setPage(1) }}
              aria-label="Leads only"
            />
            Leads only
          </label>

          <select
            value={range}
            onChange={e => { setRange(e.target.value); setPage(1) }}
            aria-label="Date range"
            style={selectStyle}
          >
            {DATE_RANGES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>

          <select
            value={source}
            onChange={e => { setSource(e.target.value); setPage(1) }}
            aria-label="Competitor source"
            style={selectStyle}
          >
            {COMPETITOR_SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>

        {/* Results meta */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          fontSize: 12, color: T.slate, marginBottom: 8,
        }}>
          <span>
            {totalCount === 0
              ? 'No audits match these filters'
              : `Showing ${firstRow}–${lastRow} of ${totalCount} · sorted by newest`}
          </span>
          {polling && <span>Auto-refreshes every 30 s while an audit is in progress</span>}
        </div>

        {/* Table */}
        <div style={{
          background: T.white, border: `1px solid ${T.border}`, borderRadius: 10, overflow: 'hidden',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '20%' }} />
              <col style={{ width: '19%' }} />
              <col style={{ width: '12%' }} />
              <col style={{ width: '11%' }} />
              <col style={{ width: '16%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '7%'  }} />
              <col style={{ width: '5%'  }} />
            </colgroup>
            <thead>
              <tr>
                {['Brand', 'Lead', 'Status', 'Score', 'Competitors', 'Submitted ↓', 'Full Analysis', ''].map((label, i) => (
                  <th key={i} style={{
                    textAlign: 'left', fontSize: 11, fontWeight: 600,
                    color: i === 5 ? T.text : T.slate, padding: '10px 12px',
                    background: T.offWhite, borderBottom: `1px solid ${T.border}`,
                    whiteSpace: 'nowrap',
                  }}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} style={emptyCell}>Loading audits…</td></tr>
              )}
              {!loading && error && (
                <tr><td colSpan={8} style={{ ...emptyCell, color: T.red }}>{error}</td></tr>
              )}
              {!loading && !error && items.length === 0 && (
                <tr><td colSpan={8} style={emptyCell}>No audits match these filters.</td></tr>
              )}

              {!loading && !error && items.map(row => {
                const selected = row.id === selectedId
                const subline = statusSubline(row)
                const tag = competitorTag(row)
                return (
                  <tr
                    key={row.id}
                    onClick={() => setSelectedId(row.id)}
                    style={{ cursor: 'pointer', background: selected ? '#F0FDFA' : undefined }}
                  >
                    <td style={{ ...cellStyle, boxShadow: selected ? `inset 3px 0 0 ${T.teal}` : undefined }}>
                      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', minWidth: 0 }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: 6, background: T.offWhite,
                          border: `1px solid ${T.border}`, display: 'grid', placeItems: 'center',
                          fontSize: 11, fontWeight: 700, color: T.textMid, flex: 'none',
                        }}>
                          {(row.brand_name || '?').trim().charAt(0).toUpperCase()}
                        </div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600 }}>{row.brand_name}</div>
                          <div style={{
                            color: row.store_url ? T.slate : T.slateLight,
                            fontStyle: row.store_url ? 'normal' : 'italic',
                            fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}>
                            {row.store_url ? row.store_url.replace(/^https?:\/\//, '') : 'no store URL given'}
                          </div>
                        </div>
                      </div>
                    </td>

                    <td style={cellStyle}>
                      <div style={{
                        fontWeight: row.email ? 500 : 400,
                        color: row.email ? T.text : T.slateLight,
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      }}>
                        {row.email || 'No email yet'}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 3, fontSize: 11, flexWrap: 'wrap' }}>
                        {leadFlags(row).map(flag => (
                          <span key={flag.text} style={{
                            color: flag.tone === 'ok' ? T.green : flag.tone === 'wait' ? T.amber : T.slate,
                          }}>
                            {flag.tone === 'ok' ? '✓ ' : ''}{flag.text}
                          </span>
                        ))}
                      </div>
                    </td>

                    <td style={cellStyle}>
                      <Pill row={row} />
                      {subline && (
                        <div style={{ fontSize: 11, color: T.slate, marginTop: 4 }}>{subline}</div>
                      )}
                      {row.status === 'failed' && <ErrorTrace message={row.error_message} />}
                    </td>

                    <td style={cellStyle}><ScoreCell row={row} /></td>

                    <td style={{ ...cellStyle, fontSize: 12, color: T.textMid }}>
                      {(row.competitor_names || []).length
                        ? (row.competitor_names || []).join(', ')
                        : <span style={{ color: T.slateLight }}>
                            {IN_PROGRESS_STATUSES.includes(row.status) ? 'Generating…' : 'none'}
                          </span>}
                      {tag && (
                        <span style={{
                          display: 'inline-block', marginLeft: 4, fontSize: 10, padding: '1px 5px',
                          borderRadius: 4, background: T.offWhite, border: `1px solid ${T.border}`,
                          color: T.slate, verticalAlign: 'middle',
                        }}>
                          {tag}
                        </span>
                      )}
                    </td>

                    <td style={{ ...cellStyle, whiteSpace: 'nowrap' }}>
                      {formatAbsolute(row.created_at)}
                      <div style={{ color: T.slate, fontSize: 12 }}>{formatRelative(row.created_at)}</div>
                    </td>

                    <td style={{ ...cellStyle, fontSize: 12 }}>
                      {row.continuation_cycle_code ? (
                        <>
                          <a
                            href="#metrics"
                            onClick={e => {
                              e.preventDefault()
                              e.stopPropagation()
                              onNavigate && onNavigate('metrics', { cycleCode: row.continuation_cycle_code })
                            }}
                            style={{ color: T.indigo, textDecoration: 'none', fontWeight: 600 }}
                          >
                            {row.continuation_cycle_code} ›
                          </a>
                          <div style={{ color: T.slate }}>{row.continuation_cycle_status}</div>
                        </>
                      ) : row.status === 'complete' ? (
                        <a
                          href="#new-cycle"
                          onClick={e => {
                            e.preventDefault()
                            e.stopPropagation()
                            onNavigate && onNavigate('new-cycle', {
                              auditToken: row.token, brandName: row.brand_name,
                            })
                          }}
                          style={{ color: T.indigo, textDecoration: 'none', fontWeight: 600 }}
                        >
                          Start ›
                        </a>
                      ) : (
                        <span style={{ color: T.slateLight }}>—</span>
                      )}
                    </td>

                    <td style={cellStyle}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <a
                          href={openUrl(row)}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={e => e.stopPropagation()}
                          title={row.status === 'complete' ? 'Open report' : 'Open status page'}
                          style={{
                            width: 28, height: 28, border: `1px solid ${T.border}`, borderRadius: 6,
                            background: T.white, display: 'grid', placeItems: 'center',
                            color: T.textMid, cursor: 'pointer', fontSize: 13, textDecoration: 'none',
                          }}
                        >
                          ↗
                        </a>
                        <CopyLinkButton row={row} />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* Pagination */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '10px 12px', borderTop: `1px solid ${T.border}`, fontSize: 12,
            color: T.slate, background: T.offWhite,
          }}>
            <span>{PAGE_SIZE} per page</span>
            <div style={{ display: 'flex', gap: 4 }}>
              <span
                onClick={() => page > 1 && setPage(page - 1)}
                style={{ ...pagerBtn, cursor: page > 1 ? 'pointer' : 'not-allowed', opacity: page > 1 ? 1 : 0.5 }}
              >
                ‹
              </span>
              <span style={{ ...pagerBtn, background: T.navy, color: T.white, borderColor: T.navy }}>
                {page}
              </span>
              <span style={{ padding: '4px 8px' }}>of {totalPages}</span>
              <span
                onClick={() => page < totalPages && setPage(page + 1)}
                style={{ ...pagerBtn, cursor: page < totalPages ? 'pointer' : 'not-allowed', opacity: page < totalPages ? 1 : 0.5 }}
              >
                ›
              </span>
            </div>
          </div>
        </div>
      </div>

      {selectedId !== null && (
        <Drawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}

const cellStyle = {
  padding: '11px 12px', borderBottom: `1px solid ${T.border}`,
  verticalAlign: 'top', fontSize: 13,
}

const emptyCell = {
  padding: '28px 12px', textAlign: 'center', color: T.slate, fontSize: 13,
}

const selectStyle = {
  padding: '6px 10px', borderRadius: 999, border: `1px solid ${T.border}`,
  background: T.white, fontSize: 12, color: T.textMid, cursor: 'pointer', fontFamily: FONT,
}

const pagerBtn = {
  padding: '4px 8px', borderRadius: 6, border: `1px solid ${T.border}`, background: T.white,
}
