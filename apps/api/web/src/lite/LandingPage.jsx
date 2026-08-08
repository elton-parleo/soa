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
import { useEffect, useState } from 'react'
import './theme.css'
import { STORAGE_KEY, STORAGE_KEY_STORE_URL } from './LiteWidget.jsx'
import { LandingNav } from './landing/LandingNav.jsx'
import { Hero } from './landing/Hero.jsx'
import { ProofBand } from './landing/ProofBand.jsx'
import { Stakes } from './landing/Stakes.jsx'
import { FieldEvidence } from './landing/FieldEvidence.jsx'
import { Path } from './landing/Path.jsx'
import { SampleReportSection } from './landing/SampleReportSection.jsx'
import { Framework } from './landing/Framework.jsx'
import { Grounded } from './landing/Grounded.jsx'
import { TrueSyncSection } from './landing/TrueSyncSection.jsx'
import { FinalCta } from './landing/FinalCta.jsx'
import { LandingFooter } from './landing/LandingFooter.jsx'
import { PUBLIC_AUDIT_BASE_URL } from './publicUrls.js'
import { LANDING_META_TITLE, LANDING_META_DESCRIPTION, OG_IMAGE_URL } from './landingMeta.js'
import { upsertMeta, upsertLink, restoreOrRemove } from './headMeta.js'

function writeSession(key, value) {
  try {
    if (value === null || value === undefined) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch (_) {}
}

// I2/I3, S1/S2: canonical + OG/Twitter tags, only on the landing page
// (the one indexable/shareable page on this host — /r/ and /s/ get a
// minimal noindex head instead, see LiteWidget.jsx). The audit host's
// served document already has these tags baked in at build time (same
// landingMeta.js constants, see vite.config.js's auditHeadPlugin) —
// upsert* updates that static tag in place instead of duplicating it,
// which also makes this effect correct standalone (e.g. reached via
// client-side navigation without the static head present at all).
// No og:image/twitter:image tag while OG_IMAGE_URL is null: no share
// image asset exists in this repo yet, and a made-up path would just
// 404 on every unfurl, so it's omitted rather than faked.
function useLandingMeta() {
  useEffect(() => {
    const prevTitle = document.title
    document.title = LANDING_META_TITLE

    const landingUrl = `${PUBLIC_AUDIT_BASE_URL}/`
    const handles = [
      upsertLink('canonical', landingUrl),
      upsertMeta('name', 'description', LANDING_META_DESCRIPTION),
      upsertMeta('property', 'og:title', LANDING_META_TITLE),
      upsertMeta('property', 'og:description', LANDING_META_DESCRIPTION),
      upsertMeta('property', 'og:url', landingUrl),
      upsertMeta('property', 'og:type', 'website'),
      upsertMeta('name', 'twitter:card', 'summary'),
      upsertMeta('name', 'twitter:title', LANDING_META_TITLE),
      upsertMeta('name', 'twitter:description', LANDING_META_DESCRIPTION),
      ...(OG_IMAGE_URL
        ? [upsertMeta('property', 'og:image', OG_IMAGE_URL), upsertMeta('name', 'twitter:image', OG_IMAGE_URL)]
        : []),
    ]

    return () => {
      document.title = prevTitle
      handles.forEach(restoreOrRemove)
    }
  }, [])
}

// Re-weighting session (Part 4): the expired-report state's "run a
// fresh audit" CTA prefills this from the retired report's own
// store_url, when one was recorded — read once on mount, never
// re-read on navigation within the page (a query param is how a full
// navigation from ReportExpired hands this off, not client-side state).
function usePrefillUrlFromQuery() {
  const [prefillUrl] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('url') || ''
    } catch (_) {
      return ''
    }
  })
  return prefillUrl
}

export default function LandingPage({ navigate }) {
  useLandingMeta()
  const prefillUrl = usePrefillUrlFromQuery()

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
      <Hero onSubmitted={handleSubmitted} initialStoreUrl={prefillUrl} />
      <ProofBand />
      <Stakes />
      <FieldEvidence />
      <Path />
      <SampleReportSection />
      <Framework />
      <Grounded />
      <TrueSyncSection />
      <FinalCta onSubmitted={handleSubmitted} />
      <LandingFooter />
    </div>
  )
}
