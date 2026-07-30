/**
 * THE HERO — scan.parleo.io landing page, section [1].
 *
 * Embeds the existing LiteForm submit flow (compact variant — see
 * ../LiteForm.jsx) rather than reimplementing it. Truth rules honored:
 *  - T1: visibility copy stays scoped to ChatGPT/LITE_QUERY_COUNT queries; the "four
 *    agents" claim is scoped strictly to what the crawl reads.
 *  - T2: no "instant"/"about a minute" language — results stream live
 *    over a few minutes.
 *  - T5: no real sample-report token exists in the repo yet, so the
 *    sample-teaser card points at href="#" (flagged to the user).
 */
import { SectionHeader } from '../liteTheme.jsx'
import { LiteForm } from '../LiteForm.jsx'
import { TrustChip, PrivacyNote, SampleTeaserCard, ReportPreviewMock, BrandChip } from './landingTheme.jsx'
import { LITE_QUERY_COUNT } from './scanDimensionsRegistry.js'

const PLATFORMS = [
  { label: 'ChatGPT', glyph: 'C' },
  { label: 'Gemini', glyph: 'G' },
  { label: 'Perplexity', glyph: 'P' },
  { label: 'Copilot', glyph: 'M' },
]

export function Hero({ onSubmitted }) {
  return (
    <section className="lite-landing-section lite-landing-section--tight" style={{ paddingTop: 56 }}>
      <SectionHeader
        label={<>THE PARLEO SCAN <span className="lite-badge-dot" style={{ background: 'var(--accent)' }} aria-hidden="true" /></>}
      />
      <h1 className="lite-display-headline">
        Do AI agents recommend your{' '}
        <span className="lite-serif-italic">best price</span>?
      </h1>

      <div className="lite-cols-2" style={{ marginTop: 40, alignItems: 'start', gap: 48 }}>
        <div>
          <p className="lite-body lite-muted" style={{ fontSize: 15, marginBottom: 24, maxWidth: 480 }}>
            We ask ChatGPT {LITE_QUERY_COUNT} questions across all four stages of a purchase —
            awareness, research, comparison, ready to buy — and score how
            often it recommends you, and at what price. Then we crawl your
            store the same way ChatGPT, Gemini, Perplexity, and Copilot all
            read a page, so you can see whether the agents your customers
            already use can find your offers at all.
          </p>

          <div style={{ maxWidth: 480, marginBottom: 20 }}>
            <LiteForm onSubmitted={onSubmitted} compact submitLabel="Get your visibility report" />
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
            <TrustChip icon="✓">Free</TrustChip>
            <TrustChip icon="⏱">Results in minutes, streamed live</TrustChip>
            <TrustChip icon="👁">No signup to see your score</TrustChip>
          </div>

          <PrivacyNote>
            The scan reads only your public pages, the same ones agents see,
            and only asks ChatGPT about your brand and its closest
            competitors. Your report link is private until you share it.
          </PrivacyNote>

          <div style={{ marginTop: 24, marginBottom: 16 }}>
            <SampleTeaserCard
              href="#"
              score={57}
              label="Sample report"
              linkText="See a sample of the full report"
              meta="9 incentives · 8 dimensions · ranked fixes in plain language"
            />
          </div>

          <div>
            <div className="lite-label" style={{ marginBottom: 10 }}>
              Visibility on ChatGPT · store read across the four agents
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {PLATFORMS.map((p) => <BrandChip key={p.label} label={p.label} glyph={p.glyph} />)}
            </div>
          </div>
        </div>

        <div>
          <ReportPreviewMock domain="yourstore.com" score={57} />
          <p className="lite-visually-hidden">
            Sample report preview: an Agent Commerce Score of 57 out of 100
            for yourstore.com, with an Accessibility subscore of 14 out of 20
            and a True Value subscore of 26 out of 40. Nine incentives were
            found; agents can price none of them.
          </p>
        </div>
      </div>
    </section>
  )
}
