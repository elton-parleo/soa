"""
Tests for app/routers/public_lite.py::_positive_int_env, which reads the
SoA Lite rate-limit constants from the environment at import time.
"""
import logging

import pytest

import app.routers.public_lite as public_lite

ENV_NAME = "TEST_PUBLIC_LITE_RATE_LIMIT"


def test_unset_uses_default(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    assert public_lite._positive_int_env(ENV_NAME, 7) == 7


def test_empty_uses_default(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "")
    assert public_lite._positive_int_env(ENV_NAME, 7) == 7


def test_valid_value_is_used(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "42")
    assert public_lite._positive_int_env(ENV_NAME, 7) == 42


@pytest.mark.parametrize("raw", ["abc", "3.5", "0", "-5"])
def test_invalid_value_falls_back_with_warning(monkeypatch, caplog, raw):
    monkeypatch.setenv(ENV_NAME, raw)
    with caplog.at_level(logging.WARNING, logger=public_lite.log.name):
        assert public_lite._positive_int_env(ENV_NAME, 7) == 7
    assert ENV_NAME in caplog.text


def test_constants_are_module_level_ints():
    for name in ("RATE_LIMIT_PER_IP_HOUR", "RATE_LIMIT_PER_IP_DAY", "GLOBAL_RATE_LIMIT_PER_HOUR"):
        assert isinstance(getattr(public_lite, name), int)
