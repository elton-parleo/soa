/**
 * Wraps the Wordmark lockup in a link to parleo.io wherever it renders
 * as site chrome (nav/rail/footer) — never inside a report/sample-card
 * DEPICTION of the mark (Hero.jsx's sample-report preview, the email
 * template) where it's part of the content being shown, not a way to
 * leave the page. target=_blank + rel="noopener noreferrer" so a
 * merchant reading a report never loses the tab they're on.
 *
 * Lives in lite/, not ds/ — it needs PARLEO_HOME_URL from
 * publicUrls.js, and ds/ never depends on lite/ (see
 * RequestFormModal.jsx's own docstring on that boundary).
 *
 * glyphOnly: no call site renders the icon-only variant today (grep
 * confirms), but the 44px hit area is wired in for whenever one does,
 * per the mobile pass convention every other icon-only control here
 * follows (see ShareReportButton.jsx's compact variant).
 */
import { Wordmark } from '../ds/index.js'
import { PARLEO_HOME_URL } from './publicUrls.js'

export function WordmarkLink({ size, dark, glyphOnly, style, className }) {
  const hitAreaStyle = glyphOnly
    ? { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 44, minHeight: 44 }
    : { display: 'inline-flex', alignItems: 'center' }

  return (
    <a
      href={PARLEO_HOME_URL}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Parleo home"
      className={`parleo-home-link${className ? ` ${className}` : ''}`}
      style={{ textDecoration: 'none', color: 'inherit', ...hitAreaStyle }}
    >
      <Wordmark size={size} dark={dark} glyphOnly={glyphOnly} style={style} />
    </a>
  )
}
