/**
 * Tier segmentation and Layer 2 accuracy — new, with no lite equivalent:
 * a lite audit has no published catalog behind it, so there is nothing
 * for a typed expectation to be compared against.
 *
 * Renders nothing at all when report.tier_accuracy is absent, which is
 * every cycle of a study generated without a syndicated brand. Absent
 * rather than empty on purpose: an empty accuracy panel invites the
 * reader to conclude something about a measurement that was never taken.
 *
 * Three honesty rules the markup enforces, matching the rest of this
 * report's conventions:
 *
 *   No rate without its sample count. A rate over four samples and a
 *   rate over four hundred are not the same claim.
 *
 *   A rate with no sample renders a state chip, never a zero — the same
 *   not_measured/na convention PlatformMatrixSection already follows.
 *
 *   The validated agreement rate is blank until a human records one, and
 *   says so in words. It is never estimated and never inferred from the
 *   extractor's own confidence.
 */
import { StateChip } from '../../ds/index.js'
import { ReportSection } from '../../lite/report/ReportSection.jsx'

const OUTCOME_LABELS = {
  exact: 'Exact',
  stale: 'Stale',
  wrong: 'Wrong',
  absent: 'Not addressed',
  unscoreable: 'Unreadable',
}

// Deliberately five, in this order, and `unscoreable` is one of them.
// A report that showed four and folded unreadable answers into "wrong"
// would be reporting our own extraction failures as assistant errors.
const OUTCOME_ORDER = ['exact', 'stale', 'wrong', 'absent', 'unscoreable']

const SOURCE_LABELS = {
  brand_domain: "Brand's own store",
  retailer: 'Retailer only',
  none: 'No source cited',
}

function pct(rate) {
  return rate === null || rate === undefined ? null : `${Math.round(rate * 100)}%`
}

/** A rate with the sample it rests on, or an honest state chip. */
function Rate({ rate, samples, label }) {
  if (rate === null || rate === undefined || !samples) {
    return <StateChip state="unmeasured" variant="chip" size="sm">No sample</StateChip>
  }
  return (
    <span>
      <strong style={{ color: 'var(--text-strong)' }}>{pct(rate)}</strong>
      <span style={{ color: 'var(--faint)', fontSize: 11.5, marginLeft: 6 }}>
        n={samples}{label ? ` ${label}` : ''}
      </span>
    </span>
  )
}

const CELL = { padding: '12px', borderTop: '1px solid var(--hairline)', fontSize: 12.5 }
const HEAD = {
  textAlign: 'left', padding: '8px 12px', fontFamily: 'var(--font-mono)',
  fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase',
  color: 'var(--faint)', fontWeight: 500, borderBottom: '2px solid var(--border-strong)',
}

function ExtractionValidation({ validation }) {
  // The one number in this section that a model cannot produce. Blank
  // until Elton records a hand-check, and it says "not validated" rather
  // than printing something plausible — a validated agreement rate
  // nobody validated is the single most damaging number here.
  if (!validation || validation.agreement_rate === null || validation.agreement_rate === undefined) {
    return (
      <div data-testid="extraction-validation" style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
        <StateChip state="unmeasured" variant="chip" size="sm">Not validated</StateChip>
        <span style={{ marginLeft: 8 }}>
          No hand-check of the extraction pass has been recorded for this run.
          Every outcome below rests on one model reading each answer;
          until someone samples and checks that reading, its agreement
          rate is unknown rather than assumed.
        </span>
      </div>
    )
  }
  return (
    <div data-testid="extraction-validation" style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
      <strong style={{ color: 'var(--text-strong)' }}>
        Extraction validated at {pct(validation.agreement_rate)}
      </strong>
      {' '}on {validation.sample_size} hand-checked answers
      {validation.validated_by ? ` by ${validation.validated_by}` : ''}
      {validation.validated_at ? `, ${String(validation.validated_at).slice(0, 10)}` : ''}.
      {validation.notes ? ` ${validation.notes}` : ''}
    </div>
  )
}

