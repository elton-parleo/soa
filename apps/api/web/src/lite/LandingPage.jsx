/**
 * Parleo Scan landing page — public, unauthenticated, at /scan.
 *
 * Presentational only: no submit-flow logic lives here. Both embedded
 * forms (hero + final CTA) are the existing LiteForm component in its
 * `compact` variant; submitting hands off to the existing /lite widget's
 * state machine by writing the same sessionStorage keys it already
 * reads on mount (see LiteWidget.jsx's resume-from-storage behavior) —
 * the progress/report state machine is never duplicated here.
 *
 * Stage 9: navigation to the canonical /report/{token} URL goes through
 * the required `navigate` prop (App.jsx's history-push helper) instead
 * of a full page reload, so the transition from the marketing sections
 * to the live progress view doesn't lose React state or refetch assets.
 */
import './theme.css'
import { STORAGE_KEY, STORAGE_KEY_STORE_URL } from './LiteWidget.jsx'
import { LandingNav } from './landing/LandingNav.jsx'
import { Hero } from './landing/Hero.jsx'
import { AnatomyOfAnAnswer } from './landing/AnatomyOfAnAnswer.jsx'
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

export default function LandingPage({ navigate }) {
  function handleSubmitted(token, { storeUrl } = {}) {
    writeSession(STORAGE_KEY, token)
    writeSession(STORAGE_KEY_STORE_URL, storeUrl || null)
    navigate(`/report/${token}`)
  }

  return (
    <div className="lite-root" style={{ display: 'block', padding: 0 }}>
      <LandingNav />
      <Hero onSubmitted={handleSubmitted} />
      <AnatomyOfAnAnswer />
      <WhatYouGet />
      <FieldEvidence />
      <Stakes />
      <Path />
      <FinalCta onSubmitted={handleSubmitted} />
      <LandingFooter />
    </div>
  )
}
