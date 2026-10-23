# Recorded narrative responses (2L-3)

One JSON file per subject of the FL13-shaped fixture (`tests/narratives_fixture.py`), named by the sha256
of its facts (`soa_shared/narratives.py` `facts_digest`): the facts, the model, the request digest (model,
effort, system prompt, schema, prompt) and both calls' raw responses and usage. `RecordedWriter` replays them;
a recording made from another request is refused with the command to re-record.

    cd apps/api
    python scripts/record_narratives.py --cycle fl13            # record what is missing or stale
    python scripts/record_narratives.py --cycle fl13 --force    # re-record everything
    python scripts/record_narratives.py --cycle fl13 --compare  # call again, compare, write nothing

Re-recorded Oct 22 2026 (2L-3a) with gpt-5.4-nano-2026-03-17, on the fixture with the three FL13 shapes
(`narratives_fixture.fl13_shapes`: an unreadable reference, a quote range around the price, a per-diaper quote).
A subject whose two calls split line/null holds a third call, the retry. The facts are the fixture's, not
production's.

Re-recorded Oct 22 2026 (2M-3) with gpt-5.4-nano-2026-03-17 after the prompt changed (no verdict word, the product
named on a price line, no bare comma between the quote and the retailer's price, the product rows' issues):
132 subjects, 275 calls, accepted 78, dropped 6, null 48; $0.0955 at the unverified price in
`scripts/record_narratives.py`. Two recordings were made this pass ($0.0944 and $0.0955); this is the second.
