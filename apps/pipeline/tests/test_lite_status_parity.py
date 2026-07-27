"""
Stage 14 (T1/T4): status-parity tests. Every soa_lite_requests.status
value worker.py WRITES must be a member of LITE_STATUSES (soa_shared/
models/soa_models.py) — the single source of truth the DB's
ck_soa_lite_requests_status is also built from (see the Stage 14
migration, b7c9c235bf62_fix_ck_soa_lite_requests_status.py). This is
exactly the class of bug that caused the Stage 13 incident: a status
write ('identifying_competitors') shipped in code before the DB
constraint was updated to allow it, so every attempt to write it
violated the constraint and the same poisoned row was re-picked and
re-failed on every poll forever.

_collect_written_lite_statuses AST-parses a source file and finds every
status value assigned in a conn.execute(text(...), {...}) call whose
SQL text mentions soa_lite_requests — both literal SQL ("SET status =
'x'") and bind-param writes ({"status": LITE_STATUS_X}), since Stage 14
converted every write in worker.py to the latter. Deliberately does NOT
scope by UPDATE vs INSERT vs table alias beyond substring-matching
'soa_lite_requests' in the SQL text — precise enough for this codebase
(no other table's status column is ever set in the same call), and
erring toward catching too much rather than too little is the right
default for a regression guard.
"""
import ast
import re
from pathlib import Path

from soa_shared.models.soa_models import LITE_STATUSES, SoaLiteRequest

WORKER_PATH = Path(__file__).parent.parent / "worker.py"


def _status_constants():
    import soa_shared.models.soa_models as soa_models
    return {
        name: getattr(soa_models, name)
        for name in dir(soa_models)
        if name.startswith("LITE_STATUS_")
    }


def _sql_text_of(node):
    """Extracts the raw SQL string from a text(...) call (typically a
    triple-quoted literal) or a bare string literal — the two shapes
    conn.execute()'s first arg takes in this codebase."""
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
            continue  # a SELECT's WHERE status = 'x' is a read, not a write

        # Literal writes: SET status = 'x' (none left in worker.py after
        # Stage 14's bind-param conversion, but a future regression
        # would be caught here too).
        found |= set(re.findall(r"\bstatus\s*=\s*'([a-z_]+)'", sql_text))

        # Bind-param writes: a 'status' key in the params dict, either a
        # literal string or a LITE_STATUS_* Name resolved via the
        # constants map.
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


def test_worker_status_writes_are_a_subset_of_lite_statuses():
    written = _collect_written_lite_statuses(WORKER_PATH.read_text())
    assert written, "sanity: the AST scan should find at least one status write in worker.py"
    assert written <= set(LITE_STATUSES)


def test_worker_writes_every_non_terminal_status_at_least_once():
    """Not just a subset check — confirms the scanner is actually
    finding the real transitions, not silently matching nothing useful."""
    written = _collect_written_lite_statuses(WORKER_PATH.read_text())
    assert written == {"identifying_competitors", "generating", "running", "complete", "failed"}


def test_constraint_matches_lite_statuses_exactly():
    assert _constraint_statuses() == set(LITE_STATUSES)


def test_parity_scanner_catches_a_deliberately_bogus_status():
    """
    T4: reproduces the exact Stage 13 incident shape — a status write
    outside the constraint set — as a throwaway fixture, and proves the
    same scanner used by test_worker_status_writes_are_a_subset_of_lite_statuses
    is sensitive enough to catch it (not a tautology that would pass no
    matter what). Never touches real source; nothing to clean up.
    """
    bogus_source = '''
from sqlalchemy import text

def bogus_write(conn, request_id):
    conn.execute(text("""
        UPDATE soa_lite_requests
        SET status = 'reticulating_splines', updated_at = NOW()
        WHERE id = :id
    """), {"id": request_id})
'''
    written = _collect_written_lite_statuses(bogus_source)
    assert "reticulating_splines" in written
    assert not written <= set(LITE_STATUSES)


def test_parity_scanner_catches_a_bogus_bind_param_status():
    """Same as above, but for the bind-param write shape (the one
    Stage 14 actually converted worker.py to use) — a bogus named
    constant would only be caught if it resolves to a value outside
    LITE_STATUSES, exercising the constants-map branch of the scanner."""
    bogus_source = '''
from sqlalchemy import text

BOGUS_STATUS = "reticulating_splines"

def bogus_write(conn, request_id):
    conn.execute(text("""
        UPDATE soa_lite_requests
        SET status = :status, updated_at = NOW()
        WHERE id = :id
    """), {"status": BOGUS_STATUS, "id": request_id})
'''
    written = _collect_written_lite_statuses(bogus_source, status_constants={"BOGUS_STATUS": "reticulating_splines"})
    assert "reticulating_splines" in written
    assert not written <= set(LITE_STATUSES)
