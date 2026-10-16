"""
2I: which runners this worker can run, reported at boot.

One row per runner in soa_worker_surfaces: {surface_id, configured, seen_at}.
`configured` is whether the key the runner refuses to start without is set
(each runner's __init__ raises on it). Booleans only: a key's value is
never read into a row, a log line or an error.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import text

import soa_shared.config as config
from soa_shared import surfaces

logger = logging.getLogger(__name__)

#: The setting each runner needs, by surface id (run_orchestrator._RUNNER_CLASSES).
KEYS = {
    'chatgpt': 'OPEN_AI_API_KEY',
    'chatgpt_api': 'OPEN_AI_API_KEY',
    'gemini_grounded': 'GEMINI_API_KEY',
    'gemini_api': 'GEMINI_API_KEY',
    'perplexity': 'PERPLEXITY_API_KEY',
    'claude': 'ANTHROPIC_CLAUDE_API_KEY',
}
#: The consumer runners need SerpApi and the switch (surfaces.consumer_enabled).
CONSUMER = ('aimode', 'copilot')


def configured(env=None) -> Dict[str, bool]:
    out = {sid: bool(getattr(config, key, '')) for sid, key in KEYS.items()}
    on = surfaces.consumer_enabled(env)
    out.update({sid: on for sid in CONSUMER})
    return out


def report(engine, *, env=None, now: Optional[datetime] = None) -> Dict[str, bool]:
    """Writes one row per runner, replacing the last boot's. A failure is
    logged, never raised: a worker that cannot report still runs."""
    found = configured(env)
    now = now or datetime.now(timezone.utc)
    try:
        with engine.begin() as conn:
            for sid, ok in found.items():
                updated = conn.execute(text(
                    "UPDATE soa_worker_surfaces SET configured = :c, seen_at = :t WHERE surface_id = :s"),
                    {'c': ok, 't': now, 's': sid}).rowcount
                if not updated:
                    conn.execute(text(
                        "INSERT INTO soa_worker_surfaces (surface_id, configured, seen_at) VALUES (:s, :c, :t)"),
                        {'c': ok, 't': now, 's': sid})
        logger.info("[surfaces] reported %s", ', '.join(f"{s}={'yes' if v else 'no'}" for s, v in found.items()))
    except Exception:  # noqa: BLE001 - the table may predate the migration
        logger.exception("[surfaces] could not report the worker's surfaces")
    return found
