# Recorded narrative responses (2L-3)

One JSON file per subject of the FL13-shaped fixture (`tests/narratives_fixture.py`), named by the sha256
of its facts (`soa_shared/narratives.py` `facts_digest`): the facts, the model, the request digest (model,
effort, system prompt, schema, prompt) and both calls' raw responses and usage. `RecordedWriter` replays them;
a recording made from another request is refused with the command to re-record.

    cd apps/api
    python scripts/record_narratives.py --cycle fl13            # record what is missing or stale
    python scripts/record_narratives.py --cycle fl13 --force    # re-record everything
    python scripts/record_narratives.py --cycle fl13 --compare  # call again, compare, write nothing

Recorded Oct 21 2026 with gpt-5.4-nano-2026-03-17. The facts are the fixture's, not production's.
