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

/**
 * What to call a tier in the first column. The label when the service
 * gave one, the tier key when it did not, and 'Untiered' for the rows
 * that carry no tier at all — questions written before the tiers
 * existed, which soa_queries.tier is nullable for.
 */
const BRAND_NOTE = {
  grounded: 'cited the brand\u2019s own record',
  echoed: 'named the brand, nothing checkable behind it',
  misattributed: 'named the brand, described a different one',
  fabricated: 'stated facts the record does not carry',
  acknowledged_unknown: 'said it could not find or verify the brand',
}

/**
 * The brand-direct tier, as the split it is rather than as an accuracy.
 *
 * There is no published value for one of these answers to match, so
 * exact/stale/wrong never described them; scoring on presence is what let
 * an answer reading "not a real or widely recognized brand" count beside
 * one that cited the brand's own loyalty page.
 *
 * Per surface as well as per tier, because the two fail differently —
 * one substitutes a product from another brand, the other invents one —
 * and a blended number describes neither.
 */
function BrandSplit({ tiers }) {
  const brand = (tiers || []).filter((t) => t.assessments)
  if (!brand.length) return null

  return (
    <div data-testid="brand-direct-split" style={{ marginTop: 28 }}>
      <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.65, marginBottom: 12 }}>
        Brand-direct questions name no published number, so they are not
        scored right or wrong. They are sorted by what the answer did with
        the brand. <strong style={{ color: 'var(--text-strong)' }}>Grounded</strong> cited
        your own record; <strong style={{ color: 'var(--text-strong)' }}>brand echoed</strong> named
        you and nothing more — which is all the old visibility number ever
        measured.
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={HEAD}>Brand-direct</th>
              {brand[0].assessments.map((a) => (
                <th key={a.outcome} style={HEAD}>{a.label}</th>
              ))}
              <th style={HEAD}>Assessed</th>
            </tr>
          </thead>
          <tbody>
            {brand.flatMap((tier) => [
              <tr key={tier.tier} data-testid="brand-split-total">
                <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>
                  All surfaces
                </td>
                {tier.assessments.map((a) => (
                  <td key={a.outcome} style={CELL} title={BRAND_NOTE[a.outcome]}>
                    <Rate rate={a.rate} samples={a.count} label="runs" />
                  </td>
                ))}
                <td style={{ ...CELL, color: 'var(--muted)' }}>
                  {tier.assessed} of {tier.samples}
                </td>
              </tr>,
              ...(tier.surfaces || []).filter((s) => s.assessments).map((surface) => (
                <tr key={`${tier.tier}:${surface.platform}`}
                    data-testid={`brand-split-${surface.platform}`}>
                  <td style={{ ...CELL, color: 'var(--muted)' }}>{surface.platform}</td>
                  {surface.assessments.map((a) => (
                    <td key={a.outcome} style={CELL}>
                      <Rate rate={a.rate} samples={a.count} label="runs" />
                    </td>
                  ))}
                  <td style={{ ...CELL, color: 'var(--muted)' }}>
                    {surface.assessed} of {surface.samples}
                  </td>
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </div>
      {brand.map((tier) => tier.counts?.absent > 0 && (
        <div key={tier.tier} style={{ fontSize: 11.5, color: 'var(--faint)', marginTop: 8 }}>
          {tier.counts.absent} answer{tier.counts.absent === 1 ? '' : 's'} never
          named the brand at all, and {tier.counts.absent === 1 ? 'is' : 'are'} outside
          the denominator above — nothing can be said about how a brand was
          treated in an answer that did not mention it.
        </div>
      ))}
    </div>
  )
}

function tierName(tier) {
  return tier.label || tier.tier || 'Untiered'
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

      {/* What the headline leaves out, and why. A rate that quietly drops
          rows is worse than one that never excluded them. */}
      {tierAccuracy.low_information && (
        <div data-testid="low-information" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--faint)', lineHeight: 1.6 }}>
          {tierAccuracy.low_information.scored} question
          {tierAccuracy.low_information.scored === 1 ? ' is' : 's are'} kept out of
          that figure as low-information{' '}
          ({tierAccuracy.low_information.exact} of {tierAccuracy.low_information.scored} answered
          exactly right). {tierAccuracy.low_information.note}
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
            {tiers.map((tier, index) => (
              <tr key={tier.tier ?? `tier-${index}`} data-testid={`tier-row-${tier.tier}`}>
                <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>
                  {/* A button with nothing in it is a button nobody can
                      click, and a drill-down keyed on a tier of null
                      cannot be opened — the endpoint filters on the tier
                      and the panel mounts on a truthy one. Both of those
                      present as a name that does nothing when clicked,
                      which is the failure this row is not allowed to
                      have. So: always a name, and a control only where
                      there is something behind it. */}
                  {onDrillDown && tier.tier ? (
                    <button
                      type="button"
                      onClick={() => onDrillDown(tier.tier)}
                      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit', color: 'var(--text-strong)', textDecoration: 'underline' }}
                    >{tierName(tier)}</button>
                  ) : tierName(tier)}
                </td>
                <td style={CELL}>
                  {/* Retired for brand-direct. It counted whether the
                      brand was named, which the split below now calls
                      'Brand echoed' — a word that does not read as a
                      score. See tier_accuracy.py. */}
                  {tier.visibility_retired
                    ? <span style={{ fontSize: 11.5, color: 'var(--faint)' }}>see below</span>
                    : <Rate rate={tier.visibility?.rate} samples={tier.visibility?.runs} label="runs" />}
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
                  <td key={o} style={{ ...CELL, color: 'var(--muted)' }}>
                    {tier.assessments ? '—' : (tier.counts?.[o] ?? 0)}
                    {/* The right code with the wrong terms. Still inside
                        `wrong`, counted apart from it — the code reached
                        the assistant and its value did not. */}
                    {o === 'wrong' && tier.near_miss > 0 && (
                      <span style={{ fontSize: 11, color: 'var(--faint)' }}>
                        {' '}({tier.near_miss} near miss)
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <BrandSplit tiers={tiers} />

      {/* Secondary expectations. The question asked for neither, so
          neither can move the accuracy above — they are shown here, with
          their own samples, as the bonus signals they are.

          Pack count in particular is weak evidence on a multi-variant
          product: the price question names the variant BY its count
          ("Size 3 small pack (84 ct)"), so an assistant restating 84 is
          echoing the question. The caption says so rather than letting
          a high number be read as knowledge. */}
      {tiers.some((t) => (t.secondary || []).length > 0) && (
        <div style={{ overflowX: 'auto', marginTop: 24 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)', marginBottom: 6 }}>
            Volunteered alongside — not asked for
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                <th style={HEAD}>Tier</th>
                <th style={HEAD}>Signal</th>
                <th style={HEAD}>Right when stated</th>
                <th style={HEAD}>Stated at all</th>
                {OUTCOME_ORDER.map((o) => <th key={o} style={HEAD}>{OUTCOME_LABELS[o]}</th>)}
              </tr>
            </thead>
            <tbody>
              {tiers.flatMap((tier) => (tier.secondary || []).map((signal) => (
                <tr key={`${tier.tier}:${signal.type}`} data-testid={`secondary-row-${tier.tier}-${signal.type}`}>
                  <td style={{ ...CELL, color: 'var(--muted)' }}>{tier.label}</td>
                  <td style={{ ...CELL, fontWeight: 600, color: 'var(--text-strong)' }}>{signal.label}</td>
                  <td style={CELL}><Rate rate={signal.accuracy} samples={signal.scored} label="stated" /></td>
                  <td style={CELL}><Rate rate={signal.answered_rate} samples={signal.samples} label="answers" /></td>
                  {OUTCOME_ORDER.map((o) => (
                    <td key={o} style={{ ...CELL, color: 'var(--muted)' }}>{signal.counts?.[o] ?? 0}</td>
                  ))}
                </tr>
              )))}
            </tbody>
          </table>
          <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--faint)', lineHeight: 1.55 }}>
            Neither is asked for, so neither moves the accuracy above. Read pack
            count carefully: on a product with several sizes the price question
            names the variant by its count, so an answer restating it is echoing
            the question rather than knowing it. A standalone pack-count probe
            that asks without stating is not built yet.
          </div>
        </div>
      )}

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
