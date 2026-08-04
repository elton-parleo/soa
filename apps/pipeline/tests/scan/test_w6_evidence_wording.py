"""
Tests for W6 — the evidence-wording upgrade: "our identified reader"
becomes "our cryptographically verified reader (Web Bot Auth)" when
the run's fetches were signed, ONE template (scorer.py::_reader_phrase)
read from ONE flag (signing.is_signing_enabled()) — never two evidence
lines independently deciding the wording and risking disagreement.
"""
import socket

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scan import engine, fetcher, scorer, signing

ORIGIN = "https://acme.example.com"


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()


@pytest.fixture
def signing_on(monkeypatch):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", Ed25519PrivateKey.generate())
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "on")


@pytest.fixture
def signing_off(monkeypatch):
    monkeypatch.setattr(signing, "_PRIVATE_KEY", None)
    monkeypatch.setattr(signing, "WEB_BOT_AUTH", "off")


# ─── _reader_phrase: the one template, the one conditional ──────────────

def test_reader_phrase_unsigned(signing_off):
    assert scorer._reader_phrase() == "our identified reader"


def test_reader_phrase_signed(signing_on):
    assert scorer._reader_phrase() == "our cryptographically verified reader (Web Bot Auth)"


# ─── Integration: the robots-403-itself evidence line (Sephora shape) ────

def _uniform_403(monkeypatch):
    def fake_get(self, url, headers=None):
        return httpx.Response(403, text="Forbidden", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)


def test_robots_403_evidence_unsigned_wording(monkeypatch, signing_off):
    _uniform_403(monkeypatch)
    result = engine.run_scan(ORIGIN)
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt itself refused our identified reader (HTTP 403)" in evidence
    assert "cryptographically verified" not in evidence


def test_robots_403_evidence_signed_wording(monkeypatch, signing_on):
    _uniform_403(monkeypatch)
    result = engine.run_scan(ORIGIN)
    evidence = " ".join(result.dimensions["agent_access"]["evidence"])
    assert "robots.txt itself refused our cryptographically verified reader (Web Bot Auth) (HTTP 403)" in evidence


def test_signing_enabled_flag_recorded_on_every_run(monkeypatch, signing_on):
    _uniform_403(monkeypatch)
    result = engine.run_scan(ORIGIN)
    assert result.dimensions["signing_enabled"] is True


def test_signing_disabled_flag_recorded_on_every_run(monkeypatch, signing_off):
    _uniform_403(monkeypatch)
    result = engine.run_scan(ORIGIN)
    assert result.dimensions["signing_enabled"] is False
