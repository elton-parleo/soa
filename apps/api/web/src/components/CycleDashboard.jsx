import React, { useState, useEffect } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'

// ─── Design tokens (verbatim from NewCycleWizard.jsx) ────────────────────────
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
  sidebarText: '#94A3B8',
}

// ─── Status tokens ────────────────────────────────────────────────────────────
const STATUS = {
  running: {
    badge:   '#1D4ED8',
    badgeBg: '#DBEAFE',
    border:  '#3B82F6',
    dot:     '#3B82F6',
    label:   'RUNNING',
  },
  needs_review: {
    badge:   '#92400E',
    badgeBg: '#FEF3C7',
    border:  '#F59E0B',
    dot:     '#F59E0B',
    label:   'REVIEW',
  },
  complete: {
    badge:   '#14532D',
    badgeBg: '#DCFCE7',
    border:  '#16A34A',
    dot:     '#16A34A',
    label:   'COMPLETE',
  },
  failed: {
    badge:   '#991B1B',
    badgeBg: '#FEE2E2',
    border:  '#DC2626',
    dot:     '#DC2626',
    label:   'FAILED',
  },
  planned: {
    badge:   '#374151',
    badgeBg: '#F3F4F6',
    border:  '#9CA3AF',
    dot:     '#9CA3AF',
    label:   'PLANNED',
  },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function calcElapsed(createdAt, updatedAt) {
  // Returns a formatted duration string between createdAt and updatedAt
  // (or now if updatedAt is null). e.g. "02:34:52" or "1d 03:12:44"
  if (!createdAt) return '—'
  const start = new Date(createdAt)
  const end   = updatedAt ? new Date(updatedAt) : new Date()
  if (isNaN(start.getTime())) return '—'
  const diffMs    = Math.max(0, end.getTime() - start.getTime())
  const totalSecs = Math.floor(diffMs / 1000)
  const days  = Math.floor(totalSecs / 86400)
  const hours = Math.floor((totalSecs % 86400) / 3600)
  const mins  = Math.floor((totalSecs % 3600) / 60)
  const secs  = totalSecs % 60
  const hh = String(hours).padStart(2, '0')
  const mm = String(mins).padStart(2, '0')
  const ss = String(secs).padStart(2, '0')
  if (days > 0) return `${days}d ${hh}:${mm}:${ss}`
  return `${hh}:${mm}:${ss}`
}

function cycleDisplayName(cycle_code) {
  const parts = cycle_code.split('-')
  const nameParts = parts.slice(2)
  return nameParts
    .map(p => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ')
}

function formatEstRemaining(totalRuns, completedRuns) {
  const remaining = Math.max(0, totalRuns - completedRuns)
  const secs = remaining * 7
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

// ─── Topbar ───────────────────────────────────────────────────────────────────

function Topbar() {
  return (
    <div style={{ height: 56, background: T.white, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', flexShrink: 0 }}>
      <div style={{ fontSize: 13, color: T.slate }}>
        <span style={{ color: T.text, fontWeight: 500 }}>CYCLES</span>
        {' › '}
        <span>Overview</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: T.indigo, color: T.white, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>E</div>
      </div>
    </div>
  )
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.planned
  const icons = { running: '●', needs_review: '⚠', complete: '✓', failed: '✗', planned: '◷' }
  return (
    <span style={{ padding: '4px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, color: s.badge, background: s.badgeBg, whiteSpace: 'nowrap' }}>
      {icons[status] || '◷'} {s.label}
    </span>
  )
}

// ─── Card base wrapper ────────────────────────────────────────────────────────

function CycleCard({ cycle, children, onClick }) {
  const s = STATUS[cycle.status] || STATUS.planned
  return (
    <div
      onClick={onClick}
      style={{
        background: T.white,
        borderRadius: 12,
        border: `1px solid ${T.border}`,
        borderLeft: `3px solid ${s.border}`,
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      {/* Card header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontFamily: 'monospace', fontSize: 11, color: T.slate, marginBottom: 4 }}>{cycle.cycle_code}</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{cycleDisplayName(cycle.cycle_code)}</div>
        </div>
        <StatusBadge status={cycle.status} />
      </div>
      {children}
    </div>
  )
}

// ─── Running card body ────────────────────────────────────────────────────────

const PLATFORM_META = {
  chatgpt:    { icon: '🤖', color: '#10B981' },
  gemini:     { icon: '✦',  color: '#4F46E5' },
  claude:     { icon: '◈',  color: '#F59E0B' },
  perplexity: { icon: '🔍', color: '#0EA5E9' },
}

function RunningBody({ cycle, onViewCycle }) {
  const pct = cycle.total_runs_planned > 0
    ? Math.min(100, (cycle.completed_runs / cycle.total_runs_planned) * 100)
    : 0
  const estRemaining = formatEstRemaining(cycle.total_runs_planned, cycle.completed_runs)

  // Derive likely platforms from study_type as rough heuristic; fall back to placeholders
  const derivedPlatforms = ['chatgpt', 'gemini']

  return (
    <>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>Progress</span>
          <span style={{ fontSize: 12, color: T.textMid, fontFamily: 'monospace' }}>
            {cycle.completed_runs}/{cycle.total_runs_planned} runs
          </span>
        </div>
        <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: T.teal, borderRadius: 4, transition: 'width 0.5s ease' }} />
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
          {derivedPlatforms.map(pid => {
            const meta = PLATFORM_META[pid] || { icon: '?', color: T.slate }
            return (
              <div key={pid} style={{ width: 24, height: 24, borderRadius: 6, background: meta.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: T.white }}>
                {meta.icon}
              </div>
            )
          })}
        </div>
      </div>
      <div style={{ fontSize: 13, color: T.slate }}>◷ Est. {estRemaining} remaining</div>
      <button
        onClick={e => { e.stopPropagation(); onViewCycle && onViewCycle(cycle.cycle_code) }}
        style={{ width: '100%', padding: '9px 0', background: T.white, border: `1px solid ${T.text}`, color: T.text, borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
      >
        View Progress
      </button>
    </>
  )
}

// ─── Needs Review card body ───────────────────────────────────────────────────

function NeedsReviewBody({ cycle, onViewCycle }) {
  const flagCount = (() => {
    const m = cycle.notes?.match(/(\d+)\s+responses?\s+flagged/i)
    return m ? m[1] : '?'
  })()

  return (
    <>
      <div style={{ background: '#FEF3C7', borderLeft: `3px solid #F59E0B`, borderRadius: 6, padding: '10px 12px' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#92400E', marginBottom: 4 }}>⚠ {flagCount} Responses Pending</div>
        <div style={{ fontSize: 12, color: '#92400E' }}>Sentiment classification ambiguity detected.</div>
      </div>
      <div style={{ display: 'flex', gap: 16 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Status</div>
          <div style={{ fontSize: 13, color: T.text }}>Coding Complete</div>
        </div>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Last Update</div>
          <div style={{ fontSize: 13, color: T.text }}>2h ago</div>
        </div>
      </div>
      <button
        onClick={e => { e.stopPropagation(); onViewCycle && onViewCycle(cycle.cycle_code) }}
        style={{ width: '100%', padding: '9px 0', background: T.text, border: 'none', color: T.white, borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
      >
        Review Now →
      </button>
    </>
  )
}

// ─── Complete card body ───────────────────────────────────────────────────────

function CompleteBody({ cycle, onViewCycle }) {
  const MetricRow = ({ label, value, last }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: last ? 0 : 10, marginBottom: last ? 0 : 10, borderBottom: last ? 'none' : `1px solid ${T.border}` }}>
      <span style={{ fontSize: 13, color: T.slate }}>{label}</span>
      <span style={{ fontSize: 13, color: T.text, fontWeight: 700 }}>{value}</span>
    </div>
  )

  return (
    <>
      <div>
        <MetricRow label="Elapsed Time" value={<span style={{ fontFamily: 'monospace', color: T.teal }}>{calcElapsed(cycle.created_at, cycle.updated_at)}</span>} />
        <MetricRow label="Completed Runs" value={cycle.completed_runs ?? '—'} />
        <MetricRow label="Export Ready" value={<span style={{ color: T.teal }}>📄</span>} last />
      </div>
      <button
        onClick={e => { e.stopPropagation(); onViewCycle && onViewCycle(cycle.cycle_code) }}
        style={{ width: '100%', padding: '9px 0', background: T.white, border: `1px solid ${T.text}`, color: T.text, borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
      >
        View Results
      </button>
    </>
  )
}

// ─── Failed card body ─────────────────────────────────────────────────────────

function FailedBody({ cycle, onViewCycle, onResume, resuming }) {
  const notesLines = (cycle.notes || '').split('\n')
  const stageLine  = notesLines.find(l => l.toLowerCase().startsWith('failed at')) || 'Failed at: unknown stage'
  const reasonLine = notesLines.find(l => l.toLowerCase().startsWith('reason'))    || 'Reason: Unknown error'
  const isResuming = resuming === cycle.cycle_code

  return (
    <>
      <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 6, padding: 12 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: '#991B1B', textTransform: 'uppercase', letterSpacing: 0.5, fontFamily: 'monospace', marginBottom: 6 }}>ERROR TRACE</div>
        <div style={{ fontSize: 13, color: T.text, marginBottom: 4 }}>{stageLine}</div>
        <div style={{ fontSize: 12, color: T.slate }}>{reasonLine}</div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={e => { e.stopPropagation(); onResume && onResume(cycle) }}
          disabled={isResuming}
          style={{
            flex: 1, padding: '9px 0',
            background: T.text, border: 'none', color: T.white,
            borderRadius: 8, fontWeight: 600, fontSize: 13,
            opacity: isResuming ? 0.7 : 1,
            cursor: isResuming ? 'not-allowed' : 'pointer',
          }}
        >
          {isResuming ? '...' : '▶ Resume'}
        </button>
        <button
          style={{ width: 40, height: 40, padding: 0, background: T.white, border: `1px solid ${T.border}`, color: T.text, borderRadius: 8, fontWeight: 600, fontSize: 16, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          ⋮
        </button>
      </div>
    </>
  )
}

// ─── Planned card body ────────────────────────────────────────────────────────

function PlannedBody({ cycle, onViewCycle }) {
  return (
    <>
      <div style={{ background: T.offWhite, borderRadius: 6, padding: 12, fontSize: 13, color: T.slate }}>
        ◷ Queued — waiting for pipeline worker to start this cycle.
      </div>
      <button
        onClick={e => { e.stopPropagation(); onViewCycle && onViewCycle(cycle.cycle_code) }}
        style={{ width: '100%', padding: '9px 0', background: T.white, border: `1px solid ${T.text}`, color: T.text, borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }}
      >
        View Details
      </button>
      {/* Scope SKUs are managed from the entity's "Measured SKUs" tab
          (EntityRegistry.jsx), the cycle-creation wizard's Scope step, and
          the cycle detail Scope section (MetricsDashboard.jsx) — not here. */}
    </>
  )
}

// ─── Empty slot card ──────────────────────────────────────────────────────────

function EmptySlotCard({ onNewCycle }) {
  const [hovered, setHovered] = useState(false)
  return (
    <div
      onClick={onNewCycle}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: T.white,
        borderRadius: 12,
        border: `1px dashed ${hovered ? T.text : T.borderDark}`,
        minHeight: 220,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'border-color 0.15s',
        padding: 24,
        textAlign: 'center',
      }}
    >
      <div style={{ width: 48, height: 48, borderRadius: '50%', background: T.offWhite, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, color: T.slate, marginBottom: 12 }}>
        ↺
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, color: T.textMid, marginBottom: 6 }}>Initiate New Cycle</div>
      <div style={{ fontSize: 12, color: T.slate, maxWidth: 160, lineHeight: 1.5 }}>
        Define new parameters, sources, and algorithmic depth for brand analysis.
      </div>
    </div>
  )
}

// ─── Skeleton cards ───────────────────────────────────────────────────────────

function SkeletonCard({ delay = 0 }) {
  return (
    <div style={{
      background: T.white,
      borderRadius: 12,
      border: `1px solid ${T.border}`,
      borderLeft: `3px solid ${T.border}`,
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      padding: 20,
      minHeight: 220,
      animation: `pulse 1.5s ease-in-out ${delay}s infinite`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ height: 10, width: 100, background: T.border, borderRadius: 4, marginBottom: 8 }} />
          <div style={{ height: 16, width: 140, background: T.border, borderRadius: 4 }} />
        </div>
        <div style={{ height: 22, width: 70, background: T.border, borderRadius: 4 }} />
      </div>
      <div style={{ height: 8, background: T.border, borderRadius: 4, marginBottom: 10 }} />
      <div style={{ height: 8, width: '70%', background: T.border, borderRadius: 4, marginBottom: 20 }} />
      <div style={{ height: 36, background: T.border, borderRadius: 8 }} />
    </div>
  )
}

// ─── Filter pill ──────────────────────────────────────────────────────────────

function FilterPill({ label, count, dotColor, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 14px',
        borderRadius: 99,
        border: `1px solid ${active ? T.text : T.border}`,
        background: active ? T.text : T.white,
        color: active ? T.white : T.textMid,
        fontSize: 13, fontWeight: 500,
        cursor: 'pointer',
        transition: 'all 0.12s',
      }}
    >
      {dotColor && (
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: dotColor, display: 'inline-block', flexShrink: 0 }} />
      )}
      {label}
      {count !== undefined && (
        <span style={{ background: active ? 'rgba(255,255,255,0.2)' : T.offWhite, color: active ? T.white : T.slate, borderRadius: 99, padding: '1px 7px', fontSize: 11, fontWeight: 700 }}>
          {count}
        </span>
      )}
    </button>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function CycleDashboard({ onNewCycle, onViewCycle, onNavigate }) {
  const [cycles,       setCycles]       = useState([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [activeFilter, setActiveFilter] = useState('all')
  const [liveTimer,    setLiveTimer]    = useState(0)
  const [resuming,     setResuming]     = useState(null) // cycle_code being resumed

  const fetchCycles = () =>
    api.getCycles()
      .then(data => { setCycles(data || []); setError(null) })
      .catch(err  => { setCycles([]); console.error('Failed to load cycles:', err); setError(err.message) })

  // Initial fetch
  useEffect(() => {
    fetchCycles().finally(() => setLoading(false))
  }, [])

  // Live timer — increments every second for running card elapsed display
  useEffect(() => {
    const id = setInterval(() => setLiveTimer(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  // Silent auto-refresh every 30s
  useEffect(() => {
    const id = setInterval(fetchCycles, 30_000)
    return () => clearInterval(id)
  }, [])

  const handleRetry = () => {
    setLoading(true)
    setError(null)
    fetchCycles().finally(() => setLoading(false))
  }

  async function handleResume(cycle) {
    setResuming(cycle.cycle_code)
    try {
      await api.resumeCycle(cycle.cycle_code)
      // Optimistically update local state without waiting for next poll
      setCycles(prev =>
        prev.map(c =>
          c.cycle_code === cycle.cycle_code
            ? { ...c, status: 'planned' }
            : c
        )
      )
    } catch (err) {
      console.error('Resume failed:', err.message)
      alert(`Could not resume cycle: ` + err.message)
    } finally {
      setResuming(null)
    }
  }

  const displayCycles = cycles

  // Counts for filter pills
  const counts = {
    running:      displayCycles.filter(c => c.status === 'running').length,
    needs_review: displayCycles.filter(c => c.status === 'needs_review').length,
    complete:     displayCycles.filter(c => c.status === 'complete').length,
    planned:      displayCycles.filter(c => c.status === 'planned').length,
    failed:       displayCycles.filter(c => c.status === 'failed').length,
  }

  const filtered = activeFilter === 'all'
    ? displayCycles
    : displayCycles.filter(c => c.status === activeFilter)

  const cardBody = (cycle) => {
    if (cycle.status === 'running')      return <RunningBody      cycle={cycle} onViewCycle={onViewCycle} key={liveTimer} />
    if (cycle.status === 'needs_review') return <NeedsReviewBody  cycle={cycle} onViewCycle={onViewCycle} />
    if (cycle.status === 'complete')     return <CompleteBody      cycle={cycle} onViewCycle={onViewCycle} />
    if (cycle.status === 'failed')       return <FailedBody        cycle={cycle} onViewCycle={onViewCycle} onResume={handleResume} resuming={resuming} />
    return <PlannedBody cycle={cycle} onViewCycle={onViewCycle} />
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        * { box-sizing: border-box; }
      `}</style>

      <Sidebar activeView="dashboard" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200 }}>
        <Topbar />

        <div style={{ flex: 1, overflowY: 'auto', padding: 32 }}>
          {/* Page header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
            <div>
              <h1 style={{ margin: '0 0 6px', fontSize: 28, fontWeight: 700, color: T.text }}>Cycle Management</h1>
              <p style={{ margin: 0, fontSize: 14, color: T.slate, maxWidth: 540 }}>
                Monitor and manage automated brand studies. Deploy new algorithmic cycles to track market share shifts in real-time.
              </p>
            </div>
            <button
              onClick={onNewCycle}
              style={{ padding: '10px 20px', background: T.text, color: T.white, border: 'none', borderRadius: 8, fontWeight: 700, fontSize: 14, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
            >
              + New Cycle
            </button>
          </div>

          {/* Filter pills */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
            <FilterPill
              label="All"
              count={displayCycles.length}
              active={activeFilter === 'all'}
              onClick={() => setActiveFilter('all')}
            />
            {counts.running > 0 && (
              <FilterPill label="Running" count={counts.running} dotColor={STATUS.running.dot} active={activeFilter === 'running'} onClick={() => setActiveFilter('running')} />
            )}
            {counts.needs_review > 0 && (
              <FilterPill label="Needs Review" count={counts.needs_review} dotColor={STATUS.needs_review.dot} active={activeFilter === 'needs_review'} onClick={() => setActiveFilter('needs_review')} />
            )}
            {counts.complete > 0 && (
              <FilterPill label="Complete" count={counts.complete} dotColor={STATUS.complete.dot} active={activeFilter === 'complete'} onClick={() => setActiveFilter('complete')} />
            )}
            {counts.planned > 0 && (
              <FilterPill label="Planned" count={counts.planned} dotColor={STATUS.planned.dot} active={activeFilter === 'planned'} onClick={() => setActiveFilter('planned')} />
            )}
            {counts.failed > 0 && (
              <FilterPill label="Failed" count={counts.failed} dotColor={STATUS.failed.dot} active={activeFilter === 'failed'} onClick={() => setActiveFilter('failed')} />
            )}
          </div>

          {/* Error state */}
          {error && !loading && (
            <div style={{ textAlign: 'center', padding: 64 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>⚠</div>
              <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 700, color: T.text }}>Could not load cycles</h3>
              <p style={{ margin: '0 0 20px', fontSize: 13, color: T.slate }}>{error}</p>
              <button onClick={handleRetry}
                style={{ padding: '10px 24px', background: T.navy, color: T.white, border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
                Try Again
              </button>
            </div>
          )}

          {/* Card grid */}
          {!error && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
              {loading
                ? [0, 1, 2, 3, 4, 5].map(i => <SkeletonCard key={i} delay={i * 0.1} />)
                : (
                  <>
                    {filtered.length === 0 ? (
                      <div style={{
                        gridColumn: '1 / -1',
                        textAlign: 'center',
                        padding: '60px 20px',
                        color: T.slate,
                        fontSize: '14px',
                      }}>
                        <div style={{ fontSize: '32px', marginBottom: '12px' }}>○</div>
                        <div style={{ fontWeight: '600', fontSize: '15px', color: T.textMid, marginBottom: '8px' }}>
                          No cycles yet
                        </div>
                        <div style={{ fontSize: '13px', color: T.slate }}>
                          Create a new cycle to start collecting SoA data.
                        </div>
                      </div>
                    ) : (
                      <>
                        {filtered.map(cycle => (
                          <CycleCard key={cycle.cycle_code} cycle={cycle} onClick={() => onViewCycle && onViewCycle(cycle.cycle_code)}>
                            {cardBody(cycle)}
                          </CycleCard>
                        ))}
                        {activeFilter === 'all' && (
                          <EmptySlotCard onNewCycle={onNewCycle} />
                        )}
                      </>
                    )}
                  </>
                )
              }
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
