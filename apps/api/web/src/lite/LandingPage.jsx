/**
 * Parleo Scan landing page — public, unauthenticated, at /scan.
 *
 * Presentational only: no submit-flow logic lives here. Both embedded
 * forms (hero + final CTA) are the existing LiteForm component in its
 * `compact` variant; submitting hands off to the existing /lite widget
 * by writing the same sessionStorage keys it already reads on mount
 * (see LiteWidget.jsx's resume-from-storage behavior) and navigating
 * there, so the progress/report state machine is never duplicated.
 */
import './theme.css'
import { STORAGE_KEY, STORAGE_KEY_STORE_URL } from './LiteWidget.jsx'
import { LandingNav } from './landing/LandingNav.jsx'
import { Hero } from './landing/Hero.jsx'
import { Methodology } from './landing/Methodology.jsx'
import { WhatYouGet } from './landing/WhatYouGet.jsx'
import { FieldEvidence } from './landing/FieldEvidence.jsx'
import { Stakes } from './landing/Stakes.jsx'
import { Path } from './landing/Path.jsx'
import { FinalCta } from './landing/FinalCta.jsx'
import { LandingFooter } from './landing/LandingFooter.jsx'

function writeSession(key, value) {
  try {
    if (value === null || value === undefined) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch (_) {}
}

export default function LandingPage() {
  function handleSubmitted(token, { storeUrl } = {}) {
    writeSession(STORAGE_KEY, token)
    writeSession(STORAGE_KEY_STORE_URL, storeUrl || null)
    window.location.href = '/lite'
  }

  return (
    <div className="lite-root" style={{ display: 'block', padding: 0 }}>
      <LandingNav />
      <Hero onSubmitted={handleSubmitted} />
      <Methodology />
      <WhatYouGet />
      <FieldEvidence />
      <Stakes />
      <Path />
      <FinalCta onSubmitted={handleSubmitted} />
      <LandingFooter />
    </div>
  )
}
