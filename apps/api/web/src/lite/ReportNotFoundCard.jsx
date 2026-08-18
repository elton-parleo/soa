/**
 * Shared "honest dead end" card for an unknown/revoked/expired public
 * report — no stack trace, no redirect loop, just a way forward.
 * Originally LiteWidget.jsx's own ReportNotFound; generalized (copy +
 * CTA as props) so the Full Analysis public route (/fa/{token}) reuses
 * the same design system rather than forking a near-identical card.
 * Backend collapses unknown/revoked/expired share tokens to one
 * identical 404 (public_full_analysis.py's module docstring), so
 * there's deliberately only one card here too — not a separate
 * "revoked" or "expired" variant the frontend has no way to
 * distinguish anyway.
 */
import { LightCard } from './liteTheme.jsx'

export function ReportNotFoundCard({
  heading = "We couldn't find this report",
  body = 'This link may be mistyped, or the report it points to may no longer be available.',
  ctaLabel = 'Start a new audit',
  onCta,
}) {
  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <div className="lite-headline" style={{ fontSize: 20, marginBottom: 8 }}>
            {heading}
          </div>
          <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
            {body}
          </div>
          {onCta && (
            <button type="button" className="lite-pill lite-pill--solid" onClick={onCta}>
              {ctaLabel}
            </button>
          )}
        </LightCard>
      </div>
    </div>
  )
}