function ExpectedNulls({ study }) {
  // Written BEFORE the run, at generation time, so a zero below reads as
  // predicted rather than explained after the fact. A prediction
  // recorded after seeing the result is not a prediction.
  const notes = study?.expected_nulls || {}
  const keys = Object.keys(notes)
  if (!keys.length) return null

  return (
    <div data-testid="expected-nulls" style={{ marginTop: 14 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', marginBottom: 6 }}>
        What this study expected to see nothing from
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--muted)', lineHeight: 1.65 }}>
        {keys.map((tier) => (
          <li key={tier}>{notes[tier]}</li>
        ))}
      </ul>
    </div>
  )
}

function Unavailable({ study }) {
  const unavailable = study?.unavailable || {}
  const keys = Object.keys(unavailable)
  if (!keys.length) return null

  // A tier that was asked for and could not be built. Stated, because a
  // missing rate that renders as 0% is the report lying quietly.
  return (
    <div data-testid="tier-unavailable" style={{ marginTop: 14, fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
      <StateChip state="unmeasured" variant="chip" size="sm">Not built</StateChip>
      <span style={{ marginLeft: 8 }}>
        {keys.length === 1 ? 'One tier was' : `${keys.length} tiers were`} requested
        but could not be built when this study was generated
        ({keys.map((t) => `${t}: ${unavailable[t]}`).join('; ')}). Its questions
        are absent from this report, not scored at zero.
      </span>
    </div>
  )
}

export function TierAccuracySection({ tierAccuracy, open, onToggle, onDrillDown }) {
  if (!tierAccuracy || !(tierAccuracy.tiers || []).length) return null

  const { tiers, study, value_survival, value_survival_samples } = tierAccuracy
  const merchant = study?.merchant

  return (
    <ReportSection
      id="tiers"
      eyebrow={
        merchant?.brand
          ? `${merchant.brand.toUpperCase()} · ANSWERS CHECKED AGAINST THE PUBLISHED RECORD`
          : 'ANSWERS CHECKED AGAINST THE PUBLISHED RECORD'
      }
      title="Not just whether you were mentioned — whether what was said was true"
      open={open}
      onToggle={onToggle}
    >
      <div style={{ marginTop: 16, fontSize: 13, color: 'var(--muted)', lineHeight: 1.65 }}>
        Every question below carries the answer we published, so an answer can be
        compared to it rather than judged. <strong style={{ color: 'var(--text-strong)' }}>Exact</strong> matches
        what is published now; <strong style={{ color: 'var(--text-strong)' }}>stale</strong> matches
        something we published before; <strong style={{ color: 'var(--text-strong)' }}>wrong</strong> matches
        nothing we have ever published. Answers that did not address the
        quantity, and answers we could not read, are counted separately and
        kept out of the accuracy rate — neither is a claim.
      </div>

      {value_survival !== null && value_survival !== undefined && (
        <div data-testid="value-survival" style={{ marginTop: 16, fontSize: 13, color: 'var(--text)' }}>
          Value survival:{' '}
          <Rate rate={value_survival} samples={value_survival_samples} label="scored" />
          <span style={{ color: 'var(--faint)', marginLeft: 8, fontSize: 11.5 }}>
            — the share of member-price, code and points questions answered exactly right.
          </span>
        </div>
      )}

      <div style={{ overflowX: 'auto', marginTop: 20 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={HEAD}>Tier</th>
              <th style={HEAD}>Visibility</th>
              <th style={HEAD}>Accuracy</th>
              <th style={HEAD}>Staleness</th>
              {OUTCOME_ORDER.map((o) => (
                <th key={o} style={HEAD}>{OUTCOME_LABELS[o]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier) => (
              <tr key={tier.tier} data-testid={`tier-row-${tier.tier}`}>
                <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>
                  {onDrillDown ? (
                    <button
                      type="button"
                      onClick={() => onDrillDown(tier.tier)}
                      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit', color: 'var(--text-strong)', textDecoration: 'underline' }}
                    >{tier.label}</button>
                  ) : tier.label}
                </td>
                <td style={CELL}>
                  <Rate rate={tier.visibility?.rate} samples={tier.visibility?.runs} label="runs" />
                </td>
                <td style={CELL}>
                  {/* category_control carries no expectation by design,
                      so it has visibility and no accuracy — the chip says
                      so rather than printing a zero. */}
                  <Rate rate={tier.accuracy} samples={tier.scored} label="scored" />
                </td>
                <td style={CELL}>
                  <Rate rate={tier.staleness} samples={tier.scored} label="scored" />
                </td>
                {OUTCOME_ORDER.map((o) => (
                  <td key={o} style={{ ...CELL, color: 'var(--muted)' }}>{tier.counts?.[o] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ overflowX: 'auto', marginTop: 24 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', marginBottom: 6 }}>
          By surface
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={HEAD}>Tier</th>
              <th style={HEAD}>Surface</th>
              <th style={HEAD}>Visibility</th>
              <th style={HEAD}>Accuracy</th>
              <th style={HEAD}>Staleness</th>
              <th style={HEAD}>Unreadable</th>
            </tr>
          </thead>
          <tbody>
            {tiers.flatMap((tier) => (tier.surfaces || []).map((surface) => (
              <tr key={`${tier.tier}:${surface.platform}`} data-testid={`surface-row-${tier.tier}-${surface.platform}`}>
                <td style={{ ...CELL, color: 'var(--muted)' }}>{tier.label}</td>
                <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>{surface.platform}</td>
                <td style={CELL}><Rate rate={surface.visibility?.rate} samples={surface.visibility?.runs} label="runs" /></td>
                <td style={CELL}><Rate rate={surface.accuracy} samples={surface.scored} label="scored" /></td>
                <td style={CELL}><Rate rate={surface.staleness} samples={surface.scored} label="scored" /></td>
                <td style={CELL}><Rate rate={surface.unscoreable_rate} samples={surface.samples} label="answers" /></td>
              </tr>
            )))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 24 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', marginBottom: 6 }}>
          Where the answers came from
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={HEAD}>Tier</th>
              {Object.keys(SOURCE_LABELS).map((k) => <th key={k} style={HEAD}>{SOURCE_LABELS[k]}</th>)}
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier) => (
              <tr key={tier.tier} data-testid={`source-row-${tier.tier}`}>
                <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>{tier.label}</td>
                {Object.keys(SOURCE_LABELS).map((k) => (
                  <td key={k} style={{ ...CELL, color: 'var(--muted)' }}>
                    {tier.source_attribution?.[k] ?? 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--hairline)' }}>
        <ExtractionValidation validation={tierAccuracy.extraction_validation} />
        <Unavailable study={study} />
        <ExpectedNulls study={study} />
      </div>
    </ReportSection>
  )
}
