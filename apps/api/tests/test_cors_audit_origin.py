"""
X1: audit.parleo.io must be added to the CORS allowlist, additively —
existing origins (localhost dev, LITE_ALLOWED_ORIGIN) must not be
removed. This app has no TestClient harness (see
test_truecost_snapshots_endpoint.py's note — importing the full FastAPI
app pulls in routers that need a live DATABASE_URL at import time), so
this asserts the source directly, same style as the repo's other
grep-gate tests (e.g. scan/tests/test_identity.py).
"""
from pathlib import Path

APP_PY = Path(__file__).resolve().parents[1] / "app" / "app.py"


def _source() -> str:
    return APP_PY.read_text()


def test_cors_origins_still_include_localhost_dev_and_lite_allowed_origin():
    src = _source()
    assert '"http://localhost:5173"' in src
    assert '"http://localhost:3000"' in src
    assert '_lite_origin = os.getenv("LITE_ALLOWED_ORIGIN")' in src
    assert "_cors_origins.append(_lite_origin)" in src


def test_cors_origins_additively_include_the_audit_host():
    src = _source()
    assert 'os.getenv("PUBLIC_AUDIT_BASE_URL", "https://audit.parleo.io")' in src
    assert "_cors_origins.append(" in src


def test_x2_no_cookie_domain_widening_documented():
    src = _source()
    assert "no cookie Domain is set anywhere in this app" in src
