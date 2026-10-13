# SerpApi fixtures (2B)

None of these is a captured SerpApi response.

- `google_ai_mode_answer.json`, `bing_copilot_answer.json` — vendored verbatim from
  parleohq/truesync console-demo `services/engine/test/fixtures/serpapi_*.json`,
  which say of themselves: "Hand-written test fixture in the shape documented at
  serpapi.com/... Not a captured response."
- `google_ai_mode_no_ai_answer.json` — hand-written; the error text is the one the
  engine's own test uses.
- `bing_copilot_sign_in_wall.json` — hand-written; SerpApi's rendering of a sign-in
  wall is not documented in anything this repo has verified, so this encodes the
  runner's heuristic, not observed behaviour.

Replace with captured bodies (with the api_key removed) once a key is configured.
