/**
 * FIELD EVIDENCE — section [4]. The three exemplars and their exact
 * numbers are copy-deck-approved verbatim (Truth Rule T4) — do not add,
 * round, or invent additional figures here. No third-party logo assets
 * exist in the repo, so brand marks are mono-letter badges, consistent
 * with landingTheme.jsx's BrandChip.
 */
import { SectionHeader } from '../liteTheme.jsx'

function EvidenceBar({ label, value, pct, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-2)', marginBottom: 4 }}>
        <span>{label}</span>
        <span className="lite-mono" style={{ fontWeight: 700, color: 'var(--text)' }}>{value}</span>
      </div>
      <div className="lite-bar-track">
        <div className="lite-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

function VerifiedTag() {
  return <span className="lite-chip lite-chip--neutral" style={{ borderColor: 'var(--line)' }}>Verified</span>
}

function Monogram({ text }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 30, height: 30, borderRadius: '50%', background: 'var(--foundation)', color: '#fff',
      fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700, flexShrink: 0,
    }}>
      {text}
    </span>
  )
}

export function FieldEvidence() {
  return (
    <section className="lite-landing-section">
      <SectionHeader label="FIELD EVIDENCE" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)' }}>
        What the scan finds <span className="lite-serif-italic">in the wild</span>.
      </h2>

      <div className="lite-cols-3" style={{ marginTop: 32 }}>
        <div className="lite-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Monogram text="REI" />
              <span style={{ fontWeight: 700, fontSize: 14 }}>REI Co-op</span>
            </div>
            <VerifiedTag />
          </div>
          <EvidenceBar label="Member pays" value="$228.65" pct={69} color="var(--accent)" />
          <EvidenceBar label="Agents quote" value="$269.00" pct={100} color="var(--foundation)" />
          <p className="lite-body lite-muted" style={{ fontSize: 13, marginTop: 12 }}>
            A co-op member really pays $228.65 on a $269.00 Patagonia jacket.
            Agents quote $269.00.
          </p>
        </div>

        <div className="lite-card">
          {/* TODO(Stage 8, R1): "3.2%"/"1.8%" read as this exact metric
             (deal_citation_rate — see IncentiveCitationCard in
             LiteFullReport.jsx), but these were authored as illustrative
             copy-deck numbers in Stage 6, before deal_citation_rate was
             exposed anywhere in the product. There is no source cycle in
             this repo to verify which denominator actually produced
             them. Per R1: left unchanged rather than guessed — do not
             adjust without a verified source. */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Monogram text="G/H" />
              <span style={{ fontWeight: 700, fontSize: 14 }}>Gillette vs Harry's</span>
            </div>
            <VerifiedTag />
          </div>
          <EvidenceBar label="Harry's cited" value="3.2%" pct={100} color="var(--foundation)" />
          <EvidenceBar label="Gillette cited" value="1.8%" pct={56} color="#8890A0" />
          <p className="lite-body lite-muted" style={{ fontSize: 13, marginTop: 12 }}>
            Harry's is cited at 3.2%, Gillette at 1.8% — agents never
            compute the price-per-shave gap between them.
          </p>
        </div>

        <div className="lite-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Monogram text="iO9" />
              <span style={{ fontWeight: 700, fontSize: 14 }}>Oral-B iO Series 9</span>
            </div>
            <VerifiedTag />
          </div>
          <div style={{ position: 'relative', height: 8, background: 'var(--track)', borderRadius: 4, margin: '18px 0 10px' }}>
            <div style={{
              position: 'absolute', left: '0%', right: '30%', top: 0, bottom: 0,
              background: 'var(--accent)', borderRadius: 4,
            }} />
            <span className="lite-mono" style={{ position: 'absolute', left: 0, top: -18, fontSize: 10, color: 'var(--text-2)' }}>$219.99 · Target</span>
            <span className="lite-mono" style={{ position: 'absolute', right: 0, top: -18, fontSize: 10, color: 'var(--text-2)' }}>$329.99 · Walgreens</span>
          </div>
          <div className="lite-numeral" style={{ fontSize: 20, textAlign: 'center', marginBottom: 8 }}>$110 apart</div>
          <p className="lite-body lite-muted" style={{ fontSize: 13 }}>
            The Oral-B iO Series 9 ranges from $219.99 at Target to $329.99
            at Walgreens — a $110 spread agents see inconsistently, if at
            all.
          </p>
        </div>
      </div>
    </section>
  )
}
