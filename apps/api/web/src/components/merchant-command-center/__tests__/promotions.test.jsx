/**
 * Promotions — the Merchant Center lane's second artifact kind.
 *
 * A promotion is compiled from one incentive on the master record and
 * published through the same channel as the product feed, so it lives in
 * that channel's drawer tab rather than a column of its own. Three
 * outcomes, and telling them apart is the entire job of this section:
 *
 *   published + a review state   Google's verdict, with its reason verbatim
 *   compiled_not_published       WE declined to make the claim
 *   failed                       the payload was rejected or the call broke
 *
 * The middle one is the reason this file is longer than it looks. A
 * promotion that silently did not publish is indistinguishable from one
 * that was never compiled, and the honour gate's whole purpose is that
 * somebody can see it fired.
 *
 * Fixtures are the supply app's real compiler output; the review verdicts
 * are constructed until the first live push. See ../__fixtures__/README.md.
 */
import React from 'react'
import { render, screen, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import promotionPublications from '../__fixtures__/promotions-publications.json'
import reviews from '../__fixtures__/promotions-reviews.json'

import {
  buildPromotionRows, promotionOfferId, promotionMechanic,
  promotionReviewsById, PROMOTION_REVIEW_TONE,
} from '../truesyncDerive.js'
import { classifyRecord, aggregateCell, SURFACE } from '../verificationModel.js'

const LISTING = 94

const COUPON = promotionPublications.find((p) => p.record_ref.endsWith('mfr_coupon'))
const GIFT = promotionPublications.find((p) => p.record_ref.endsWith('gift_with_purchase'))
const REFUSED = promotionPublications.find((p) => p.status === 'compiled_not_published')

// ─── The record_ref is what separates the two artifact kinds ─────────

describe('a promotion is told apart from a listing by its record_ref', () => {
  it('reads the offer id out of a promotion ref', () => {
    expect(promotionOfferId('promotion:deal:9:mfr_coupon')).toBe('deal:9:mfr_coupon')
  })

  it('does not mistake a listing row for a promotion', () => {
    expect(promotionOfferId('listing:94')).toBeNull()
    expect(promotionOfferId(null)).toBeNull()
  })

  it('names the mechanic from the payload, not from the ref', () => {
    expect(promotionMechanic(COUPON.payload)).toBe('Coupon code')
    expect(promotionMechanic(GIFT.payload)).toBe('Gift with purchase')
    expect(promotionMechanic(REFUSED.payload)).toBe('Subscribe & save')
  })
})

// ─── A promotion review is in none of the listing's four dimensions ──

describe('promotion reviews do not answer questions about the listing', () => {
  it('is classified as its own kind, not as unreadable', () => {
    // An unclassified method falls into `unreadable` and inflates
    // dimension 4, reporting a gap in this page's observability where
    // there is none. Same trap prospect_fetch fell into.
    const classified = classifyRecord(reviews.live)
    expect(classified.kind).toBe('promotion')
    expect(classified.kind).not.toBe('unreadable')
  })

  it('is counted in no dimension of the cell it sits on', () => {
    const cell = aggregateCell(COUPON, [reviews.live, reviews.rejected], {
      channelSlug: 'merchant_center',
      verificationSurface: SURFACE.ACCEPTANCE,
    })

    expect(cell.unreadableCount).toBe(0)
    expect(cell.issueCount).toBe(0)
    expect(cell.drift).toBeNull()
    // Surfaced for the drawer, counted nowhere.
    expect(cell.promotionRecordCount).toBe(2)
  })

  it('keys reviews by promotion id, since one listing carries several', () => {
    const byId = promotionReviewsById([reviews.live, reviews.rejected])
    expect([...byId.keys()].sort()).toEqual([
      'deal_9_gift_with_purchase',
      'deal_9_mfr_coupon',
    ])
  })

  it('keeps the newest review per promotion', () => {
    const older = { ...reviews.in_review, id: 1 }
    const newer = { ...reviews.live, id: 2 }
    const byId = promotionReviewsById([newer, older])
    expect(byId.get('deal_9_mfr_coupon').drift.state).toBe('LIVE')
  })
})

// ─── Rows, one per outcome ───────────────────────────────────────────

describe('one row per promotion, including the ones we withheld', () => {
  it('builds a row for every promotion on the listing', () => {
    const rows = buildPromotionRows(promotionPublications, [], LISTING)
    expect(rows).toHaveLength(3)
  })

  it('keeps a refusal as a first-class row', () => {
    const rows = buildPromotionRows(promotionPublications, [], LISTING)
    const refused = rows.find((r) => r.refused)

    expect(refused).toBeTruthy()
    expect(refused.status).toBe('compiled_not_published')
    // Compiled and valid. The refusal is a judgment, not a failure.
    expect(refused.payload.attributes.redemptionRestriction).toBe('SUBSCRIBE')
    expect(refused.reason).toContain('false public claim')
  })

  it('carries no review for a promotion that was never published', () => {
    const rows = buildPromotionRows(promotionPublications, Object.values(reviews), LISTING)
    expect(rows.find((r) => r.refused).review).toBeNull()
  })

  it('marks a published promotion with no read-back as awaiting review', () => {
    const rows = buildPromotionRows(promotionPublications, [], LISTING)
    // Not rejected. An unreviewed promotion is not a refused one.
    expect(rows.find((r) => r.promotionId === 'deal_9_mfr_coupon').review).toBeNull()
  })

  it('ignores promotions belonging to another listing', () => {
    const elsewhere = { ...COUPON, id: 999, listing_id: 95 }
    const rows = buildPromotionRows([...promotionPublications, elsewhere], [], LISTING)
    expect(rows.every((r) => r.recordRef !== elsewhere.record_ref || r.status === 'published'))
      .toBe(true)
    expect(rows).toHaveLength(3)
  })

  it("carries Google's promotion resource name as the external ref", () => {
    const rows = buildPromotionRows(promotionPublications, [], LISTING)
    const coupon = rows.find((r) => r.promotionId === 'deal_9_mfr_coupon')
    expect(coupon.externalRef).toContain('/promotions/deal_9_mfr_coupon')
  })
})

// ─── The lifecycle, one fixture per state ────────────────────────────

describe('the review lifecycle maps to the tones acceptance already uses', () => {
  it.each([
    ['live', 'LIVE', 'sync'],
    ['in_review', 'IN_REVIEW', 'drift'],
    ['rejected', 'REJECTED', 'fail'],
  ])('%s renders as %s', (fixture, state, tone) => {
    const rows = buildPromotionRows(promotionPublications, [reviews[fixture]], LISTING)
    const row = rows.find((r) => r.review)

    expect(row.review.state).toBe(state)
    expect(row.review.tone).toBe(tone)
    expect(PROMOTION_REVIEW_TONE[state]).toBe(tone)
  })

  it('only LIVE counts as approved', () => {
    for (const [fixture, approved] of [['live', true], ['in_review', false], ['rejected', false]]) {
      const rows = buildPromotionRows(promotionPublications, [reviews[fixture]], LISTING)
      expect(rows.find((r) => r.review).review.state === 'LIVE').toBe(approved)
    }
  })

  it("keeps Google's rejection reason verbatim", () => {
    const rows = buildPromotionRows(promotionPublications, [reviews.rejected], LISTING)
    const rejected = rows.find((r) => r.review)

    // Not paraphrased and not mapped to a vocabulary of ours: the
    // merchant has to act on what Google actually said.
    expect(rejected.review.reasons[0]).toEqual(
      reviews.rejected.drift.reasons[0],
    )
  })

  it('does not treat an unrecognised state as success', () => {
    const odd = {
      ...reviews.live,
      observed: { ...reviews.live.observed },
      drift: { ...reviews.live.drift, state: 'SOME_NEW_STATE' },
    }
    const rows = buildPromotionRows(promotionPublications, [odd], LISTING)
    const row = rows.find((r) => r.review)
    expect(row.review.tone).toBe('hold')
    expect(row.review.state).not.toBe('LIVE')
  })
})

// ─── On screen ───────────────────────────────────────────────────────

import { fireEvent } from '@testing-library/react'
import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'
import ListingDrawer from '../ListingDrawer.jsx'
import {
  buildCatalogRows, latestPublicationByCell, orderChannels,
} from '../truesyncDerive.js'
import { surfaceOf } from '../verificationModel.js'

const FRESH = '2099-01-01T00:00:00Z'

function drawerProps({ promotions = [], promotionReviews = [] } = {}) {
  const ordered = orderChannels(channels)
  const rows = buildCatalogRows(spine, Object.fromEntries(
    Object.entries(listings).map(([id, d]) => [Number(id), d])))
  const row = rows[0]

  // The fixtures were captured against another listing; re-home them on
  // whichever row this drawer opens, so the test does not depend on the
  // catalog fixture's ordering.
  const rehomed = promotions.map((p) => ({ ...p, listing_id: row.listingId }))
  const reviewRows = promotionReviews.map((r) => ({
    ...r, listing_id: row.listingId, created_at: FRESH,
  }))

  const pubs = [...publications, ...rehomed]
  const byCell = latestPublicationByCell(pubs)

  const cellFor = (r, channel) => aggregateCell(
    byCell.get(`${r.listingId}:${channel.slug}`),
    channel.slug === 'merchant_center' ? reviewRows : [],
    { channelSlug: channel.slug, verificationSurface: surfaceOf(channel) },
  )

  return {
    row,
    channels: ordered,
    channelState: Object.fromEntries(
      ordered.map((c) => [c.slug, { implementation: 'live', muted: false }])),
    cellFor,
    publications: pubs,
    onClose: () => {}, onPublish: () => {}, publishPending: false,
    onVerify: () => {}, verifyPending: false,
  }
}

const openGmc = () =>
  fireEvent.click(screen.getByRole('tab', { name: /google merchant center/i }))

const promotionsSection = () =>
  screen.getByRole('heading', { name: /Promotions/ }).closest('.mcc-section')

describe('the Promotions section on screen', () => {
  it('appears only on the Merchant Center tab', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    // Another channel is selected first; promotions ride in one lane only,
    // and rendering the section everywhere would imply the others have one.
    expect(screen.queryByRole('heading', { name: /Promotions/ })).not.toBeInTheDocument()

    openGmc()
    expect(screen.getByRole('heading', { name: /Promotions/ })).toBeInTheDocument()
  })

  it('says so plainly when there is no promotion, rather than showing nothing', () => {
    render(<ListingDrawer {...drawerProps()} />)
    openGmc()
    expect(within(promotionsSection()).getByText(/No promotion has been compiled/))
      .toBeInTheDocument()
  })

  it('shows every mechanic, including the one we withheld', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()
    const section = within(promotionsSection())

    expect(section.getByText('Coupon code')).toBeInTheDocument()
    expect(section.getByText('Gift with purchase')).toBeInTheDocument()
    expect(section.getByText('Subscribe & save')).toBeInTheDocument()
  })

  it('puts the honour gate reason on screen, in full, not in a tooltip', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()

    // The sentence that explains why a correct, validated promotion did not
    // go out. A panel that buries it teaches an operator that promotions
    // silently vanish. Scoped to the section: the drawer also shows it as
    // the cell's publish reason, which is a different claim about a
    // different artifact and must not stand in for this one.
    expect(
      within(promotionsSection()).getByText(
        'store has no subscription mechanic; publishing would be a false public claim',
      ),
    ).toBeInTheDocument()
  })

  it('renders a refusal neutrally — nothing is wrong', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()

    const reason = within(promotionsSection()).getByText(/store has no subscription mechanic/)
    const row = reason.closest('.mcc-promo')
    expect(row).toHaveClass('mcc-promo-refused')
    // The `not_applicable` pattern: a settled fact gets no alarm colour.
    expect(reason).not.toHaveClass('mcc-promo-failed')
    expect(within(row).getByText('Not published')).toBeInTheDocument()
  })

  it('shows a live promotion as live', () => {
    render(<ListingDrawer {...drawerProps({
      promotions: promotionPublications, promotionReviews: [reviews.live],
    })} />)
    openGmc()
    expect(within(promotionsSection()).getByText('Live')).toBeInTheDocument()
  })

  it('shows a promotion still in review as pending, not as approved', () => {
    render(<ListingDrawer {...drawerProps({
      promotions: promotionPublications, promotionReviews: [reviews.in_review],
    })} />)
    openGmc()

    const section = within(promotionsSection())
    expect(section.getByText('In review')).toBeInTheDocument()
    expect(section.queryByText('Live')).not.toBeInTheDocument()
  })

  it("shows a rejection with Google's reason verbatim", () => {
    render(<ListingDrawer {...drawerProps({
      promotions: promotionPublications, promotionReviews: [reviews.rejected],
    })} />)
    openGmc()

    const section = within(promotionsSection())
    expect(section.getByText('Rejected')).toBeInTheDocument()
    expect(section.getByText('Promotion not found on landing page')).toBeInTheDocument()
    expect(
      section.getByText(/could not find this promotion on the landing page/),
    ).toBeInTheDocument()
  })

  it('says a published promotion is awaiting review before Google has answered', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()
    // Not rejected, and not live. Nothing has been asked yet.
    expect(within(promotionsSection()).getAllByText('Awaiting review').length)
      .toBeGreaterThan(0)
  })

  it("shows Google's resource name for a published promotion", () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()
    expect(
      within(promotionsSection()).getByText(/promotions\/deal_9_mfr_coupon/),
    ).toBeInTheDocument()
  })

  it('offers the compiled payload without showing it unprompted', () => {
    render(<ListingDrawer {...drawerProps({ promotions: promotionPublications })} />)
    openGmc()
    expect(
      within(promotionsSection()).getAllByText(/Show compiled promotion \(JSON\)/).length,
    ).toBe(3)
  })
})
