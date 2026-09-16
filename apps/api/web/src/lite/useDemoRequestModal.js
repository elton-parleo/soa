/**
 * Wires RequestFormModal (ds/, presentational-only) to the demo-request
 * API and to a CTA's copy from demoRequestCtas.js. Context ride-along
 * (Part 2c): report_token/brand_name are passed in by the caller (only
 * report surfaces have them) — no visited-page-URL field; see
 * demoRequestApi.js's own docstring for why that was dropped from the
 * payload.
 */
import { useCallback, useState } from 'react'
import { DEMO_REQUEST_CTAS } from './demoRequestCtas.js'
import { submitDemoRequest } from './demoRequestApi.js'
import { track } from './analytics.js'
import { EVENTS } from './analyticsEvents.js'
import { trackAppointmentScheduled, newRequestId } from './openaiPixel.js'

export function useDemoRequestModal({ brandName, reportToken } = {}) {
  const [ctaKey, setCtaKey] = useState(null)

  const open = useCallback((key) => setCtaKey(key), [])
  const close = useCallback(() => setCtaKey(null), [])

  const cta = ctaKey ? DEMO_REQUEST_CTAS[ctaKey] : null

  const onSubmit = useCallback(
    async (values) => {
      // Generated once, before the request, so the OpenAI dedup key is
      // stable for THIS submission. Only used when there's no
      // reportToken to key on (the landing page's modal).
      const requestId = newRequestId()
      const result = await submitDemoRequest({
        ...values,
        source: cta ? cta.source : undefined,
        subject: cta ? cta.subject : undefined,
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
        // OpenAI ad conversion, inside the same ok-only branch and for
        // the same reasons: a honeypot trip never reaches this closure
        // at all, and a 422/failure leaves result.ok false.
        trackAppointmentScheduled({ reportToken, requestId })
      }
      return result
    },
    [cta, brandName, reportToken],
  )

  return { isOpen: ctaKey !== null, cta, open, close, onSubmit }
}
