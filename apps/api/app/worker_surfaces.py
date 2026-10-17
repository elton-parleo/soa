"""
2I: the dispatch rule every path that starts answers shares (POST
/api/full-loop, POST /api/console/cycles, POST /api/cycles): grounded
surfaces only, and only those the worker has a key for.

The worker reports its runners at boot (soa_worker_surfaces, booleans
only). A surface it has not reported on is not refused: before the first
boot on migration d2f6b8a4c1e9 the table is empty, and an empty table
refuses nothing.
"""
from typing import Dict, Iterable, List

from fastapi import HTTPException
from sqlalchemy import text

from soa_shared import surfaces


def reported(engine) -> Dict[str, dict]:
    """{surface_id: {'configured': bool, 'seen_at': iso}} as the worker last
    wrote it; {} when it has not, or the table is not there yet."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT surface_id, configured, seen_at FROM soa_worker_surfaces")).mappings().all()
    except Exception:  # noqa: BLE001 - the table predates migration d2f6b8a4c1e9
        return {}
    out = {}
    for r in rows:
        seen = r['seen_at']
        out[r['surface_id']] = {'configured': bool(r['configured']),
                                'seen_at': seen.isoformat() if hasattr(seen, 'isoformat') else seen}
    return out


def configured(engine) -> Dict[str, bool]:
    return {sid: row['configured'] for sid, row in reported(engine).items()}


def check_dispatch(names: Iterable[str], engine) -> List[str]:
    """The resolved ids to store, or a 422: an ungrounded surface (alias or
    id) is `ungrounded_surface_not_allowed`, an unknown name is refused as
    2D refuses it, and one the worker has no key for is
    `surface_not_configured`. The callers then refuse one that cannot run
    anywhere (surfaces.reported_reason)."""
    names = list(names)
    refusal = surfaces.ungrounded_refusal(names)
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)
    try:
        platforms = surfaces.resolve_platforms(names)
    except surfaces.UnknownSurface as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    refusal = surfaces.unconfigured_refusal(platforms, configured(engine))
    if refusal:
        raise HTTPException(status_code=422, detail=refusal)
    return platforms


def console_list(engine) -> List[dict]:
    """GET /api/console/surfaces: what the worker reports it can run
    (surfaces.worker_list), each with fidelity_label, grounded, and the
    worker's configured and seen_at (None when it has not reported). 2I-2:
    consumer surfaces too; the API's own environment is not read, since the
    API never calls SerpApi."""
    seen = reported(engine)
    out = []
    for s in surfaces.worker_list({sid: row['configured'] for sid, row in seen.items()}):
        row = seen.get(s['id']) or {}
        out.append({**s, 'fidelity_label': s['surface_label'], 'grounded': s['grounded'],
                    'configured': row.get('configured'), 'seen_at': row.get('seen_at')})
    return out
