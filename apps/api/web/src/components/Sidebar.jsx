import { useAuth } from '../AuthContext.jsx'

// ─── Design tokens ────────────────────────────────────────────────────────────
const T = {
  navy:        '#0D1829',
  navyMid:     '#162032',
  navyBdr:     '#1E2D42',
  white:       '#FFFFFF',
  sidebarText: '#94A3B8',
  teal:        '#0D9488',
}

// ─── Nav items ────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { id: 'dashboard', label: 'Cycles'          },
  { id: 'studies',   label: 'Studies'         },
  { id: 'results',   label: 'Results'         },
  { id: 'entities',  label: 'Entity Registry' },
  { id: 'settings',  label: 'Settings'        },
]

// ─── Shared Sidebar component ─────────────────────────────────────────────────

export default function Sidebar({ activeView, onNavigate }) {
  const { signOut } = useAuth()

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: 200,
      height: '100vh',
      background: T.navy,
      display: 'flex',
      flexDirection: 'column',
      overflowY: 'auto',
      zIndex: 10,
    }}>

      {/* Logo + subtitle */}
      <div style={{ padding: '24px 20px 16px' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
          >
            <rect
              x="2" y="2"
              width="8" height="20"
              rx="1.5"
              fill="hsl(213,99%,50%)"
            />
            <rect
              x="14" y="6"
              width="8" height="12"
              rx="1.5"
              fill="hsl(213,99%,50%)"
              opacity="0.4"
            />
          </svg>
          <span style={{
            fontSize: '16px',
            fontWeight: '700',
            color: '#FFFFFF',
            letterSpacing: '0.06em',
            fontFamily: "'DM Sans', sans-serif",
          }}>
            PARLEO
          </span>
        </div>
        <div style={{ color: T.sidebarText, fontSize: 11, marginTop: 2 }}>SoA Diagnostic</div>
      </div>

      {/* Nav items */}
      <nav style={{ flex: 1, padding: '8px 0' }}>
        {NAV_ITEMS.map(item => {
          const active = item.id === activeView
          return (
            <div
              key={item.id}
              onClick={() => onNavigate && onNavigate(item.id)}
              style={{
                padding: '10px 20px',
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                color: active ? T.white : T.sidebarText,
                background: active ? T.navyMid : 'transparent',
                borderLeft: active ? `3px solid ${T.teal}` : '3px solid transparent',
                cursor: 'pointer',
              }}
            >
              {item.label}
            </div>
          )
        })}
      </nav>

      {/* Bottom links */}
      <div style={{ padding: '16px 20px', borderTop: `1px solid ${T.navyBdr}` }}>
        <div
          style={{ fontSize: 12, color: T.sidebarText, cursor: 'pointer' }}
          onClick={() => signOut()}
        >
          Log Out
        </div>
      </div>

    </div>
  )
}
