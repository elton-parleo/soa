import React, { useState, useEffect } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'

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

const PLATFORM_META = {
  chatgpt:    { icon: '🤖', color: '#10B981', label: 'ChatGPT' },
  gemini:     { icon: '✦',  color: '#4F46E5', label: 'Gemini' },
  claude:     { icon: '◈',  color: '#F59E0B', label: 'Claude' },
  perplexity: { icon: '🔍', color: '#0EA5E9', label: 'Perplexity' },
}

const STRENGTH_STYLES = {
  Positive: { color: '#D97706' },
  Primary:  { color: '#16A34A' },
  Negative: { color: '#DC2626' },
  Neutral:  { color: '#64748B' },
}

const CODE_COLORS = {
  M001: '#0D9488',
  M002: '#4F46E5',
  M003: '#F59E0B',
  M004: '#DC2626',
  M005: '#8B5CF6',
}

function codeColor(code) {
  return CODE_COLORS[code] || '#64748B'
}

function ordinal(n) {
  if (!n && n !== 0) return '—'
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

function highlightResponse(text, mentions) {
  if (!text) return null
  if (!mentions?.length)
    return (
      <p style={{ fontSize: '14px', lineHeight: '1.7', color: T.text, margin: 0 }}>
        {text}
      </p>
    )

  const sorted = [...mentions]
    .filter(m => m.entity_name)
    .sort((a, b) => (b.entity_name?.length || 0) - (a.entity_name?.length || 0))

  let segments = [text]
  sorted.forEach(mention => {
    const name = mention.entity_name
    const isPrimary = mention.role === 'primary' || mention.strength_label === 'Primary'
    segments = segments.flatMap(seg => {
      if (typeof seg !== 'string') return [seg]
      const parts = seg.split(
        new RegExp(`(${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
      )
      return parts.map((p, i) => {
        if (i % 2 === 0) return p
        return isPrimary
          ? <strong key={i} style={{ fontWeight: 700, textDecoration: 'underline' }}>{p}</strong>
          : <mark key={i} style={{ background: '#DCFCE7', color: '#14532D', borderRadius: '4px', padding: '1px 4px', fontWeight: 600 }}>{p}</mark>
      })
    })
  })

  return (
    <p style={{ fontSize: '14px', lineHeight: '1.7', color: T.text, margin: 0 }}>
      {segments}
    </p>
  )
}

function Toggle({ value, onChange }) {
  return (
    <div
      onClick={() => onChange(!value)}
      style={{
        position: 'relative', width: 36, height: 20,
        borderRadius: 10, background: value ? T.teal : T.border,
        cursor: 'pointer', transition: 'background 0.15s', flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute', top: 2, left: value ? 16 : 2,
        width: 16, height: 16, borderRadius: '50%', background: T.white,
        transition: 'left 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </div>
  )
}

function SkeletonRunCard({ delay }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: `1px solid ${T.border}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ width: 140, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: T.border, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{ width: 80, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
        <div style={{ width: 50, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
      </div>
    </div>
  )
}

function SelectControl({ label, value, onChange, options, width }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
        {label}
      </span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width, padding: '7px 10px', fontSize: 13, border: `1px solid ${T.border}`,
          borderRadius: 6, background: T.white, color: T.text,
          fontFamily: 'inherit', outline: 'none', cursor: 'pointer',
        }}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

export default function ResponseExplorer({ cycleCode, onNavigate }) {
  const [runs, setRuns]                   = useState([])
  const [total, setTotal]                 = useState(0)
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState(null)
  const [selectedRun, setSelectedRun]     = useState(null)
  const [mentions, setMentions]           = useState([])
  const [mentionsLoading, setMentionsLoading] = useState(false)

  const [platformFilter, setPlatformFilter] = useState('all')
  const [stageFilter, setStageFilter]       = useState('all')
  const [entitySearch, setEntitySearch]     = useState('')
  const [dealCited, setDealCited]           = useState(false)
  const [needsReview, setNeedsReview]       = useState(false)

  useEffect(() => {
    if (!cycleCode) return
    setLoading(true)
    setError(null)
    setSelectedRun(null)
    setMentions([])

    api.getCycleRuns(cycleCode, {
      platform:     platformFilter,
      stage:        stageFilter,
      entity:       entitySearch || undefined,
      deal_cited:   dealCited || undefined,
      needs_review: needsReview || undefined,
    })
      .then(data => {
        const runsData = data.runs || []
        setRuns(runsData)
        setTotal(data.total || 0)
        if (runsData.length > 0) setSelectedRun(runsData[0])
      })
      .catch(err => {
        setError(err.message)
        setRuns([])
        setTotal(0)
      })
      .finally(() => setLoading(false))
  }, [cycleCode, platformFilter, stageFilter, entitySearch, dealCited, needsReview])

  useEffect(() => {
    if (!selectedRun) { setMentions([]); return }
    setMentionsLoading(true)
    api.getRunMentions(cycleCode, selectedRun.run_id)
      .then(data => setMentions(data.mentions || []))
      .catch(() => setMentions([]))
      .finally(() => setMentionsLoading(false))
  }, [selectedRun?.run_id])

  const hasFilters = platformFilter !== 'all' || stageFilter !== 'all' || entitySearch || dealCited || needsReview

  const avgConfidence = (() => {
    if (mentionsLoading || mentions.length === 0) return null
    const scores = mentions.map(m => m.confidence_score).filter(v => v != null)
    if (scores.length === 0) return null
    return Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
  })()

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        @keyframes rePulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
        * { box-sizing: border-box; }
        .re-run-card:hover { background: ${T.offWhite} !important; }
        .re-breadcrumb:hover { color: ${T.textMid} !important; }
      `}</style>

      <Sidebar activeView="dashboard" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200, overflow: 'hidden' }}>

        {/* Topbar */}
        <div style={{
          height: 56, background: T.white, borderBottom: `1px solid ${T.border}`,
          display: 'flex', alignItems: 'center', padding: '0 28px', flexShrink: 0,
        }}>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontSize: 13, color: T.slate, display: 'flex', alignItems: 'center', gap: 4 }}>
              <span
                className="re-breadcrumb"
                onClick={() => onNavigate && onNavigate('dashboard')}
                style={{ cursor: 'pointer', color: T.slate, transition: 'color 0.1s' }}
              >Cycles</span>
              <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
              <span
                className="re-breadcrumb"
                onClick={() => onNavigate && onNavigate('metrics', { cycleCode })}
                style={{ cursor: 'pointer', color: T.slate, transition: 'color 0.1s', fontFamily: 'monospace', fontSize: 12 }}
              >{cycleCode}</span>
              <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
              <span style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.textMid }}>
                RESPONSE EXPLORER
              </span>
            </div>
            <div style={{ fontSize: 28, fontWeight: 700, color: T.text, marginTop: 2, lineHeight: 1 }}>
              Response Explorer
            </div>
          </div>
        </div>

        {/* Filter bar */}
        <div style={{
          background: T.white, borderBottom: `1px solid ${T.border}`,
          padding: '16px 28px', display: 'flex', alignItems: 'flex-end',
          gap: 16, flexWrap: 'wrap', flexShrink: 0,
        }}>
          <SelectControl
            label="PLATFORM" value={platformFilter} onChange={setPlatformFilter} width={160}
            options={[
              { value: 'all',        label: 'All Platforms' },
              { value: 'chatgpt',    label: 'ChatGPT' },
              { value: 'gemini',     label: 'Gemini' },
              { value: 'claude',     label: 'Claude' },
              { value: 'perplexity', label: 'Perplexity' },
            ]}
          />
          <SelectControl
            label="STAGE" value={stageFilter} onChange={setStageFilter} width={140}
            options={[
              { value: 'all',          label: 'All Stages' },
              { value: 'Research',     label: 'Research' },
              { value: 'Comparison',   label: 'Comparison' },
              { value: 'Ready to Buy', label: 'Ready to Buy' },
            ]}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
              ENTITY
            </span>
            <input
              type="text"
              value={entitySearch}
              onChange={e => setEntitySearch(e.target.value)}
              placeholder="Search entity..."
              style={{
                width: 180, padding: '7px 10px', fontSize: 13,
                border: `1px solid ${T.border}`, borderRadius: 6,
                background: T.white, color: T.text, fontFamily: 'inherit', outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 20, paddingBottom: 2 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                DEAL CITED
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Toggle value={dealCited} onChange={setDealCited} />
                <span style={{ fontSize: 12, color: T.text }}>Deal Cited</span>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                NEEDS REVIEW
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Toggle value={needsReview} onChange={setNeedsReview} />
                <span style={{ fontSize: 12, color: T.text }}>Needs Review</span>
              </div>
            </div>
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div style={{ textAlign: 'center', padding: '60px 20px' }}>
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>⚠</div>
            <div style={{ fontWeight: '600', fontSize: '15px', color: T.text, marginBottom: '8px' }}>
              Could not load runs
            </div>
            <div style={{ fontSize: '13px', color: T.slate }}>{error}</div>
          </div>
        )}

        {/* Main content */}
        {!error && (
          <div style={{ display: 'flex', flex: 1, overflow: 'hidden', borderTop: `1px solid ${T.border}` }}>

            {/* Left panel */}
            <div style={{ width: 320, flexShrink: 0, background: T.white, borderRight: `1px solid ${T.border}`, overflowY: 'auto', height: '100%' }}>
              <div style={{
                padding: '12px 16px', borderBottom: `1px solid ${T.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                  ACTIVE RUNS ({total})
                </span>
                <span style={{ fontSize: 16, color: T.slate, cursor: 'pointer' }}>⇅</span>
              </div>

              {loading && (
                <>
                  {[0, 0.08, 0.16, 0.24, 0.32, 0.40].map((delay, i) => (
                    <SkeletonRunCard key={i} delay={delay} />
                  ))}
                </>
              )}

              {!loading && runs.length === 0 && (
                <div style={{ padding: '40px 16px', textAlign: 'center' }}>
                  <div style={{ fontSize: '28px', marginBottom: '10px', color: T.slate }}>◎</div>
                  <div style={{ fontSize: '13px', fontWeight: '600', color: T.textMid, marginBottom: '6px' }}>
                    No runs found
                  </div>
                  <div style={{ fontSize: '12px', color: T.slate, lineHeight: '1.5' }}>
                    {hasFilters
                      ? 'Try adjusting the filters above.'
                      : 'This cycle has no runs yet.'
                    }
                  </div>
                </div>
              )}

              {!loading && runs.map(run => {
                const isSelected = selectedRun?.run_id === run.run_id
                const pm = PLATFORM_META[run.platform]
                const statusColor =
                  run.status === 'success' || run.status === 'complete' || run.status === 'completed'
                    ? '#16A34A'
                    : run.status === 'failed'
                      ? '#DC2626'
                      : '#94A3B8'

                return (
                  <div
                    key={run.run_id}
                    className="re-run-card"
                    onClick={() => setSelectedRun(run)}
                    style={{
                      padding: '12px 16px',
                      borderBottom: `1px solid ${T.border}`,
                      borderLeft: `3px solid ${isSelected ? T.navy : 'transparent'}`,
                      background: isSelected ? T.offWhite : T.white,
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 500, color: T.text, letterSpacing: '0.03em', wordBreak: 'break-all' }}>
                        {run.query_code || '—'}
                      </span>
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: statusColor, flexShrink: 0, marginLeft: 8, marginTop: 1 }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span style={{ fontSize: 14, color: pm?.color || T.slate }}>{pm?.icon || '?'}</span>
                        <span style={{ fontSize: 12, color: T.slate, marginLeft: 4 }}>{pm?.label || run.platform}</span>
                      </div>
                      <span style={{
                        background: T.offWhite, border: `1px solid ${T.border}`,
                        borderRadius: 4, padding: '2px 6px', fontSize: 11,
                        fontWeight: 600, color: T.textMid,
                      }}>
                        {run.run_number != null && run.runs_per_query != null
                          ? `Run ${run.run_number}/${run.runs_per_query}`
                          : 'Run —'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Right panel */}
            <div style={{ flex: 1, background: T.offWhite, overflowY: 'auto', height: '100%' }}>
              {!selectedRun && !loading && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: T.slate, gap: 10 }}>
                  <div style={{ fontSize: '28px' }}>←</div>
                  <div style={{ fontSize: '13px', color: T.slate }}>Select a run to explore its response</div>
                </div>
              )}

              {selectedRun && (
                <div style={{ padding: 24 }}>

                  {/* Card 1 — User Query */}
                  <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: '20px 24px', marginBottom: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14, color: T.slate }}>👤</span>
                      <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: T.slate }}>
                        USER QUERY
                      </span>
                    </div>
                    <div style={{
                      marginTop: 12, background: T.offWhite, border: `1px solid ${T.border}`,
                      borderRadius: 8, padding: '14px 16px', fontSize: 14,
                      fontStyle: 'italic', color: T.text, lineHeight: 1.6,
                    }}>
                      {selectedRun.query_text
                        ? `"${selectedRun.query_text}"`
                        : <span style={{ color: T.slate }}>No query text available</span>
                      }
                    </div>
                  </div>

                  {/* Card 2 — Raw Agent Response + Coded Mentions */}
                  <div style={{ background: T.white, border: `1px solid ${T.border}`, borderRadius: 12, padding: '20px 24px', marginTop: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <div style={{
                          width: 28, height: 28, background: T.navy, borderRadius: 8,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 11, fontWeight: 700, color: T.white,
                        }}>AI</div>
                        <span style={{ fontSize: 16, fontWeight: 600, color: T.text, marginLeft: 10 }}>
                          Raw Agent Response
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: T.slate }}>STRENGTH:</span>
                        <span style={{
                          background: '#FEF3C7', color: '#D97706',
                          fontSize: 14, fontWeight: 700, padding: '4px 10px',
                          borderRadius: 6, marginLeft: 6,
                        }}>
                          {mentionsLoading ? '...' : avgConfidence != null ? `${avgConfidence} / 100` : '—'}
                        </span>
                      </div>
                    </div>

                    <div style={{ marginTop: 16 }}>
                      {selectedRun.raw_response
                        ? highlightResponse(selectedRun.raw_response, mentions)
                        : (
                          <div style={{ padding: 20, textAlign: 'center', color: T.slate, fontSize: 13, background: T.offWhite, borderRadius: 8, border: `1px solid ${T.border}` }}>
                            No response text recorded
                          </div>
                        )
                      }
                    </div>

                    {/* Coded Mentions section */}
                    <div style={{ marginTop: 20, paddingTop: 16, borderTop: `1px solid ${T.border}` }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: T.slate }}>
                          CODED MENTIONS &amp; ENTITY ANALYSIS
                        </span>
                        {mentions.length > 0 && (
                          <span style={{ background: T.navy, color: T.white, fontSize: 11, fontWeight: 700, borderRadius: 99, padding: '3px 10px' }}>
                            {mentions.length} Entities Identified
                          </span>
                        )}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                          <span
                            onClick={() => {}}
                            style={{ fontSize: 13, color: T.slate, cursor: 'pointer', textDecoration: 'underline' }}
                          >
                            ✎ Override Coding
                          </span>
                          <button
                            onClick={() => {}}
                            style={{
                              background: '#16A34A', color: T.white, fontSize: 12, fontWeight: 700,
                              border: 'none', borderRadius: 6, padding: '6px 12px',
                              cursor: 'pointer', fontFamily: 'inherit',
                            }}
                          >
                            ✓ Mark as Reviewed
                          </button>
                        </div>
                      </div>

                      {mentionsLoading && (
                        <div>
                          {[0, 0.08, 0.16].map((delay, i) => (
                            <div key={i} style={{ height: 40, borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 12, padding: '0 8px' }}>
                              <div style={{ width: 60, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
                              <div style={{ width: 100, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
                              <div style={{ width: 60, height: 10, background: T.border, borderRadius: 4, animation: `rePulse 1.5s ease-in-out ${delay}s infinite` }} />
                            </div>
                          ))}
                        </div>
                      )}

                      {!mentionsLoading && mentions.length === 0 && (
                        <div style={{ padding: '20px', textAlign: 'center', color: T.slate, fontSize: 13 }}>
                          No entity mentions coded for this run
                        </div>
                      )}

                      {!mentionsLoading && mentions.length > 0 && (
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ background: T.offWhite, height: 36, borderBottom: `1px solid ${T.border}` }}>
                              {[
                                { label: 'ENTITY ID',   width: 80 },
                                { label: 'ENTITY NAME', width: null },
                                { label: 'POSITION',    width: 90 },
                                { label: 'STRENGTH',    width: 110 },
                                { label: 'DEAL',        width: 70 },
                                { label: 'CONFIDENCE',  width: 150 },
                              ].map(col => (
                                <th key={col.label} style={{
                                  width: col.width, textAlign: 'left', padding: '0 8px',
                                  fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                                  letterSpacing: '0.06em', color: T.slate,
                                }}>
                                  {col.label}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {mentions.map(m => (
                              <tr key={m.id} style={{ height: 48, borderBottom: `1px solid ${T.border}` }}>
                                <td style={{ padding: '0 8px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: codeColor(m.comparison_code), flexShrink: 0 }} />
                                    <span style={{ fontFamily: 'monospace', fontSize: 11, color: T.textMid }}>{m.comparison_code || '—'}</span>
                                  </div>
                                </td>
                                <td style={{ padding: '0 8px', fontSize: 13, fontWeight: 600, color: T.text }}>
                                  {m.entity_name || '—'}
                                </td>
                                <td style={{ padding: '0 8px', fontSize: 13, color: T.textMid }}>
                                  {ordinal(m.position)}
                                </td>
                                <td style={{ padding: '0 8px', fontSize: 13, fontWeight: 700, color: STRENGTH_STYLES[m.strength_label]?.color || T.slate }}>
                                  {m.strength_label || '—'}
                                </td>
                                <td style={{ padding: '0 8px', textAlign: 'center' }}>
                                  {m.deal_cited === true
                                    ? (
                                      <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#DCFCE7', color: '#16A34A', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>✓</div>
                                    )
                                    : (
                                      <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#F3F4F6', color: '#9CA3AF', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>✗</div>
                                    )
                                  }
                                </td>
                                <td style={{ padding: '0 8px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <div style={{ width: 80, height: 6, background: T.border, borderRadius: 3, overflow: 'hidden' }}>
                                      <div style={{ width: `${m.confidence_score || 0}%`, height: '100%', background: T.navy, borderRadius: 3, transition: 'width 0.3s ease' }} />
                                    </div>
                                    <span style={{ fontSize: 11, color: T.slate }}>
                                      {m.confidence_score != null ? `${m.confidence_score}%` : '—'}
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
