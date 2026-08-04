/**
 * R2 (fetch resilience, hotfix 3): the honest banner for a degraded run.
 * Extracted (Part 1, judgment call) from LiteFullReport.jsx so the
 * status page (LiteProgress.jsx, P4) and the full report render the
 * exact same wording from the exact same degradedReason/bannerFacts
 * shape — one component, never a second copy that can drift.
 *
 * Sitemap-sampler stage (hotfix 5, S3): first-person banner copy, one
 * honest hedge, no generalization about how other agents would fare —
 * that claim was never ours to make (grep-tested: the retired "will
 * hit the same wall" line is gone repo-wide). degradedReason/
 * bannerFacts come from report.scan (or, pre-report, from GET
 * /status's additive degraded_reason/degraded_banner_facts — engine.py
 * computes the dynamic facts server-side; this only templates the
 * static wording around them). A pre-hotfix-5 scan row has no
 * degraded_reason at all — falls back to a generic, still-honest
 * message keyed on status alone.
 */
import { LightCard, InfoBadge } from './liteTheme.jsx'

function _attemptsPhrase(bannerFacts) {
  const n = bannerFacts?.attempts
  if (!n) return ''
  const robotsNote = bannerFacts.robots_included ? ', incl. robots.txt where applicable' : ''
  return ` (${n} attempt${n === 1 ? '' : 's'}${robotsNote})`
}

// Part 2 (P4.b), state/kind-aware (N4): the Sephora fix — whether
// agents "would hit the same wall" stops being an inference the
// instant the fetch probe has an answer. Nothing is appended when the
// probe hasn't run yet or came back inconclusive (bannerFacts.
// fetch_probe is only ever set by public_lite.py on a decisive
// outcome).
//
// N4: the "wall appears specific" claim only makes sense when there
// genuinely WAS a wall (status === 'blocked') — it renders nowhere
// else. The no-product-pages-found state gets its own honest,
// sampling-scoped sentence instead: the probe proves the page exists,
// it just says nothing about why OUR sampler missed it. The generic
// unreachable fallback (no degraded_reason at all) gets neither claim
// when the probe succeeded — there's no "wall" and no "sampler miss"
// to honestly describe, only total non-response. The could-not-access
// direction is universally true regardless of state, so it always
// renders.
function _fetchProbeSentence(bannerFacts, degradedReason, status) {
  const probe = bannerFacts?.fetch_probe
  if (!probe) return ''
  if (!probe.agent_could_access) {
    return " It reported it couldn't access the page either."
  }
  if (degradedReason === 'no_product_pages_found') {
    const kindPhrase = probe.kind === 'store_root' ? 'your homepage' : 'your product page'
    return ` ChatGPT opened ${kindPhrase} fine — the pages exist; our sampler couldn't locate them this run.`
  }
  if (status === 'blocked') {
    return ' ChatGPT opened it fine — the wall appears specific to unidentified readers like ours.'
  }
  return ''
}

export function DegradedRunBanner({ status, degradedReason, bannerFacts }) {
  if (status !== 'blocked' && status !== 'failed') return null

  let message
  if (degradedReason === 'no_product_pages_found') {
    const n = bannerFacts?.sitemaps_read ?? 0
    message = `We read ${n} of your sitemap${n === 1 ? '' : 's'} but couldn't locate product pages to sample — this can be our reader's limitation; on-site checks weren't evaluated.`
  } else if (status === 'blocked') {
    const refusal = bannerFacts?.refusal
    const verb = refusal === '403' ? '403-refused' : refusal === '429' ? 'rate-limited' : 'blocked'
    // W6: one template, one conditional — bannerFacts.signed comes
    // straight from engine.py's signing.is_signing_enabled() snapshot
    // for this run (public_lite.py merges it in unconditionally), the
    // same flag scorer.py's own evidence lines already read.
    const readerPhrase = bannerFacts?.signed ? 'our cryptographically verified reader (Web Bot Auth)' : 'our identified reader'
    message = `Your site ${verb} ${readerPhrase} on every page we tried${_attemptsPhrase(bannerFacts)}. We can only measure our own reader — but an edge this strict is worth verifying against the agents you care about.`
  } else {
    message = "We couldn't finish reading your site this time — nothing could be measured on-site. We'll try again on your next diagnostic."
  }
  message += _fetchProbeSentence(bannerFacts, degradedReason, status)

  return (
    <LightCard>
      <InfoBadge message={message} />
      <div className="lite-body" style={{ marginTop: 14 }}>
        Accessibility and True Value below read <strong>NOT MEASURABLE</strong>, not a failing
        score — we simply couldn't read the pages that would prove it this run. Visibility (how
        often agents mention you) is unaffected: it comes from live answers, not our crawl.
      </div>
    </LightCard>
  )
}
