/**
 * Wires RequestFormModal (ds/, presentational-only) to the demo-request
 * API and to a CTA's copy from demoRequestCtas.js. Context ride-along
 * (Part 2c): report_token/brand_name are passed in by the caller (only
 * report surfaces have them); page_url is always read fresh from
 * window.location.href at submit time, not captured at open time, so
 * a visitor who navigates within a long-lived SPA session before
 * submitting still reports the page they were actually on.
 */
import { useCallback, useState } from 'react'
import { DEMO_REQUEST_CTAS } from './demoRequestCtas.js'
import { submitDemoRequest } from './demoRequestApi.js'
import { track } from './analytics.js'
import { EVENTS } from './analyticsEvents.js'

export function useDemoRequestModal({ brandName, reportToken } = {}) {
  const [ctaKey, setCtaKey] = useState(null)

  const open = useCallback((key) => setCtaKey(key), [])
  const close = useCallback(() => setCtaKey(null), [])

  const cta = ctaKey ? DEMO_REQUEST_CTAS[ctaKey] : null

  const onSubmit = useCallback(
    async (values) => {
      const result = await submitDemoRequest({
        ...values,
        source: cta ? cta.source : undefined,
        page_url: typeof window !== 'undefined' ? window.location.href : '',
        brand_name: brandName || undefined,
        report_token: reportToken || undefined,
      })
      // Fires only on a real 200 — never on a honeypot trip (RequestFormModal
      // fakes success without ever calling onSubmit/this closure at all) and
      // never on a 422/failure (result.ok is false there).
      if (result && result.ok) {
        track(EVENTS.DEMO_REQUEST_SUBMITTED, {
          source: cta ? cta.source : undefined,
          brand_name: brandName || undefined,
          report_token: reportToken || undefined,
        })
      }
      return result
    },
    [cta, brandName, reportToken],
  )

  return { isOpen: ctaKey !== null, cta, open, close, onSubmit }
}
