"""
Shared soa_cycles + soa_cycle_entities insert, extracted from
apps/api/app/routers/cycles.py::create_cycle (steps 4-5 of that endpoint)
so apps/pipeline/worker.py's SoA Lite processor can create cycles the same
way without duplicating the SQL or importing the API app.

Deliberately narrow: only the INSERT ... RETURNING id, created_at for
soa_cycles plus the soa_cycle_entities rows. Cycle-code uniqueness
checking, study_pattern detection from soa_queries, total_runs
computation, and the optional scope-snapshot freeze all stay in
create_cycle — those are either authed-flow-specific (uniqueness check
against a raw request) or irrelevant to cycle_mode='query' brand_vs_brand
cycles with no scope SKUs (the freeze step). create_cycle's behavior is
unchanged by this extraction: it emits the exact same SQL it did before,
just via this function.
"""
from sqlalchemy import text


def create_cycle_with_comparison_set(
    conn,
    *,
    cycle_code: str,
    study_type: str,
    study_pattern: str,
    cycle_mode: str,
    truecost_tiers,
    total_runs_planned,
    start_date,
    platforms,
    runs_per_query,
    organization_id: int,
    created_by,
    notes,
    comparison_set: list,
) -> tuple:
    """
    Inserts one soa_cycles row (status='planned') and its soa_cycle_entities
    comparison set. `conn` is an already-open connection/transaction (e.g.
    from engine.begin()) — the caller owns commit/rollback.

    comparison_set: list of dicts with keys entity_id, comparison_code, role
    (e.g. [{"entity_id": 7, "comparison_code": "M001", "role": "primary"}, ...]).
    platforms/truecost_tiers are passed through as-is (caller JSON-encodes
    if using raw SQL params that require it, matching create_cycle).

    Returns (cycle_id, created_at).
    """
    cycle_row = conn.execute(text("""
        INSERT INTO soa_cycles (
            cycle_code, study_type, study_pattern, status,
            cycle_mode, truecost_tiers,
            total_runs_planned, completed_runs, start_date, notes,
            platforms, runs_per_query,
            organization_id, created_by
        ) VALUES (
            :code, :st, :sp, 'planned',
            :cycle_mode, :truecost_tiers,
            :total, 0, :start_date, :notes,
            :platforms, :runs_per_query,
            :org_id, :created_by
        )
        RETURNING id, created_at
    """), {
        "code":           cycle_code,
        "st":             study_type,
        "sp":             study_pattern,
        "cycle_mode":     cycle_mode,
        "truecost_tiers": truecost_tiers,
        "total":          total_runs_planned,
        "start_date":     start_date,
        "notes":          notes,
        "platforms":      platforms,
        "runs_per_query": runs_per_query,
        "org_id":         organization_id,
        "created_by":     created_by,
    }).fetchone()

    cycle_id = cycle_row[0]
    created_at = cycle_row[1]

    for ce in comparison_set:
        conn.execute(text("""
            INSERT INTO soa_cycle_entities
              (cycle_id, entity_id, comparison_code, role)
            VALUES
              (:cid, :eid, :code, :role)
        """), {
            "cid":  cycle_id,
            "eid":  ce["entity_id"],
            "code": ce["comparison_code"],
            "role": ce["role"],
        })

    return cycle_id, created_at
