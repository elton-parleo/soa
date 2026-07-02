import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'

// ─── Design tokens (verbatim from MetricsDashboard.jsx) ──────────────────────
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
}

const STATUS_OPTIONS = ['proposed', 'accepted', 'in_progress', 'done', 'dismissed']

const OWNER_BADGE = {
  brand:    { label: 'Brand',    bg: T.tealLight,  fg: T.teal },
  retailer: { label: 'Retailer', bg: T.amberLight, fg: T.amber },
  joint:    { label: 'Joint',    bg: '#EDE9FE',     fg: T.indigo },
}

const EFFORT_BADGE = {
  low:    { label: 'Low effort',    bg: T.greenLight, fg: T.green },
  medium: { label: 'Medium effort', bg: T.amberLight, fg: T.amber },
  high:   { label: 'High effort',   bg: T.redLight,   fg: T.red },
}

function Badge({ label, bg, fg }) {
  return (
    <span style={{
      display: 'inline-block', padding: '3px 10px', borderRadius: 999,
      background: bg, color: fg, fontSize: 11, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.04em',
    }}>
      {label}
    </span>
  )
}

export default function ActionsPage({ cycleCode, onNavigate }) {
  const [cycleData,      setCycleData]      = useState(null)
  const [allCycles,      setAllCycles]      = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [loading,        setLoading]        = useState(true)
  const [generating,     setGenerating]     = useState(false)
  const [error,          setError]          = useState(null)
  const [showSuppressed, setShowSuppressed] = useState(false)
  const [expanded,       setExpanded]       = useState({})
  const [evidenceOpen,   setEvidenceOpen]   = useState({})

  const loadRecommendations = useCallback((cycleId, includeSuppressed) => {
    setLoading(true)
    setError(null)
    api.getRecommendations(cycleId, { includeSuppressed })
      .then(recs => setRecommendations(recs))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!cycleCode) {
      setCycleData(null)
      setRecommendations([])
      setLoading(false)
      return
    }
    setLoading(true)
    Promise.all([api.getCycle(cycleCode), api.getCycles()])
      .then(([cycle, cycles]) => {
        setCycleData(cycle)
        setAllCycles(Array.isArray(cycles) ? cycles : [])
        if (cycle?.id != null) {
          loadRecommendations(cycle.id, showSuppressed)
        } else {
          setLoading(false)
        }
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cycleCode])

  useEffect(() => {
    if (cycleData?.id != null) {
      loadRecommendations(cycleData.id, showSuppressed)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showSuppressed])

  async function handleGenerate() {
    if (!cycleData?.id) return
    setGenerating(true)
    setError(null)
    try {
      await api.generateActions(cycleData.id)
      loadRecommendations(cycleData.id, showSuppressed)
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  async function handleStatusChange(rec, status) {
    const prev = rec.status
    setRecommendations(list => list.map(r => r.id === rec.id ? { ...r, status } : r))
    try {
      await api.updateRecommendation(rec.id, status)
    } catch (err) {
      setRecommendations(list => list.map(r => r.id === rec.id ? { ...r, status: prev } : r))
      alert(`Could not update status: ${err.message}`)
    }
  }

  function viewEvidence(runId) {
    onNavigate && onNavigate('responses', { cycleCode, runId })
  }

  const visible = recommendations.filter(r => showSuppressed || !r.suppressed)
  const sorted = [...visible].sort((a, b) => b.priority_score - a.priority_score)
  const displayCode = cycleCode || '—'

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'DM Sans', sans-serif", background: T.offWhite }}>
      <style>{`
        * { box-sizing: border-box; }
        .ac-breadcrumb:hover { color: ${T.textMid} !important; }
        .ac-card:hover { border-color: ${T.borderDark} !important; }
        @keyframes acSpin { to { transform: rotate(360deg); } }
      `}</style>

      <Sidebar activeView="dashboard" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200 }}>

        {/* Topbar */}
        <div style={{
          height: 56, background: T.white, borderBottom: `1px solid ${T.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 28px', flexShrink: 0,
        }}>
          <div style={{ fontSize: 13, color: T.slate, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="ac-breadcrumb" onClick={() => onNavigate && onNavigate('dashboard')}
              style={{ color: T.slate, cursor: 'pointer', transition: 'color 0.1s' }}>Cycles</span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span className="ac-breadcrumb" onClick={() => onNavigate && onNavigate('metrics', { cycleCode })}
              style={{ color: T.slate, cursor: 'pointer', transition: 'color 0.1s', fontFamily: 'monospace', fontSize: 12 }}>
              {displayCode}
            </span>
            <span style={{ color: T.slateLight, margin: '0 2px' }}>›</span>
            <span style={{ color: T.text, fontWeight: 700 }}>Actions</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.slate, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={showSuppressed}
                onChange={e => setShowSuppressed(e.target.checked)}
              />
              Show composite outcomes
            </label>
            <div style={{ position: 'relative' }}>
              <select
                value={displayCode}
                onChange={e => onNavigate && onNavigate('actions', { cycleCode: e.target.value })}
                style={{
                  background: T.navy, color: T.white, border: 'none', borderRadius: 8,
                  padding: '8px 28px 8px 14px', fontSize: 13, fontWeight: 600,
                  cursor: 'pointer', appearance: 'none', outline: 'none',
                }}
              >
                {allCycles.length > 0
                  ? allCycles.map(c => <option key={c.cycle_code} value={c.cycle_code}>Cycle: {c.cycle_code}</option>)
                  : <option value={displayCode}>Cycle: {displayCode}</option>
                }
              </select>
              <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', color: T.slateLight, fontSize: 10, pointerEvents: 'none' }}>▾</span>
            </div>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, padding: '28px', overflow: 'auto' }}>
          {error && (
            <div style={{
              background: T.redLight, color: T.red, padding: '12px 16px',
              borderRadius: 8, fontSize: 13, marginBottom: 20,
            }}>
              {error}
            </div>
          )}

          {loading && (
            <div style={{ textAlign: 'center', padding: '80px 20px', color: T.slate, fontSize: 13 }}>
              Loading…
            </div>
          )}

          {!loading && sorted.length === 0 && (
            <div style={{
              textAlign: 'center', padding: '80px 20px', background: T.white,
              border: `1px solid ${T.border}`, borderRadius: 12,
            }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 8 }}>
                No recommendations for this cycle yet
              </div>
              <div style={{ fontSize: 13, color: T.slate, marginBottom: 20 }}>
                Run the finding detector and recommendation mapper against this cycle's metrics.
              </div>
              <button
                onClick={handleGenerate}
                disabled={generating || !cycleData?.id}
                style={{
                  padding: '10px 20px', background: T.navy, color: T.white, border: 'none',
                  borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: generating ? 'not-allowed' : 'pointer',
                  opacity: generating ? 0.7 : 1,
                }}
              >
                {generating ? 'Generating…' : 'Generate recommendations'}
              </button>
            </div>
          )}

          {!loading && sorted.length > 0 && (
            <>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
                <button
                  onClick={handleGenerate}
                  disabled={generating}
                  style={{
                    padding: '8px 16px', background: T.white, color: T.text,
                    border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 12,
                    fontWeight: 600, cursor: generating ? 'not-allowed' : 'pointer',
                  }}
                >
                  {generating ? 'Regenerating…' : '↻ Regenerate'}
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {sorted.map(rec => {
                  const owner = OWNER_BADGE[rec.owner] || OWNER_BADGE.brand
                  const effort = EFFORT_BADGE[rec.effort] || EFFORT_BADGE.medium
                  const isExpanded = !!expanded[rec.id]
                  const isEvidenceOpen = !!evidenceOpen[rec.id]
                  const evidenceIds = rec.evidence_run_ids || []

                  return (
                    <div
                      key={rec.id}
                      className="ac-card"
                      style={{
                        background: T.white, border: `1px solid ${T.border}`, borderRadius: 12,
                        padding: '18px 20px', opacity: rec.suppressed ? 0.7 : 1,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              {rec.pillar}
                            </span>
                            <span style={{ fontSize: 11, color: T.slateLight, fontFamily: 'monospace' }}>{rec.play_id}</span>
                            {rec.suppressed && <Badge label="Suppressed" bg={T.border} fg={T.slate} />}
                          </div>
                          <div style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 8 }}>
                            {rec.play_text.split('.')[0]}.
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                            <Badge {...owner} />
                            <Badge {...effort} />
                            <span style={{ fontSize: 12, color: T.slate }}>
                              Priority <b style={{ color: T.text }}>{rec.priority_score.toFixed(2)}</b>
                            </span>
                            <span style={{ fontSize: 12, color: T.slate }}>
                              {rec.cells_affected} cell{rec.cells_affected === 1 ? '' : 's'} affected
                            </span>
                          </div>
                        </div>

                        <select
                          value={rec.status}
                          onChange={e => handleStatusChange(rec, e.target.value)}
                          style={{
                            padding: '7px 10px', borderRadius: 6, border: `1px solid ${T.border}`,
                            fontSize: 12, fontWeight: 600, color: T.text, background: T.white,
                            cursor: 'pointer', flexShrink: 0,
                          }}
                        >
                          {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                        </select>
                      </div>

                      <div style={{ marginTop: 12, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                        <button
                          onClick={() => setExpanded(prev => ({ ...prev, [rec.id]: !prev[rec.id] }))}
                          style={{
                            background: 'none', border: 'none', color: T.teal, fontSize: 12,
                            fontWeight: 600, cursor: 'pointer', padding: 0,
                          }}
                        >
                          {isExpanded ? '▾ Hide details' : '▸ Play + mechanism'}
                        </button>

                        {evidenceIds.length > 0 && (
                          <button
                            onClick={() => {
                              if (evidenceIds.length === 1) {
                                viewEvidence(evidenceIds[0])
                              } else {
                                setEvidenceOpen(prev => ({ ...prev, [rec.id]: !prev[rec.id] }))
                              }
                            }}
                            style={{
                              background: 'none', border: 'none', color: T.indigo, fontSize: 12,
                              fontWeight: 600, cursor: 'pointer', padding: 0,
                            }}
                          >
                            View evidence ({evidenceIds.length} run{evidenceIds.length === 1 ? '' : 's'})
                          </button>
                        )}
                      </div>

                      {isExpanded && (
                        <div style={{ marginTop: 12, padding: '12px 14px', background: T.offWhite, borderRadius: 8, fontSize: 13, color: T.textMid, lineHeight: 1.5 }}>
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ fontSize: 11, fontWeight: 700, color: T.slate, textTransform: 'uppercase', marginBottom: 4 }}>Play</div>
                            {rec.play_text}
                          </div>
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ fontSize: 11, fontWeight: 700, color: T.slate, textTransform: 'uppercase', marginBottom: 4 }}>Mechanism</div>
                            {rec.mechanism_text}
                          </div>
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 700, color: T.slate, textTransform: 'uppercase', marginBottom: 4 }}>Expected impact</div>
                            {rec.expected_impact_text}
                          </div>
                        </div>
                      )}

                      {isEvidenceOpen && evidenceIds.length > 1 && (
                        <div style={{ marginTop: 10, padding: '10px 14px', background: T.offWhite, borderRadius: 8 }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: T.slate, textTransform: 'uppercase', marginBottom: 6 }}>
                            Evidence runs
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {evidenceIds.map(runId => (
                              <span
                                key={runId}
                                onClick={() => viewEvidence(runId)}
                                style={{
                                  padding: '3px 8px', borderRadius: 6, background: T.white,
                                  border: `1px solid ${T.border}`, fontSize: 11, fontFamily: 'monospace',
                                  color: T.indigo, cursor: 'pointer',
                                }}
                              >
                                #{runId}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
