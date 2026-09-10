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
import { PUBLIC_AUDIT_BASE_URL, auditPath } from './publicUrls.js'
import {
  LANDING_META_TITLE, LANDING_META_DESCRIPTION, OG_IMAGE_PATH, OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT, OG_IMAGE_ALT,
} from './landingMeta.js'
import { upsertMeta, upsertLink, restoreOrRemove } from './headMeta.js'
import { track, captureSrcParam } from './analytics.js'
import { EVENTS } from './analyticsEvents.js'
import { withOppref } from './openaiPixel.js'

function writeSession(key, value) {
  try {
    if (value === null || value === undefined) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch (_) {}
}

// landingMeta.js exports the share card as a root-relative PATH; the
// absolute URL is composed here from the client's env-aware
// PUBLIC_AUDIT_BASE_URL, exactly as vite.config.js's auditHeadPlugin
// composes it from the build's own audit base. One path literal, two
// env-aware bases — which is what keeps the tag correct both on
// audit.parleo.io today and on parleo.io/audit under the base-path
// build.
const OG_IMAGE_URL = OG_IMAGE_PATH ? `${PUBLIC_AUDIT_BASE_URL}${OG_IMAGE_PATH}` : null

// I2/I3, S1/S2: canonical + OG/Twitter tags, only on the landing page
// (the one indexable/shareable page on this host — /r/ and /s/ get a
// minimal noindex head instead, see LiteWidget.jsx). The audit host's
// served document already has these tags baked in at build time (same
// landingMeta.js constants, see vite.config.js's auditHeadPlugin) —
// upsert* updates that static tag in place instead of duplicating it,
// which also makes this effect correct standalone (e.g. reached via
// client-side navigation without the static head present at all).
// No og:image/twitter:image tag while OG_IMAGE_URL is null: a made-up
// path would just 404 on every unfurl, so it's omitted rather than
// faked (dead branch today — OG_IMAGE_PATH is a real asset now — but
// kept so a future reset back to null degrades safely).
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
      upsertMeta('name', 'twitter:card', OG_IMAGE_URL ? 'summary_large_image' : 'summary'),
      upsertMeta('name', 'twitter:title', LANDING_META_TITLE),
      upsertMeta('name', 'twitter:description', LANDING_META_DESCRIPTION),
      ...(OG_IMAGE_URL
        ? [
            upsertMeta('property', 'og:image', OG_IMAGE_URL),
            upsertMeta('property', 'og:image:width', String(OG_IMAGE_WIDTH)),
            upsertMeta('property', 'og:image:height', String(OG_IMAGE_HEIGHT)),
            upsertMeta('property', 'og:image:alt', OG_IMAGE_ALT),
            upsertMeta('name', 'twitter:image', OG_IMAGE_URL),
          ]
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

// Part 3c: landing_viewed.src mirrors captureSrcParam() (analytics.js)
// — the same ?src= read-store-strip mechanism the report page uses for
// ?src=email, here covering any future campaign link. Fires once per
// mount; absent a src param this session, captureSrcParam() itself
// resolves to 'direct'.
function useLandingViewedTracking() {
  useEffect(() => {
    track(EVENTS.LANDING_VIEWED, { src: captureSrcParam() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}

export default function LandingPage({ navigate }) {
  useLandingMeta()
  useLandingViewedTracking()
  const prefillUrl = usePrefillUrlFromQuery()

  function handleSubmitted(token, { storeUrl } = {}) {
    writeSession(STORAGE_KEY, token)
    writeSession(STORAGE_KEY_STORE_URL, storeUrl || null)
    // This page only ever renders on the audit surface (App.jsx), so
    // '/r/' is always the right canonical prefix here — through
    // auditPath(), because that surface may be served under a base
    // path (parleo.io/audit) rather than at a host root.
    //
    // withOppref: the ad-click parameter arrives on THIS page's URL and
    // would be dropped by a bare pushState path, leaving the run's own
    // report URL unattributed in the address bar. The pixel's cookie
    // already covers the in-tab case; this covers the copied/reloaded
    // URL. oppref only — never src, which analytics.js strips on
    // purpose so a copied link stays canonical.
    navigate(withOppref(auditPath(`/r/${token}`)))
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
