/**
 * S2: fixable hook band. Counts come from F4's gap_areas_total/
 * gap_areas_parleo_fixes/parleo_fixable_points — computed by the run,
 * never a copy literal.
 */
import { Container, Button } from '../../ds/index.js'

export function FixableHook({ report }) {
  const pillars = report.pillars
  const total = pillars.gap_areas_total ?? 4
  const parleoFixes = pillars.gap_areas_parleo_fixes ?? 2
  const points = Math.round(pillars.parleo_fixable_points ?? 0)

  return (
    <div style={{ marginBottom: 26 }}>
      <Container pad={0}>
        <div style={{ padding: '22px 26px 24px', display: 'flex', justifyContent: 'space-between', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ maxWidth: 520 }}>
            <div className="mono-label" style={{ fontSize: 9, color: 'var(--blue)' }}>THE HEADLINE FINDING</div>
            <div style={{ fontSize: 22, fontWeight: 720, color: 'var(--text-strong)', letterSpacing: '-0.022em', marginTop: 8, lineHeight: 1.2 }}>
              Parleo can fix {parleoFixes} of your {total} major gaps.
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 8 }}>
              Incentive sync and protocol declarations are worth <b style={{ color: 'var(--text-strong)' }}>up to {points} points</b> on this run. TrueSync closes both.
            </div>
          </div>
          <a href="#truesync" style={{ textDecoration: 'none' }}>
            <Button variant="blue" arrow>See the two fixes</Button>
          </a>
        </div>
      </Container>
    </div>
  )
}
