"""
Crawl-failure alerting, and the deploy smoke test that should have
caught the crash that motivated it.

The signing-import crash (production outage, 2026-09-22) ran for a full
deploy cycle before anyone noticed, and what surfaced it was a visitor
reading their own broken report. Two things follow from that: the worker
should tell us when a crawl fails, and a module that cannot import
should fail the deploy rather than the first audit.

No real HTTP: httpx.post is patched in every test that could reach it.
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

import ops_alert
import worker


@pytest.fixture(autouse=True)
def _clean_alert_state(monkeypatch):
    ops_alert.reset_rate_limit()
    monkeypatch.setenv("OPS_ALERT_EMAIL", "ops@parleo.io")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "audits@parleo.io")
    yield
    ops_alert.reset_rate_limit()


class _OkResponse:
    status_code = 200

    def raise_for_status(self):
        return None


def _capture_posts():
    posts = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _OkResponse()

    return posts, fake_post


# ─── it sends, and it says what happened ─────────────────────────────────

def test_an_orchestration_failure_sends_one_email_with_the_run_facts():
    posts, fake_post = _capture_posts()

    with patch.object(httpx, "post", fake_post):
        sent = ops_alert.send_crawl_failure_alert(
            ops_alert.FAILURE_CLASS_ORCHESTRATION,
            request_id=417, token="abc123", store_url="https://allbirds.com",
            error="NameError: name 'base64' is not defined",
        )

    assert sent is True
    assert len(posts) == 1
    body = posts[0]["json"]["text"]
    for fact in ("417", "abc123", "https://allbirds.com", "NameError"):
        assert fact in body, fact
    assert posts[0]["json"]["to"] == ["ops@parleo.io"]
    assert ops_alert.FAILURE_CLASS_ORCHESTRATION in posts[0]["json"]["subject"]


def test_the_watchdog_class_is_its_own_alert():
    posts, fake_post = _capture_posts()

    with patch.object(httpx, "post", fake_post):
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=1)
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_WATCHDOG, request_id=2)

    assert len(posts) == 2


# ─── rate limiting: a broken deploy sends one email, not hundreds ────────

def test_repeated_failures_of_the_same_class_send_one_email_per_window():
    posts, fake_post = _capture_posts()

    with patch.object(httpx, "post", fake_post):
        results = [
            ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=i)
            for i in range(50)
        ]

    assert len(posts) == 1
    assert results[0] is True
    assert not any(results[1:])


def test_the_window_reopens_after_the_rate_limit_elapses(monkeypatch):
    posts, fake_post = _capture_posts()
    clock = {"t": 1000.0}
    monkeypatch.setattr(ops_alert.time, "monotonic", lambda: clock["t"])

    with patch.object(httpx, "post", fake_post):
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=1)
        clock["t"] += ops_alert.ALERT_RATE_LIMIT_SECONDS - 1
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=2)
        assert len(posts) == 1
        clock["t"] += 2
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=3)

    assert len(posts) == 2


# ─── never raises, never blocks ──────────────────────────────────────────

def test_no_recipient_configured_logs_and_returns_without_sending(monkeypatch, caplog):
    monkeypatch.delenv("OPS_ALERT_EMAIL", raising=False)
    posts, fake_post = _capture_posts()

    with caplog.at_level("ERROR"), patch.object(httpx, "post", fake_post):
        sent = ops_alert.send_crawl_failure_alert(
            ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=9, error="boom",
        )

    assert sent is False
    assert posts == []
    assert any("scan_orchestration_failed" in r.getMessage() for r in caplog.records)


def test_a_failing_send_never_raises():
    def _explode(*a, **k):
        raise httpx.ConnectError("no route to host")

    with patch.object(httpx, "post", _explode):
        assert ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_WATCHDOG, request_id=1) is False


def test_the_failure_is_logged_at_error_even_when_it_is_rate_limited(caplog):
    posts, fake_post = _capture_posts()

    with patch.object(httpx, "post", fake_post), caplog.at_level("ERROR"):
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=1)
        caplog.clear()
        ops_alert.send_crawl_failure_alert(ops_alert.FAILURE_CLASS_ORCHESTRATION, request_id=2)

    assert len(posts) == 1
    # The suppressed one is still an ERROR in the log — the email is
    # rate-limited, the record of the failure is not.
    assert [r for r in caplog.records if r.levelname == "ERROR"]


# ─── the worker actually calls it ────────────────────────────────────────

def test_the_worker_alerts_when_scan_orchestration_raises(monkeypatch):
    """The exact shape the signing-import crash took: _run_lite_scan
    raising out of process_lite_requests' isolating except."""
    calls = []
    monkeypatch.setattr(
        worker.ops_alert, "send_crawl_failure_alert",
        lambda failure_class, **kw: calls.append((failure_class, kw)),
    )
    # A grep-level guard that the call site exists at all — the
    # behavioral test for the whole path lives in
    # test_process_lite_requests.py, which has the full DB fixture.
    source = Path(worker.__file__).read_text()
    assert "ops_alert.send_crawl_failure_alert(" in source
    assert source.count("ops_alert.send_crawl_failure_alert(") == 2
    assert "FAILURE_CLASS_ORCHESTRATION" in source
    assert "FAILURE_CLASS_WATCHDOG" in source


# ─── the deploy smoke test ───────────────────────────────────────────────

PIPELINE_ROOT = Path(worker.__file__).parent


def test_the_smoke_script_passes_with_a_valid_signing_key(monkeypatch):
    """Run as a real subprocess, exactly as railway.toml runs it — an
    in-process import would already have the modules cached and would
    prove nothing."""
    env = dict(os.environ)
    # A 32-byte Ed25519 seed, hex-encoded — the shape scan/signing.py
    # reads. The outage was a crash on the path that HANDLES this value.
    env["BOT_SIGNING_KEY"] = "ab" * 32

    result = subprocess.run(
        [sys.executable, "smoke_imports.py"],
        cwd=PIPELINE_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    for module in ("scan.engine", "scan.signing", "worker"):
        assert f"[smoke] {module}: ok" in result.stdout


def test_the_smoke_script_fails_loudly_when_a_module_cannot_import(tmp_path):
    """The whole point: a broken module must exit non-zero, by name, so
    the deploy stops instead of the first audit."""
    script = PIPELINE_ROOT / "smoke_imports.py"
    broken = script.read_text().replace(
        'MODULES = ("scan.engine", "scan.signing", "worker")',
        'MODULES = ("scan.engine", "this_module_does_not_exist")',
    )
    target = tmp_path / "smoke_broken.py"
    target.write_text(broken)

    result = subprocess.run(
        [sys.executable, str(target)],
        cwd=PIPELINE_ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 1
    assert "this_module_does_not_exist" in result.stderr


def test_railway_runs_the_smoke_script_before_the_worker():
    """A smoke test that isn't wired into the start command is a file
    nobody runs."""
    toml = (PIPELINE_ROOT / "railway.toml").read_text()
    assert "smoke_imports.py && python worker.py" in toml
