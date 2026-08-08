/**
 * Guard against the landing's sample report going stale the way it did
 * this session: a re-weighting bumps SCORER_VERSION and retires old
 * reports (Part 4 of that session), so a sample run scored under a
 * prior version silently starts serving the "this report has expired"
 * state. This test fails the moment that happens, forcing a fresh
 * sample run instead of a dead link on the landing page.
 */
import { describe, it, expect } from 'vitest'
import { SAMPLE_REPORT_SCORER_VERSION } from '../landingSampleContent.js'
import { SCORER_VERSION } from '../scanDimensionsRegistry.js'

describe('landingSampleContent — sample run stays scored under the live model', () => {
  it('SAMPLE_REPORT_SCORER_VERSION matches the current SCORER_VERSION', () => {
    expect(SAMPLE_REPORT_SCORER_VERSION).toBe(SCORER_VERSION)
  })
})
