import { useState, useEffect } from 'react'
import { api } from '../api.js'
import Sidebar from './Sidebar.jsx'

// ─── Design tokens (verbatim from CycleDashboard.jsx) ────────────────────────
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

// ─── Query status tokens — keys match DB values (Active / Paused / Retired) ───
const QUERY_STATUS = {
  Active: {
    label: 'ACTIVE',
    color: '#14532D',
    bg:    '#DCFCE7',
  },
  Paused: {
    label: 'PAUSED',
    color: '#92400E',
    bg:    '#FEF3C7',
  },
  Retired: {
    label: 'RETIRED',
    color: '#374151',
    bg:    '#F3F4F6',
  },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
// Known study_type → display name map (mirrors backend STUDY_TYPE_NAMES)
const STUDY_NAMES = {
  'brand_oral_b':             'Oral-B Brand Study',
  'brand_oral_b_100':         'Oral-B Extended Study',
  'brand_oral_b_unbranded':   'Oral-B Unbranded Study',
  'brand_oral_b_neutral':     'Oral-B Neutral Study',
  'brand_oral_b_etb_neutral': 'Oral-B ETB Neutral Study',
  'brand_gillette':           'Gillette Brand Study',
  'brand_gillette_100':       'Gillette 100 Study',
  'brand_gillette_unbranded': 'Gillette Unbranded Study',
  'retailer_sephora':         'Sephora Retailer Study',
}

function studyDisplayName(studyType) {
  if (!studyType) return ''
  if (STUDY_NAMES[studyType]) return STUDY_NAMES[studyType]
  // Fall back: title-case the underscored slug
  return studyType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const EMPTY_FORM = {
  query_text:  '',
  category:    '',
  stage:       'Research',
  specificity: 'Broad',
  persona:     '',
  status:      'Active',
}

// ─── Topbar ───────────────────────────────────────────────────────────────────
function Topbar({ studyName, onBack }) {
  return (
    <div style={{
      height: 56,
      background: T.white,
      borderBottom: `1px solid ${T.border}`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 32px',
      flexShrink: 0,
    }}>
      <div style={{ fontSize: 13, color: T.slate }}>
        <span
          style={{ color: T.teal, fontWeight: 500, cursor: 'pointer' }}
          onClick={onBack}
        >STUDIES</span>
        {' › '}
        <span style={{ color: T.text, fontWeight: 700 }}>{studyName}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 18, cursor: 'pointer' }}>🔔</span>
        <div style={{
          width: 32, height: 32,
          borderRadius: '50%',
          background: T.indigo,
          color: T.white,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 13,
          fontWeight: 700,
        }}>E</div>
      </div>
    </div>
  )
}

// ─── Query status badge ───────────────────────────────────────────────────────
function QueryStatusBadge({ status }) {
  const s = QUERY_STATUS[status] || QUERY_STATUS['Active']
  return (
    <span style={{
      padding: '4px 8px',
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 700,
      textTransform: 'uppercase',
      color: s.color,
      background: s.bg,
      whiteSpace: 'nowrap',
    }}>
      {s.label}
    </span>
  )
}

// ─── Field label style ────────────────────────────────────────────────────────
const labelStyle = {
  display: 'block',
  fontSize: 10,
  fontWeight: 700,
  color: T.slate,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  marginBottom: 6,
}

const inputStyle = {
  width: '100%',
  padding: '9px 12px',
  fontSize: 13,
  color: T.text,
  background: T.white,
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  outline: 'none',
  fontFamily: "'DM Sans', sans-serif",
}

const selectStyle = {
  ...inputStyle,
  cursor: 'pointer',
}

