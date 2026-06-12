import { useState, useEffect, useRef } from 'react'
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

// ─── Study status tokens ──────────────────────────────────────────────────────
const STUDY_STATUS = {
  active: {
    label: 'ACTIVE',
    color: '#14532D',
    bg:    '#DCFCE7',
    dot:   '#16A34A',
  },
  paused: {
    label: 'PAUSED',
    color: '#92400E',
    bg:    '#FEF3C7',
    dot:   '#F59E0B',
  },
  draft: {
    label: 'DRAFT',
    color: '#374151',
    bg:    '#F3F4F6',
    dot:   '#9CA3AF',
  },
  archived: {
    label: 'ARCHIVED',
    color: '#374151',
    bg:    '#F3F4F6',
    dot:   '#9CA3AF',
  },
}

// ─── Mock data fallback ───────────────────────────────────────────────────────
const MOCK_STUDIES = [
  {
    study_type:    'brand_oral_b',
    name:          'Oral-B Brand Study',
    description:   'Deep dive into competitive performance and search engine visibility for oral care.',
    category:      'Oral Care',
    status:        'active',
    query_count:   50,
    study_pattern: 'Brand vs Brand',
  },
  {
    study_type:    'nike_footwear_q3',
    name:          'Nike Footwear Q3',
    description:   'Seasonal footwear category analysis.',
    category:      'Apparel',
    status:        'active',
    query_count:   128,
    study_pattern: 'Brand vs Brand',
  },
  {
    study_type:    'eco_label_audit',
    name:          'Eco-Label Audit',
    description:   'Cross-category sustainability study.',
    category:      'Cross-Category',
    status:        'paused',
    query_count:   42,
    study_pattern: 'Brand at Retail',
  },
  {
    study_type:    'dyson_air',
    name:          'Dyson Air Purifiers',
    description:   'Home tech category study.',
    category:      'Home Tech',
    status:        'active',
    query_count:   310,
    study_pattern: 'Retail',
  },
  {
    study_type:    'liquid_trends_2024',
    name:          'Liquid Trends 2024',
    description:   'FMCG beverage trends study.',
    category:      'FMCG',
    status:        'active',
    query_count:   75,
    study_pattern: 'Mixed',
  },
  {
    study_type:    'tesla_charging_ux',
    name:          'Tesla Charging UX',
    description:   'Automotive UX and purchase intent.',
    category:      'Automotive',
    status:        'draft',
    query_count:   15,
    study_pattern: 'Brand at Retail',
  },
  {
    study_type:    'samsung_galaxy_s24',
    name:          'Samsung Galaxy S24',
    description:   'Mobile tech competitive study.',
    category:      'Mobile Tech',
    status:        'active',
    query_count:   240,
    study_pattern: 'Brand vs Brand',
  },
]

// ─── Topbar ───────────────────────────────────────────────────────────────────
function Topbar() {
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
        <span style={{ color: T.text, fontWeight: 500 }}>STUDIES</span>
        {' › '}
        <span>Overview</span>
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

// ─── Status badge ─────────────────────────────────────────────────────────────
function StudyStatusBadge({ status }) {
  const s = STUDY_STATUS[status] || STUDY_STATUS.draft
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '4px 8px',
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 700,
      textTransform: 'uppercase',
      color: s.color,
      background: s.bg,
      whiteSpace: 'nowrap',
    }}>
      <span style={{
        width: 6, height: 6,
        borderRadius: '50%',
        background: s.dot,
        display: 'inline-block',
        flexShrink: 0,
      }} />
      {s.label}
    </span>
  )
}

// ─── Skeleton card ────────────────────────────────────────────────────────────
function SkeletonCard({ delay = 0 }) {
  return (
    <div style={{
      background: T.white,
      borderRadius: 12,
      border: `1px solid ${T.border}`,
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      padding: 20,
      minHeight: 220,
      animation: `pulse 1.5s ease-in-out ${delay}s infinite`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ height: 20, width: 70, background: T.border, borderRadius: 4 }} />
        <div style={{ height: 20, width: 20, background: T.border, borderRadius: 4 }} />
      </div>
      <div style={{ height: 20, width: '80%', background: T.border, borderRadius: 4, marginBottom: 20 }} />
      <div style={{ height: 10, background: T.border, borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 10, background: T.border, borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 10, background: T.border, borderRadius: 4 }} />
    </div>
  )
}

