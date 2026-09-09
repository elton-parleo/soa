# Create Study modal — screenshot harness

Renders `CreateStudyModal` on its own, with `api.js` and `truesyncApi.js`
replaced by stubs, so the modal can be seen and screenshotted without a
login, a backend, or a live TrueSync.

    npm run shot        # http://localhost:5199

The TrueSync stub serves `apps/pipeline/tests/fixtures/wiggle_and_snug_catalog.json`
— the same real Wiggle & Snug catalog the Python and JS tier tests assert
against — so what the harness shows is what a real generation would
produce for that brand, not a mock of it.

Two stubs and a vite plugin, and the plugin is the only non-obvious part:
the component imports `'../api.js'` relative to itself, which
`resolve.alias` never sees, so the swap has to happen on the RESOLVED id.

## Why this cannot ship

The stubs answer as the API client. A bundle carrying them would be an
app whose data layer silently returns canned constraints and a fixture
catalog — a failure that ships quietly, because nothing about it looks
broken.

Three things keep it out, in increasing order of how much they actually
guarantee:

1. **Separate config and root.** `vite.shot.config.js` roots the build at
   this directory. The production `vite.config.js` names its three entry
   documents explicitly and this is not one of them.
2. **A dev-only script.** `npm run shot`, never `npm run build`.
3. **A build-time guard.** `forbid-screenshot-harness` in
   `vite.config.js` throws on resolving any module under this directory,
   so a stray import from `src/` fails the production build with the file
   that pulled it in — rather than shipping.

(1) and (2) are arrangements; only (3) is a guarantee, and only because
`src/__tests__/screenshotHarness.build.test.js` proves it is live: it
builds a probe entry that imports a stub and asserts the build *fails*.
Delete the plugin and that test goes red.

Nothing here is imported by the app or by the test suites.
