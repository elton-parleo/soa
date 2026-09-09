# Create Study modal — screenshot harness

Renders `CreateStudyModal` on its own, with `api.js` and `truesyncApi.js`
replaced by stubs, so the modal can be seen and screenshotted without a
login, a backend, or a live TrueSync.

    npx vite --config vite.shot.config.js     # http://localhost:5199

The TrueSync stub serves `apps/pipeline/tests/fixtures/wiggle_and_snug_catalog.json`
— the same real Wiggle & Snug catalog the Python and JS tier tests assert
against — so what the harness shows is what a real generation would
produce for that brand, not a mock of it.

Two stubs and a vite plugin, and the plugin is the only non-obvious part:
the component imports `'../api.js'` relative to itself, which
`resolve.alias` never sees, so the swap has to happen on the RESOLVED id.

Nothing here is imported by the app or the test suites.