// ─── Study card ───────────────────────────────────────────────────────────────
function StudyCard({ study, onClick }) {
  const [hovered, setHovered] = useState(false)
  const DataRow = ({ label, value, last }) => (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingBottom: last ? 0 : 8,
      marginBottom: last ? 0 : 8,
      borderBottom: last ? 'none' : `1px solid ${T.border}`,
    }}>
      <span style={{ fontSize: 13, color: T.slate }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color: T.text }}>{value}</span>
    </div>
  )

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: T.white,
        borderRadius: 12,
        border: `1px solid ${T.border}`,
        boxShadow: hovered
          ? '0 4px 12px rgba(0,0,0,0.08)'
          : '0 1px 3px rgba(0,0,0,0.06)',
        padding: 20,
        cursor: 'pointer',
        transition: 'box-shadow 0.15s',
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
      }}
    >
      {/* Card header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
      }}>
        <StudyStatusBadge status={study.status} />
        <button
          onClick={e => e.stopPropagation()}
          style={{
            background: 'none',
            border: 'none',
            fontSize: 18,
            color: T.slate,
            cursor: 'pointer',
            padding: '0 4px',
            lineHeight: 1,
          }}
        >⋮</button>
      </div>

      {/* Study name */}
      <div style={{
        fontSize: 18,
        fontWeight: 700,
        color: T.text,
        marginBottom: 20,
        minHeight: 48,
        lineHeight: 1.3,
      }}>
        {study.name}
      </div>

      {/* Data rows */}
      <div>
        <DataRow label="Category"      value={study.category}      />
        <DataRow label="Query Count"   value={study.query_count}   />
        <DataRow label="Study Pattern" value={study.study_pattern} last />
      </div>
    </div>
  )
}

