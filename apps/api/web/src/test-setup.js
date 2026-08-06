/**
 * Global vitest/jsdom setup. jsdom doesn't implement IntersectionObserver
 * — several ported design-system components (Stat's count-up,
 * SoAIndex's bar-fill reveal) use it for real, so tests that mount them
 * need a stub or every render throws in the passive-effect phase.
 * Enough surface for those effects: an observer that stores its
 * callback and never actually fires (count-up/reveal stay at their
 * pre-animation state, which is what the smoke tests assert on).
 */
class MockIntersectionObserver {
  constructor(callback) {
    this.callback = callback
  }
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.IntersectionObserver === 'undefined') {
  globalThis.IntersectionObserver = MockIntersectionObserver
}
