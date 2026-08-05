/**
 * Parleo Audit landing page — public, unauthenticated, at audit.parleo.io/.
 *
 * Presentational only: no submit-flow logic lives here. Both embedded
 * forms (hero + final CTA) are the existing LiteForm component in its
 * `compact` variant; submitting hands off to the existing /lite widget's
 * state machine by writing the same sessionStorage keys it already
 * reads on mount (see LiteWidget.jsx's resume-from-storage behavior) —
 * the progress/report state machine is never duplicated here.
 *
 * Stage 9: navigation to the canonical /r/{token} URL goes through
 * the required `navigate` prop (App.jsx's history-push helper) instead
 * of a full page reload, so the transition from the marketing sections
 * to the live progress view doesn't lose React state or refetch assets.
 */
import { useEffect } from 'react'
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
import { PUBLIC_AUDIT_BASE_URL } from './publicUrls.js'

function writeSession(key, value) {
  try {
    if (value === null || value === undefined) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch (_) {}
}

const META_TITLE = 'Parleo Audit — how AI shopping agents see your store'
const META_DESCRIPTION =
  'A free audit of what agentic shoppers actually see when they read your store: pricing, membership terms, and structured data.'

// I2/I3: canonical + OG/Twitter tags, only on the landing page (the one
// indexable/shareable page on this host — /r/ and /s/ get noindex
// instead, see LiteWidget.jsx). No og:image/twitter:image tag: no share
// image asset exists in this repo yet, and a made-up path would just
// 404 on every unfurl, so it's omitted rather than faked.
function useLandingMeta() {
  useEffect(() => {
    const prevTitle = document.title
    document.title = META_TITLE

    const canonical = document.createElement('link')
    canonical.rel = 'canonical'
    canonical.href = `${PUBLIC_AUDIT_BASE_URL}/`

    const metaTags = [
      ['name', 'description', META_DESCRIPTION],
      ['property', 'og:title', META_TITLE],
      ['property', 'og:description', META_DESCRIPTION],
      ['property', 'og:url', `${PUBLIC_AUDIT_BASE_URL}/`],
      ['property', 'og:type', 'website'],
      ['name', 'twitter:card', 'summary'],
      ['name', 'twitter:title', META_TITLE],
      ['name', 'twitter:description', META_DESCRIPTION],
    ].map(([attr, key, content]) => {
      const el = document.createElement('meta')
      el.setAttribute(attr, key)
      el.content = content
      return el
    })

    document.head.appendChild(canonical)
    metaTags.forEach((el) => document.head.appendChild(el))

    return () => {
      document.title = prevTitle
      document.head.removeChild(canonical)
      metaTags.forEach((el) => document.head.removeChild(el))
    }
  }, [])
}

export default function LandingPage({ navigate }) {
  useLandingMeta()

  function handleSubmitted(token, { storeUrl } = {}) {
    writeSession(STORAGE_KEY, token)
    writeSession(STORAGE_KEY_STORE_URL, storeUrl || null)
    // This page only ever renders on the audit host (App.jsx), so '/r/'
    // is always the right canonical prefix here.
    navigate(`/r/${token}`)
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