// ─── New Study empty card ─────────────────────────────────────────────────────
function NewStudyCard() {
  const [hovered, setHovered] = useState(false)
  return (
    <div
      title="Coming soon"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: T.white,
        borderRadius: 12,
        border: `1px dashed ${hovered ? T.text : T.borderDark}`,
        padding: 20,
        minHeight: 220,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'border-color 0.15s',
        textAlign: 'center',
      }}
    >
      <div style={{
        width: 48, height: 48,
        borderRadius: '50%',
        background: T.offWhite,
        border: `1px solid ${T.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 12,
        fontSize: 24,
        color: T.slate,
      }}>⊕</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: T.textMid, marginBottom: 8 }}>
        New Study
      </div>
      <div style={{ fontSize: 12, color: T.slate, maxWidth: 160, lineHeight: 1.5 }}>
        Define new parameters and entities to start a new data collection cycle.
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function StudyLibrary({ onNavigate, onSelectStudy }) {
  const [studies,        setStudies]        = useState([])
  const [loading,        setLoading]        = useState(true)
  const [categoryFilter, setCategoryFilter] = useState('All Categories')
  const [statusFilter,   setStatusFilter]   = useState('active')
  const [dateFilter,     setDateFilter]     = useState('Last 30 Days')
  const [uploading,      setUploading]      = useState(false)
  const [uploadError,    setUploadError]    = useState(null)
  const [uploadSuccess,  setUploadSuccess]  = useState(null)
  const fileInputRef = useRef(null)

  function loadStudies() {
    api.getStudies()
      .then(data => {
        if (data && data.length > 0) {
          setStudies(data.map(s => ({
            study_type:    s.id,
            name:          s.name,
            description:   '',
            category:      s.category,
            status:        'active',
            query_count:   s.queryCount,
            study_pattern: s.patterns?.[0] ?? '—',
          })))
        } else {
          setStudies(MOCK_STUDIES)
        }
      })
      .catch(() => setStudies(MOCK_STUDIES))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadStudies() }, [])

  async function handleFileSelected(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setUploadSuccess(null)
    try {
      const result = await api.uploadStudyCsv(file)
      setUploadSuccess(
        `Imported ${result.inserted} quer${result.inserted === 1 ? 'y' : 'ies'} across `
        + `${result.study_types.length} study type(s): ${result.study_types.join(', ')}`
      )
      // Refresh study list to reflect new data
      setLoading(true)
      loadStudies()
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const displayStudies = studies.length > 0 ? studies : MOCK_STUDIES

  // Derive unique categories for filter dropdown
  const categories = ['All Categories', ...new Set(displayStudies.map(s => s.category))]

  const filtered = displayStudies.filter(s => {
    const matchCat    = categoryFilter === 'All Categories' || s.category === categoryFilter
    const matchStatus = statusFilter === 'all' || s.status === statusFilter
    return matchCat && matchStatus
  })

  const selectStyle = {
    padding: '7px 10px',
    fontSize: 13,
    color: T.text,
    background: T.white,
    border: `1px solid ${T.border}`,
    borderRadius: 8,
    cursor: 'pointer',
    outline: 'none',
  }

  return (
    <div style={{
      display: 'flex',
      minHeight: '100vh',
      fontFamily: "'DM Sans', sans-serif",
      background: T.offWhite,
    }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        * { box-sizing: border-box; }
      `}</style>

      <Sidebar activeView="studies" onNavigate={onNavigate} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh', marginLeft: 200 }}>
        <Topbar />

        <div style={{ flex: 1, overflowY: 'auto', padding: 32 }}>

          {/* Hidden CSV file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={handleFileSelected}
          />

          {/* Page header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
            <div>
              <h1 style={{ margin: '0 0 6px', fontSize: 28, fontWeight: 700, color: T.text }}>Study Library</h1>
              <p style={{ margin: 0, fontSize: 14, color: T.slate, maxWidth: 540 }}>
                Manage and browse brand intelligence studies and their query sets.
              </p>
            </div>
            <button
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
              style={{
                padding: '10px 20px',
                background: T.text,
                color: T.white,
                border: 'none',
                borderRadius: 8,
                fontWeight: 700,
                fontSize: 14,
                cursor: uploading ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
                flexShrink: 0,
                opacity: uploading ? 0.7 : 1,
              }}
            >
              {uploading ? '⏳ Uploading...' : '⊕ Create Study with CSV'}
            </button>
          </div>

          {/* Upload success banner */}
          {uploadSuccess && (
            <div style={{
              background: '#DCFCE7', border: '1px solid #BBF7D0',
              borderRadius: 8, padding: '10px 14px', marginBottom: 16,
              fontSize: 13, color: '#14532D',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              ✓ {uploadSuccess}
              <button
                onClick={() => setUploadSuccess(null)}
                style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: '#14532D', fontSize: 14 }}
              >×</button>
            </div>
          )}

          {/* Upload error banner */}
          {uploadError && (
            <div style={{
              background: '#FEE2E2', border: '1px solid #FECACA',
              borderRadius: 8, padding: '10px 14px', marginBottom: 16,
              fontSize: 13, color: '#991B1B', whiteSpace: 'pre-line',
            }}>
              ✕ Upload failed:{'\n'}{uploadError}
              <button
                onClick={() => setUploadError(null)}
                style={{
                  display: 'block', marginTop: 8, background: '#FFFFFF',
                  border: '1px solid #FECACA', borderRadius: 4,
                  padding: '4px 10px', cursor: 'pointer', color: '#991B1B', fontSize: 12,
                }}
              >Dismiss</button>
            </div>
          )}

          {/* Filter bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
            <span style={{ fontSize: 13, color: T.slate }}>Filter by:</span>
            <select
              value={categoryFilter}
              onChange={e => setCategoryFilter(e.target.value)}
              style={selectStyle}
            >
              {categories.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              style={selectStyle}
            >
              <option value="all">Status: All</option>
              <option value="active">Status: Active</option>
              <option value="paused">Status: Paused</option>
              <option value="draft">Status: Draft</option>
              <option value="archived">Status: Archived</option>
            </select>
            <select
              value={dateFilter}
              onChange={e => setDateFilter(e.target.value)}
              style={selectStyle}
            >
              <option value="Last 30 Days">Last 30 Days</option>
              <option value="Last 90 Days">Last 90 Days</option>
              <option value="Last Year">Last Year</option>
              <option value="All Time">All Time</option>
            </select>
          </div>

          {/* Card grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            {loading
              ? [0, 1, 2, 3, 4, 5].map(i => <SkeletonCard key={i} delay={i * 0.1} />)
              : (
                <>
                  {filtered.map(study => (
                    <StudyCard
                      key={study.study_type}
                      study={study}
                      onClick={() => onSelectStudy && onSelectStudy(study.study_type)}
                    />
                  ))}
                  <NewStudyCard />
                </>
              )
            }
          </div>

        </div>
      </div>
    </div>
  )
}