// ─── Constraint-driven select (used in slide-over form) ──────────────────────
function ConstrainedSelect({
  label,
  field,
  value,
  onChange,
  placeholder = 'Select...',
  constraints,
  constraintsLoading,
}) {
  const options = constraints[field] || []
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      <select
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        style={selectStyle}
      >
        <option value="">
          {constraintsLoading ? 'Loading...' : placeholder}
        </option>
        {options.map(opt => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function StudyDetail({ studyType, onNavigate }) {
  const [queries,             setQueries]             = useState([])
  const [loading,             setLoading]             = useState(true)
  const [slideOver,           setSlideOver]           = useState(null)
  const [stageFilter,         setStageFilter]         = useState('All')
  const [specificityFilter,   setSpecificityFilter]   = useState('All')
  const [personaFilter,       setPersonaFilter]       = useState('All')
  const [statusFilter,        setStatusFilter]        = useState('All')
  const [saving,              setSaving]              = useState(false)
  const [formData,            setFormData]            = useState(EMPTY_FORM)
  const [saveError,           setSaveError]           = useState(null)
  const [toast,               setToast]               = useState(null)
  const [genStatus,           setGenStatus]           = useState(null)
  const [constraints,         setConstraints]         = useState({})
  const [constraintsLoading,  setConstraintsLoading]  = useState(true)

  const studyName = studyDisplayName(studyType ?? '')

  useEffect(() => {
    if (!studyType) return
    setLoading(true)
    setConstraintsLoading(true)

    Promise.allSettled([
      api.getQueryRows(studyType),
      api.getQueryConstraints(),
    ]).then(([queriesResult, constraintsResult]) => {
      // Always use the real API result — an empty array is valid
      // (brand-new study mid-generation has zero queries so far)
      if (queriesResult.status === 'fulfilled') {
        setQueries(queriesResult.value || [])
      } else {
        setQueries([])
        console.error('Failed to load study queries:', queriesResult.reason)
      }

      // Handle constraints — graceful degradation if fetch fails
      if (
        constraintsResult.status === 'fulfilled' &&
        constraintsResult.value
      ) {
        setConstraints(constraintsResult.value)
      }

      setLoading(false)
      setConstraintsLoading(false)
    })
  }, [studyType])

  // Poll generation status every 3s while a job is active
  useEffect(() => {
    if (!studyType) return
    let cancelled = false
    let intervalId = null

    async function checkStatus() {
      try {
        const status = await api.getGenerationStatus(studyType)
        if (cancelled) return
        setGenStatus(status)

        if (status.status === 'running') {
          // Refresh queries incrementally as rows are inserted
          api.getQueryRows(studyType)
            .then(data => { if (!cancelled && data?.length > 0) setQueries(data) })
            .catch(() => {})
        }

        if (status.status === 'complete' || status.status === 'failed') {
          clearInterval(intervalId)
          if (status.status === 'complete') {
            api.getQueryRows(studyType)
              .then(data => { if (!cancelled && data?.length > 0) setQueries(data) })
              .catch(() => {})
          }
        }
      } catch (_) {
        // 404 = no generation job (CSV study or older study) — not an error
        if (!cancelled) {
          setGenStatus(null)
          clearInterval(intervalId)
        }
      }
    }

    checkStatus()
    intervalId = setInterval(checkStatus, 3000)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [studyType])

  // Derive unique persona values from loaded data for dynamic filter dropdown
  const personaOptions = [
    'All',
    ...Array.from(new Set(queries.map(q => q.persona).filter(Boolean))).sort(),
  ]

  // Apply all active filters
  const filteredQueries = queries.filter(q => {
    const matchStage   = stageFilter       === 'All' || q.stage === stageFilter
    const matchSpec    = specificityFilter === 'All' || q.specificity === specificityFilter
    const matchPersona = personaFilter     === 'All' || q.persona === personaFilter
    const matchStatus  = statusFilter      === 'All' || q.status === statusFilter
    return matchStage && matchSpec && matchPersona && matchStatus
  })

  // Auto-dismiss toast after 4 s
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(t)
  }, [toast])

  function openAdd() {
    setFormData(EMPTY_FORM)
    setSaveError(null)
    setSlideOver({ mode: 'add' })
  }

  function openEdit(query) {
    setFormData({
      query_text:  query.query_text  ?? '',
      category:    query.category    ?? '',
      stage:       query.stage       ?? 'Research',
      specificity: query.specificity ?? 'Broad',
      persona:     query.persona     ?? '',
      status:      query.status      ?? 'Active',
    })
    setSaveError(null)
    setSlideOver({ mode: 'edit', query })
  }

  async function handleSaveQuery() {
    if (!formData.query_text.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      if (slideOver?.mode === 'add') {
        const created = await api.createQuery(studyType, formData)
        setQueries(prev => [...prev, created])
        setToast('Query added successfully.')
      } else {
        const updated = await api.updateQuery(
          studyType,
          slideOver.query.query_code,
          formData,
        )
        setQueries(prev =>
          prev.map(q =>
            q.query_code === slideOver.query.query_code ? updated : q
          )
        )
        setToast('Query updated successfully.')
      }
      setSlideOver(null)
    } catch (err) {
      setSaveError(err.message ?? 'Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const filterSelectStyle = {
    padding: '7px 10px',
    fontSize: 13,
    color: T.text,
    background: T.white,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    cursor: 'pointer',
    outline: 'none',
  }

  // Table column config
  const COL_WIDTHS = {
    id:          200,  // widened for long codes e.g. GROOM_RES_BRD_CAS_01
    question:    null, // flex: 1
    category:    120,
    stage:       120,
    specificity: 110,
    persona:     110,
    status:      100,
  }

  const thStyle = (flex, width) => ({
    flex: flex ? 1 : undefined,
    minWidth: flex ? 0 : (width ?? undefined),
    width: width ?? undefined,
    flexShrink: flex ? 1 : 0,
    padding: '0 12px',
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: T.slate,
    textAlign: 'left',
    whiteSpace: 'nowrap',
  })

  const tdStyle = (flex, width) => ({
    flex: flex ? 1 : undefined,
    minWidth: flex ? 0 : (width ?? undefined),
    width: width ?? undefined,
    flexShrink: flex ? 1 : 0,
    padding: '0 12px',
  })

  return (
    <div style={{
      display: 'flex',
      minHeight: '100vh',
      fontFamily: "'DM Sans', sans-serif",
      background: T.offWhite,
    }}>
      <style>{`* { box-sizing: border-box; }`}</style>

      <Sidebar activeView="studies" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200 }}>
        <Topbar studyName={studyName} onBack={() => onNavigate && onNavigate('studies')} />

        <div style={{ flex: 1, overflowY: 'auto', padding: 32 }}>

          {/* Page header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 }}>
            <div>
              <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text }}>
                {studyName}
              </h1>
            </div>
            <button
              disabled
              title="Coming soon"
              style={{
                padding: '9px 18px',
                background: T.text,
                color: T.white,
                border: 'none',
                borderRadius: 8,
                fontWeight: 700,
                fontSize: 13,
                cursor: 'not-allowed',
                flexShrink: 0,
                opacity: 0.45,
                pointerEvents: 'none',
              }}
            >
              + Add Query
            </button>
          </div>

          {/* Generation progress banner */}
          {genStatus && genStatus.status !== 'complete' && (
            genStatus.status === 'failed' ? (
              <div style={{
                background: '#FEE2E2', border: '1px solid #FECACA',
                borderRadius: 8, padding: '12px 16px', marginBottom: 16,
                fontSize: 13, color: '#991B1B', fontWeight: 600,
              }}>
                Question generation failed: {genStatus.error_message || 'Unknown error'}
              </div>
            ) : (
              <>
                <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
                <div style={{
                  background: '#EFF6FF', border: '1px solid #BFDBFE',
                  borderRadius: 8, padding: '12px 16px', marginBottom: 16,
                  display: 'flex', alignItems: 'center', gap: 12,
                }}>
                  <div style={{
                    width: 16, height: 16, borderRadius: '50%',
                    border: '2px solid #BFDBFE', borderTopColor: '#2563EB',
                    animation: 'spin 0.8s linear infinite', flexShrink: 0,
                  }} />
                  <span style={{ fontSize: 13, color: '#1E40AF', fontWeight: 600 }}>
                    {genStatus.status === 'pending'
                      ? 'Queued — question generation will begin shortly.'
                      : `Generating questions... ${genStatus.created_count}/${genStatus.target_count} created`
                    }
                  </span>
                  {genStatus.status === 'running' && (
                    <div style={{
                      marginLeft: 'auto', width: 120, height: 6,
                      background: '#DBEAFE', borderRadius: 3, flexShrink: 0,
                    }}>
                      <div style={{
                        height: '100%', borderRadius: 3, background: '#2563EB',
                        width: `${(genStatus.created_count / genStatus.target_count) * 100}%`,
                        transition: 'width 0.4s ease',
                      }} />
                    </div>
                  )}
                </div>
              </>
            )
          )}

          {/* Tabs row */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${T.border}`, marginBottom: 20 }}>
            <div style={{
              padding: '10px 0',
              marginRight: 24,
              fontSize: 14,
              fontWeight: 600,
              color: T.text,
              borderBottom: `2px solid ${T.text}`,
              marginBottom: -1,
              cursor: 'pointer',
            }}>
              Queries
            </div>
          </div>

          {/* Filter bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: T.slate }}>Filter by:</span>
            {/* Stage */}
            <select value={stageFilter} onChange={e => setStageFilter(e.target.value)} style={filterSelectStyle}>
              <option value="All">Stage: All</option>
              {(constraints.stage || []).map(v => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            {/* Specificity */}
            <select value={specificityFilter} onChange={e => setSpecificityFilter(e.target.value)} style={filterSelectStyle}>
              <option value="All">Specificity: All</option>
              {(constraints.specificity || []).map(v => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            {/* Persona */}
            <select value={personaFilter} onChange={e => setPersonaFilter(e.target.value)} style={filterSelectStyle}>
              <option value="All">Persona: All</option>
              {(constraints.persona || []).map(v => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            {/* Status */}
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={filterSelectStyle}>
              <option value="All">Status: All</option>
              {(constraints.status || []).map(v => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </div>

          {/* Query table */}
          <div style={{
            background: T.white,
            border: `1px solid ${T.border}`,
            borderRadius: 12,
            overflow: 'hidden',
          }}>
            {/* Table header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              height: 40,
              background: T.offWhite,
              borderBottom: `1px solid ${T.border}`,
            }}>
              <div style={thStyle(false, COL_WIDTHS.id)}>Query ID</div>
              <div style={thStyle(true,  null)}>Question / Prompt</div>
              <div style={thStyle(false, COL_WIDTHS.category)}>Category</div>
              <div style={thStyle(false, COL_WIDTHS.stage)}>Stage</div>
              <div style={thStyle(false, COL_WIDTHS.specificity)}>Specificity</div>
              <div style={thStyle(false, COL_WIDTHS.persona)}>Persona</div>
              <div style={thStyle(false, COL_WIDTHS.status)}>Status</div>
            </div>

            {/* Table rows */}
            {loading ? (
              <div style={{ padding: 32, textAlign: 'center', color: T.slate, fontSize: 13 }}>
                Loading queries...
              </div>
            ) : filteredQueries.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: T.slate, fontSize: 13 }}>
                {queries.length === 0 && (genStatus?.status === 'pending' || genStatus?.status === 'running')
                  ? 'Questions will appear here as they are generated...'
                  : queries.length === 0
                  ? 'No queries yet. Add a query or upload a CSV to get started.'
                  : 'No queries match the selected filters.'
                }
              </div>
            ) : filteredQueries.map((query, idx) => (
              <QueryRow
                key={query.query_code ?? idx}
                query={query}
                isLast={idx === filteredQueries.length - 1}
                tdStyle={tdStyle}
                COL_WIDTHS={COL_WIDTHS}
                onClick={() => openEdit(query)}
              />
            ))}
          </div>

        </div>
      </div>

      {/* Slide-over overlay + panel */}
      {slideOver && (
        <>
          {/* Overlay */}
          <div
            onClick={() => !saving && setSlideOver(null)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.4)',
              zIndex: 40,
            }}
          />

          {/* Panel */}
          <div style={{
            position: 'fixed',
            right: 0,
            top: 0,
            bottom: 0,
            width: 380,
            background: T.white,
            boxShadow: '-8px 0 32px rgba(0,0,0,0.12)',
            zIndex: 50,
            display: 'flex',
            flexDirection: 'column',
            transform: 'translateX(0)',
            transition: 'transform 0.25s ease',
          }}>
            {/* Panel header */}
            <div style={{
              height: 56,
              borderBottom: `1px solid ${T.border}`,
              padding: '0 24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexShrink: 0,
            }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>
                Query Details
              </span>
              <button
                onClick={() => setSlideOver(null)}
                style={{
                  width: 24, height: 24,
                  background: 'none',
                  border: 'none',
                  fontSize: 18,
                  color: T.slate,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                }}
              >×</button>
            </div>

            {/* Panel body */}
            <div style={{
              flex: 1,
              overflowY: 'auto',
              padding: 24,
              display: 'flex',
              flexDirection: 'column',
              gap: 20,
            }}>
              {/* Query text */}
              <div>
                <label style={labelStyle}>QUERY TEXT</label>
                <textarea
                  rows={5}
                  value={formData.query_text}
                  onChange={e => setFormData(f => ({ ...f, query_text: e.target.value }))}
                  placeholder="Enter query prompt..."
                  style={{ ...inputStyle, resize: 'vertical' }}
                />
              </div>

              {/* Category + Stage row */}
              <div style={{ display: 'flex', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <ConstrainedSelect
                    label="CATEGORY"
                    field="category"
                    value={formData.category}
                    onChange={v => setFormData(f => ({ ...f, category: v }))}
                    placeholder="Select category..."
                    constraints={constraints}
                    constraintsLoading={constraintsLoading}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <ConstrainedSelect
                    label="STAGE"
                    field="stage"
                    value={formData.stage}
                    onChange={v => setFormData(f => ({ ...f, stage: v }))}
                    placeholder="Select stage..."
                    constraints={constraints}
                    constraintsLoading={constraintsLoading}
                  />
                </div>
              </div>

              {/* Specificity + Persona row */}
              <div style={{ display: 'flex', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <ConstrainedSelect
                    label="SPECIFICITY"
                    field="specificity"
                    value={formData.specificity}
                    onChange={v => setFormData(f => ({ ...f, specificity: v }))}
                    placeholder="Select specificity..."
                    constraints={constraints}
                    constraintsLoading={constraintsLoading}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <ConstrainedSelect
                    label="PERSONA"
                    field="persona"
                    value={formData.persona}
                    onChange={v => setFormData(f => ({ ...f, persona: v }))}
                    placeholder="Select persona..."
                    constraints={constraints}
                    constraintsLoading={constraintsLoading}
                  />
                </div>
              </div>

              {/* Status */}
              <ConstrainedSelect
                label="STATUS"
                field="status"
                value={formData.status}
                onChange={v => setFormData(f => ({ ...f, status: v }))}
                placeholder="Select status..."
                constraints={constraints}
                constraintsLoading={constraintsLoading}
              />
            </div>

            {/* Save error */}
            {saveError && (
              <div style={{
                margin: '0 24px 12px',
                padding: '10px 14px',
                background: T.redLight,
                color: T.red,
                borderRadius: 8,
                fontSize: 12,
                fontWeight: 500,
                flexShrink: 0,
              }}>
                {saveError}
              </div>
            )}

            {/* Panel footer */}
            <div style={{
              height: 64,
              borderTop: `1px solid ${T.border}`,
              padding: '0 24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 12,
              flexShrink: 0,
            }}>
              <button
                onClick={() => setSlideOver(null)}
                style={{
                  padding: '9px 18px',
                  background: T.white,
                  color: T.text,
                  border: `1px solid ${T.border}`,
                  borderRadius: 8,
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >Cancel</button>
              <button
                onClick={handleSaveQuery}
                disabled={saving}
                style={{
                  padding: '9px 18px',
                  background: T.text,
                  color: T.white,
                  border: 'none',
                  borderRadius: 8,
                  fontWeight: 700,
                  fontSize: 13,
                  cursor: saving ? 'not-allowed' : 'pointer',
                  opacity: saving ? 0.7 : 1,
                }}
              >
                {saving ? '...' : 'Save'}
              </button>
            </div>
          </div>
        </>
      )}

      {/* Toast notification */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: 32,
          left: '50%',
          transform: 'translateX(-50%)',
          background: T.text,
          color: T.white,
          padding: '12px 24px',
          borderRadius: 10,
          fontSize: 13,
          fontWeight: 600,
          boxShadow: '0 4px 24px rgba(0,0,0,0.18)',
          zIndex: 9999,
          pointerEvents: 'none',
        }}>
          {toast}
        </div>
      )}
    </div>
  )
}

// ─── Query row — extracted to prevent re-render closure issues ────────────────
function QueryRow({ query, isLast, tdStyle, COL_WIDTHS, onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        height: 56,
        borderBottom: isLast ? 'none' : `1px solid ${T.border}`,
        background: hovered ? T.offWhite : T.white,
        cursor: 'pointer',
        transition: 'background 0.1s',
      }}
    >
      <div style={{ ...tdStyle(false, COL_WIDTHS.id), fontFamily: 'monospace', fontSize: 11, color: T.slate, wordBreak: 'break-all' }}>
        {query.query_code}
      </div>
      <div style={{
        ...tdStyle(true, null),
        fontSize: 13,
        color: T.text,
        overflow: 'hidden',
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        lineHeight: 1.4,
      }}>
        {query.query_text}
      </div>
      <div style={{ ...tdStyle(false, COL_WIDTHS.category), fontSize: 13, color: T.textMid }}>
        {query.category}
      </div>
      <div style={{ ...tdStyle(false, COL_WIDTHS.stage), fontSize: 13, color: T.textMid }}>
        {query.stage}
      </div>
      <div style={{ ...tdStyle(false, COL_WIDTHS.specificity), fontSize: 13, color: T.textMid }}>
        {query.specificity}
      </div>
      <div style={{ ...tdStyle(false, COL_WIDTHS.persona), fontSize: 13, color: T.textMid }}>
        {query.persona}
      </div>
      <div style={tdStyle(false, COL_WIDTHS.status)}>
        <QueryStatusBadge status={query.status} />
      </div>
    </div>
  )
}

