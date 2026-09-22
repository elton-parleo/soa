"""
ops_alert.py — tells us when a crawl fails, instead of waiting for a
user to read the report and say so.

The signing-import crash (production outage, 2026-09-22) ran for a full
deploy cycle before anyone noticed, and what finally surfaced it was a
visitor reading their own broken report. Every crawl failure the worker
already handles gracefully — _run_lite_scan's orchestration except, and
_sweep_lite_completions' watchdog force-fail — was, by design, silent.
Graceful is right; silent is not.

Delivery reuses email_sender.py's Resend plumbing (same HTTP API, same
httpx call, same timeout) rather than adding a second provider. There is
no shared send-a-plain-message abstraction to hang this on — EmailSender
sends exactly one templated email — and inventing one for a two-field
internal alert would be more machinery than the thing it carries.

Never raises. An alert that can break the worker is worse than no alert:
the failure paths this is called from are the ones already doing their
best to keep a broken run from taking anything else down.

OPS_ALERT_EMAIL unset (local dev, and any deploy that hasn't set it)
logs at ERROR and returns — which is still strictly more than the
nothing that happened before.
"""
import logging
import os
import threading
import time

import httpx

from email_sender import RESEND_API_URL, SEND_TIMEOUT_SECONDS

log = logging.getLogger(__name__)

OPS_ALERT_EMAIL_ENV = "OPS_ALERT_EMAIL"

# One email per failure CLASS per window — not per failure. A broken
# deploy fails every request it touches, and the fiftieth identical
# email tells us nothing the first didn't while making the inbox
# useless for the next, different failure. The suppressed ones are
# still logged at ERROR.
ALERT_RATE_LIMIT_SECONDS = 15 * 60

FAILURE_CLASS_ORCHESTRATION = "scan_orchestration_failed"
FAILURE_CLASS_WATCHDOG = "scan_timed_out"

_last_sent: dict = {}
_last_sent_lock = threading.Lock()


def _should_send(failure_class: str, now: float) -> bool:
    """True at most once per failure_class per ALERT_RATE_LIMIT_SECONDS.
    Process-local: the worker is a single long-running process (see
    worker.py's module docstring), so this is the whole population.
    Locked because the state is shared and the cost of a lock here is
    nothing next to an HTTP call."""
    with _last_sent_lock:
        previous = _last_sent.get(failure_class)
        if previous is not None and (now - previous) < ALERT_RATE_LIMIT_SECONDS:
            return False
        _last_sent[failure_class] = now
        return True


def reset_rate_limit() -> None:
    """Test seam — the module-level clock is deliberately process-wide,
    and a test that ran after another test's alert would otherwise be
    suppressed by it."""
    with _last_sent_lock:
        _last_sent.clear()


def _body(failure_class: str, *, request_id, token, store_url, error) -> str:
    return "\n".join([
        f"failure class: {failure_class}",
        f"lite request:  {request_id}",
        f"token:         {token}",
        f"store URL:     {store_url}",
        "",
        "error:",
        str(error or "(none recorded)")[:2000],
    ])


def send_crawl_failure_alert(
    failure_class: str, *, request_id=None, token=None, store_url=None, error=None,
) -> bool:
    """Returns True when an email was actually handed to Resend. False
    covers every other outcome — no recipient configured, rate-limited,
    send failed — all of which are logged. Never raises."""
    try:
        now = time.monotonic()
        recipient = (os.environ.get(OPS_ALERT_EMAIL_ENV) or "").strip()
        api_key = os.environ.get("RESEND_API_KEY")
        from_address = os.environ.get("EMAIL_FROM")

        # Logged at ERROR before any early return: whether or not an
        # email goes out, this failure is now in the log as a failure.
        log.error(
            "[ops_alert] %s — request=%s token=%s store_url=%s error=%s",
            failure_class, request_id, token, store_url, str(error)[:300],
        )

        if not recipient:
            return False
        if not (api_key and from_address):
            log.error("[ops_alert] RESEND_API_KEY/EMAIL_FROM not set — alert not emailed")
            return False
        if not _should_send(failure_class, now):
            log.info("[ops_alert] %s suppressed (rate limit) — already alerted this window", failure_class)
            return False

        resp = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": from_address,
                "to": [recipient],
                "subject": f"[parleo] crawl failure: {failure_class}",
                "text": _body(failure_class, request_id=request_id, token=token,
                              store_url=store_url, error=error),
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        log.info("[ops_alert] %s alert sent", failure_class)
        return True
    except Exception:
        log.exception("[ops_alert] failed to send crawl-failure alert")
        return False
