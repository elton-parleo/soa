"""
Stage 14 (T1/T4): status-parity tests for public_lite.py's side of
soa_lite_requests.status — apps/pipeline and apps/api are separate
deployable services (communicate only through Postgres), so this
mirrors apps/pipeline/tests/test_lite_status_parity.py rather than
sharing a test module across app boundaries.

public_lite.py writes exactly one status value directly (the initial
INSERT's 'pending', via the LITE_STATUS_PENDING bind param) — every
other status transition happens in apps/pipeline/worker.py. See that
file's test_lite_status_parity.py for the AST-scanner used there; this
one is intentionally lighter given the smaller surface here.
"""
import ast
import re
from pathlib import Path

from soa_shared.models.soa_models import LITE_STATUSES, SoaLiteRequest

PUBLIC_LITE_PATH = Path(__file__).parent.parent / "app" / "routers" / "public_lite.py"


def _status_constants():
    import soa_shared.models.soa_models as soa_models
    return {
        name: getattr(soa_models, name)
        for name in dir(soa_models)
        if name.startswith("LITE_STATUS_")
    }


def _sql_text_of(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "text":
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _collect_written_lite_statuses(source_text: str, status_constants: dict = None) -> set:
    status_constants = status_constants if status_constants is not None else _status_constants()
    tree = ast.parse(source_text)
    found = set()

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"):
            continue
        if not node.args:
            continue
        sql_text = _sql_text_of(node.args[0])
        if not sql_text or "soa_lite_requests" not in sql_text:
            continue
        sql_upper = sql_text.upper()
        if not ("UPDATE" in sql_upper or "INSERT" in sql_upper):
            continue  # a SELECT/WHERE status = 'x' is a read, not a write

        found |= set(re.findall(r"\bstatus\s*=\s*'([a-z_]+)'", sql_text))

        if len(node.args) >= 2 and isinstance(node.args[1], ast.Dict):
            for key, value in zip(node.args[1].keys, node.args[1].values):
                if not (isinstance(key, ast.Constant) and key.value == "status"):
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
                elif isinstance(value, ast.Name) and value.id in status_constants:
                    found.add(status_constants[value.id])

    return found


def _constraint_statuses() -> set:
    constraint = next(
        c for c in SoaLiteRequest.__table_args__
        if getattr(c, "name", None) == "ck_soa_lite_requests_status"
    )
    return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))


def test_public_lite_status_writes_are_a_subset_of_lite_statuses():
    written = _collect_written_lite_statuses(PUBLIC_LITE_PATH.read_text())
    assert written, "sanity: the AST scan should find at least one status write in public_lite.py"
    assert written <= set(LITE_STATUSES)


def test_public_lite_writes_pending_on_submit():
    written = _collect_written_lite_statuses(PUBLIC_LITE_PATH.read_text())
    assert written == {"pending"}


def test_constraint_matches_lite_statuses_exactly():
    assert _constraint_statuses() == set(LITE_STATUSES)


def test_parity_scanner_catches_a_deliberately_bogus_status():
    """
    T4: reproduces the actual regression shape for this file (every
    real write here goes through a bind param, matching submit_lite_
    request's own INSERT) — a bogus status value assigned to the
    'status' bind param, caught by the scanner's constants-map branch.
    Never touches real source; nothing to clean up.
    """
    bogus_source = '''
from sqlalchemy import text

BOGUS_STATUS = "reticulating_splines"

def bogus_insert(conn, token):
    conn.execute(text("""
        INSERT INTO soa_lite_requests (token, status)
        VALUES (:token, :status)
    """), {"token": token, "status": BOGUS_STATUS})
'''
    written = _collect_written_lite_statuses(bogus_source, status_constants={"BOGUS_STATUS": "reticulating_splines"})
    assert "reticulating_splines" in written
    assert not written <= set(LITE_STATUSES)
