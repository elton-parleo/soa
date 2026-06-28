"""
validate_truecost_sweep.py — standalone, idempotent end-to-end validation
of the cycle_mode='truecost' sweep feature, driven through the DB and the
real sweep executor (apps/pipeline/sweep/truecost_sweep.py). No frontend,
no LLM calls.

Usage:
    VALIDATE_ENTITY_ID=17 python apps/pipeline/scripts/validate_truecost_sweep.py

Env vars:
    VALIDATE_ENTITY_ID   (required)  — pilot brand entity_id whose scope
                                       SKUs (entity templates) get swept.
    VALIDATE_TIERS       (default "null,walmart_plus") — comma list; the
                                       literal "null" means the non-member
                                       baseline tier (None).
    VALIDATE_CYCLE_CODE  (default "truecost-validate")
    VALIDATE_ORG_ID      (optional)  — organization_id to stamp on the
                                       cycle if the DB-fallback insert path
                                       is used. Defaults to the org of the
                                       most recently created soa_cycles
                                       row, or the first organizations row.
    API_BASE             (default "http://localhost:8000")
    API_TOKEN            (optional)  — only used for the read-endpoint
                                       check (step 8); that check is
                                       skipped without it.
    CLEAN                (default "true") — delete this validation cycle's
                                       prior snapshots + cycle row (scoped
                                       to VALIDATE_CYCLE_CODE only) before
                                       re-running.

This script never mutates feature code to make a check pass. If a check
reveals a real gap (e.g. the cycle-create API not yet accepting cycle_mode/
truecost_tiers), it REPORTS the gap and falls back to a direct DB insert —
the gap is a finding, not something papered over.
"""
import asyncio
import os
import sys

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import soa_shared.config as config
from soa_shared.database import session_factory
from soa_shared.models.soa_models import Organization, SoaCycle, SoaScopeSku, SoaTruecostSnapshot
from sweep.truecost_sweep import resolve_tiers, run_truecost_sweep

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VALIDATE_ENTITY_ID = os.environ.get("VALIDATE_ENTITY_ID")
VALIDATE_TIERS = os.environ.get("VALIDATE_TIERS", "null,walmart_plus")
VALIDATE_CYCLE_CODE = os.environ.get("VALIDATE_CYCLE_CODE", "truecost-validate")
VALIDATE_ORG_ID = os.environ.get("VALIDATE_ORG_ID")
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN")
CLEAN = os.environ.get("CLEAN", "true").lower() == "true"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}")
    results.append((ok, label))
    return ok


def info(label: str) -> None:
    print(f"[INFO] {label}")


def warn(label: str) -> None:
    print(f"[WARN] {label}")


def fatal(label: str) -> None:
    check(False, label)
    print_summary()
    sys.exit(1)


def print_summary() -> None:
    failed = [label for ok, label in results if not ok]
    print()
    if failed:
        print(f"VALIDATION FAILED ({len(failed)} checks)")
        for label in failed:
            print(f"  - {label}")
    else:
        print("VALIDATION PASSED")


def parse_tiers(raw: str) -> list[str | None]:
    tiers: list[str | None] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        tiers.append(None if part.lower() == "null" else part)
    return tiers or [None]


# ---------------------------------------------------------------------------
# Step 1 — preflight
# ---------------------------------------------------------------------------

def step_preflight() -> None:
    print("\n--- Step 1: Preflight ---")
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        check(True, "DB reachable via session_factory")
    except Exception as exc:
        fatal(f"DB reachable via session_factory: {exc}")

    if not config.DEAL_ENGINE_BASE_URL:
        fatal("Deal Engine reachable: DEAL_ENGINE_BASE_URL not configured")

    try:
        resp = httpx.get(config.DEAL_ENGINE_BASE_URL, timeout=5.0)
        # Any HTTP response (even 404) proves the service is up; only a
        # connection-level failure means it's unreachable.
        check(True, f"Deal Engine reachable at {config.DEAL_ENGINE_BASE_URL} (status={resp.status_code})")
    except Exception as exc:
        fatal(f"Deal Engine reachable at {config.DEAL_ENGINE_BASE_URL}: {exc}")


# ---------------------------------------------------------------------------
# Step 2 — schema
# ---------------------------------------------------------------------------

def step_schema() -> None:
    print("\n--- Step 2: Schema ---")
    with session_factory() as session:
        regclass = session.execute(
            text("SELECT to_regclass('soa_truecost_snapshots')")
        ).scalar()
        check(regclass is not None, "soa_truecost_snapshots table exists")

        cols = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'soa_cycles'"
                )
            ).fetchall()
        }
        check("cycle_mode" in cols, "soa_cycles.cycle_mode column exists")
        check("truecost_tiers" in cols, "soa_cycles.truecost_tiers column exists")


# ---------------------------------------------------------------------------
# Step 3 — scope present
# ---------------------------------------------------------------------------

def step_scope_present(entity_id: int) -> int:
    print("\n--- Step 3: Scope present ---")
    with session_factory() as session:
        active_count = (
            session.query(SoaScopeSku)
            .filter(
                SoaScopeSku.entity_id == entity_id,
                SoaScopeSku.cycle_id.is_(None),
                SoaScopeSku.is_active.is_(True),
            )
            .count()
        )
    if active_count == 0:
        fatal(
            f"entity_id={entity_id} has at least one active scope SKU "
            "(entity template) — pilot scope must be authored first; "
            "this script does NOT auto-create scope"
        )
    check(True, f"entity_id={entity_id} has {active_count} active scope SKU(s)")
    return active_count


# ---------------------------------------------------------------------------
# Step 4 — cleanup
# ---------------------------------------------------------------------------

def step_cleanup() -> None:
    print("\n--- Step 4: Cleanup ---")
    if not CLEAN:
        info("CLEAN=false — skipping cleanup")
        return
    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=VALIDATE_CYCLE_CODE).first()
        if cycle is None:
            info(f"No prior cycle '{VALIDATE_CYCLE_CODE}' to clean up")
            return
        deleted_snapshots = (
            session.query(SoaTruecostSnapshot).filter_by(cycle_id=cycle.id).delete()
        )
        session.query(SoaScopeSku).filter_by(cycle_id=cycle.id).delete()
        session.execute(
            text("DELETE FROM soa_cycle_entities WHERE cycle_id = :cid"), {"cid": cycle.id}
        )
        # truecost cycles never legitimately produce soa_runs/coded_mentions/
        # other_mentions/metrics_results/incentive_scores rows. If any exist
        # for this cycle_id (e.g. a stale Postgres sequence reused this id
        # after an earlier, unrelated cycle row was deleted), they are by
        # definition this cycle's data — delete them too rather than letting
        # the FK constraint abort the cycle delete below. We delete via raw
        # SQL (not ORM session.delete) specifically to avoid SQLAlchemy's
        # relationship-cascade trying to NULL out a NOT NULL child FK.
        run_ids = [
            r[0]
            for r in session.execute(
                text("SELECT id FROM soa_runs WHERE cycle_id = :cid"), {"cid": cycle.id}
            ).fetchall()
        ]
        if run_ids:
            warn(
                f"found {len(run_ids)} pre-existing soa_runs row(s) referencing "
                f"cycle_id={cycle.id} — deleting them as part of this cycle's "
                "cleanup (truecost cycles never write soa_runs; likely a "
                "reused Postgres sequence id from an earlier, unrelated cycle)"
            )
            session.execute(
                text(
                    "DELETE FROM soa_coded_mentions WHERE run_id = ANY(:run_ids)"
                ),
                {"run_ids": run_ids},
            )
            session.execute(
                text(
                    "DELETE FROM soa_other_mentions WHERE run_id = ANY(:run_ids)"
                ),
                {"run_ids": run_ids},
            )
            session.execute(
                text(
                    "DELETE FROM soa_incentive_scores WHERE run_id = ANY(:run_ids)"
                ),
                {"run_ids": run_ids},
            )
            session.execute(
                text("DELETE FROM soa_runs WHERE cycle_id = :cid"), {"cid": cycle.id}
            )
        session.execute(
            text("DELETE FROM soa_metrics_results WHERE cycle_id = :cid"), {"cid": cycle.id}
        )
        session.execute(text("DELETE FROM soa_cycles WHERE id = :cid"), {"cid": cycle.id})
        session.commit()
        info(
            f"Deleted prior cycle '{VALIDATE_CYCLE_CODE}' (id={cycle.id}), "
            f"{deleted_snapshots} snapshot row(s), its frozen scope SKUs, "
            "and its cycle_entities rows"
        )


# ---------------------------------------------------------------------------
# Step 5 — create the truecost cycle
# ---------------------------------------------------------------------------

def _resolve_org_id(session) -> int:
    if VALIDATE_ORG_ID:
        return int(VALIDATE_ORG_ID)
    row = (
        session.query(SoaCycle.organization_id)
        .order_by(SoaCycle.id.desc())
        .first()
    )
    if row and row[0] is not None:
        return row[0]
    org = session.query(Organization).first()
    if org is not None:
        return org.id
    raise RuntimeError(
        "Could not resolve an organization_id — set VALIDATE_ORG_ID explicitly"
    )


def step_create_cycle(entity_id: int, tiers: list[str | None]) -> int:
    print("\n--- Step 5: Create truecost cycle ---")

    api_payload = {
        "cycle_code": VALIDATE_CYCLE_CODE,
        "cycle_mode": "truecost",
        "truecost_tiers": tiers,
        "comparison_set": [
            {"entity_id": entity_id, "comparison_code": "M001", "role": "primary"}
        ],
    }
    api_accepted = False
    try:
        resp = httpx.post(f"{API_BASE}/api/cycles", json=api_payload, timeout=10.0)
        if resp.status_code in (200, 201):
            body = resp.json()
            with session_factory() as session:
                cycle = session.query(SoaCycle).filter_by(cycle_code=VALIDATE_CYCLE_CODE).first()
                if cycle is not None and cycle.cycle_mode == "truecost":
                    api_accepted = True
                    cycle_id = cycle.id
        if not api_accepted:
            warn(
                "Cycle-create API responded but did not produce a "
                f"cycle_mode='truecost' row (status={resp.status_code}, "
                f"body={resp.text[:300]!r}) — falling back to a direct DB "
                "insert. FINDING: POST /api/cycles does not yet accept "
                "cycle_mode/truecost_tiers."
            )
    except Exception as exc:
        warn(
            f"Cycle-create API call failed ({exc}) — falling back to a "
            "direct DB insert. FINDING: POST /api/cycles does not yet "
            "accept cycle_mode/truecost_tiers (or is unreachable without "
            "an API token)."
        )

    if not api_accepted:
        import datetime

        with session_factory() as session:
            org_id = _resolve_org_id(session)
            cycle = SoaCycle(
                cycle_code=VALIDATE_CYCLE_CODE,
                start_date=datetime.date.today(),
                status="planned",
                cycle_mode="truecost",
                truecost_tiers=tiers,
                organization_id=org_id,
                created_by="validate_truecost_sweep.py",
            )
            session.add(cycle)
            session.flush()
            cycle_id = cycle.id

            from soa_shared.models.soa_models import SoaCycleEntity

            session.add(
                SoaCycleEntity(
                    cycle_id=cycle_id,
                    entity_id=entity_id,
                    comparison_code="M001",
                    role="primary",
                )
            )
            session.commit()
        info(f"Created cycle '{VALIDATE_CYCLE_CODE}' via direct DB insert (id={cycle_id})")
    else:
        info(f"Created cycle '{VALIDATE_CYCLE_CODE}' via POST /api/cycles (id={cycle_id})")

    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(id=cycle_id).first()
        ok = (
            cycle is not None
            and cycle.cycle_mode == "truecost"
            and cycle.truecost_tiers == tiers
        )
    check(ok, "Cycle row has cycle_mode='truecost' and truecost_tiers persisted")
    return cycle_id


# ---------------------------------------------------------------------------
# Step 6 — run the sweep
# ---------------------------------------------------------------------------

def step_run_sweep() -> None:
    print("\n--- Step 6: Run sweep ---")
    summary = asyncio.run(run_truecost_sweep(VALIDATE_CYCLE_CODE))
    info(
        f"Sweep summary: sku_count={summary.sku_count} tier_count={summary.tier_count} "
        f"captured={summary.captured} unavailable={summary.unavailable} "
        f"skipped_already_done={summary.skipped_already_done} "
        f"total_planned={summary.total_planned}"
    )
    check(True, "Sweep executor (run_truecost_sweep) completed without raising")


# ---------------------------------------------------------------------------
# Step 7 — verify snapshot rows
# ---------------------------------------------------------------------------

def step_verify_snapshots(cycle_id: int, expected_sku_count: int, tiers: list[str | None]) -> None:
    print("\n--- Step 7: Verify snapshot rows ---")
    with session_factory() as session:
        frozen_skus = (
            session.query(SoaScopeSku)
            .filter(
                SoaScopeSku.cycle_id == cycle_id,
                SoaScopeSku.is_active.is_(True),
            )
            .all()
        )
        snapshots = (
            session.query(SoaTruecostSnapshot)
            .filter_by(cycle_id=cycle_id)
            .order_by(SoaTruecostSnapshot.scope_sku_id, SoaTruecostSnapshot.id)
            .all()
        )
        for s in frozen_skus + snapshots:
            session.expunge(s)

    expected_count = len(frozen_skus) * len(tiers)
    check(
        len(snapshots) == expected_count,
        f"row_count == frozen_sku_count * tier_count "
        f"({len(snapshots)} == {len(frozen_skus)} * {len(tiers)} = {expected_count})",
    )
    check(
        len(frozen_skus) == expected_sku_count,
        f"frozen scope SKU count matches pre-sweep active scope count "
        f"({len(frozen_skus)} == {expected_sku_count})",
    )

    # 7b. one refresh per SKU; listed_price identical across a SKU's tiers
    by_sku: dict[int, list] = {}
    for snap in snapshots:
        by_sku.setdefault(snap.scope_sku_id, []).append(snap)

    refresh_ok = True
    price_consistency_ok = True
    for sku_id, rows in by_sku.items():
        refreshed = [r for r in rows if r.price_was_refreshed]
        if len(refreshed) != 1:
            refresh_ok = False
            warn(
                f"scope_sku_id={sku_id} has {len(refreshed)} price_was_refreshed=true "
                "rows (expected exactly 1)"
            )
        captured_prices = {
            float(r.listed_price) for r in rows if r.status == "captured" and r.listed_price is not None
        }
        if len(captured_prices) > 1:
            price_consistency_ok = False
            warn(f"scope_sku_id={sku_id} has inconsistent listed_price across tiers: {captured_prices}")

    check(refresh_ok, "price_was_refreshed is true exactly once per SKU")
    check(price_consistency_ok, "listed_price is identical across a SKU's tier rows")

    # 7c. status values + ground_truth_unavailable accounting
    valid_statuses = {"captured", "ground_truth_unavailable"}
    bad_status = [s for s in snapshots if s.status not in valid_statuses]
    check(not bad_status, "every snapshot status is in {'captured','ground_truth_unavailable'}")

    captured_n = sum(1 for s in snapshots if s.status == "captured")
    unavailable = [s for s in snapshots if s.status == "ground_truth_unavailable"]
    info(f"status counts: captured={captured_n} ground_truth_unavailable={len(unavailable)}")
    if unavailable:
        warn(f"{len(unavailable)} row(s) ground_truth_unavailable (soft warning, not a hard fail):")
        for s in unavailable:
            print(f"         scope_sku_id={s.scope_sku_id} tier={s.user_tier_name} error={s.error_message}")

    # 7d. tier delta (soft)
    print()
    any_delta_checked = False
    delta_ok = True
    saw_deal_delta = False
    for sku_id, rows in by_sku.items():
        baseline = next((r for r in rows if r.user_tier_name is None and r.status == "captured"), None)
        if baseline is None:
            continue
        for r in rows:
            if r.user_tier_name is None or r.status != "captured":
                continue
            any_delta_checked = True
            if (r.applied_deals or []) != (baseline.applied_deals or []):
                saw_deal_delta = True
                if r.true_cost is not None and baseline.true_cost is not None:
                    if float(r.true_cost) > float(baseline.true_cost):
                        delta_ok = False
                        warn(
                            f"scope_sku_id={sku_id} tier={r.user_tier_name} true_cost "
                            f"({r.true_cost}) > baseline true_cost ({baseline.true_cost}) "
                            "despite a different deal set"
                        )

    if saw_deal_delta:
        check(delta_ok, "member tier true_cost <= baseline true_cost wherever applied_deals differ")
    else:
        info("no live-deal delta — baseline (no-deal) state, true_cost == listed_price")
        for sku_id, rows in by_sku.items():
            for r in rows:
                if r.status != "captured" or r.true_cost is None or r.listed_price is None:
                    continue
                if abs(float(r.true_cost) - float(r.listed_price)) > 0.01:
                    info(
                        f"  note: scope_sku_id={sku_id} tier={r.user_tier_name} true_cost "
                        f"({r.true_cost}) != listed_price ({r.listed_price}) despite no deal delta"
                    )


# ---------------------------------------------------------------------------
# Step 8 — read endpoint
# ---------------------------------------------------------------------------

def step_read_endpoint(cycle_id: int) -> None:
    print("\n--- Step 8: Read endpoint ---")
    if not API_TOKEN:
        info("API_TOKEN not set — SKIPPING read-endpoint check")
        return

    with session_factory() as session:
        db_row_count = (
            session.query(SoaTruecostSnapshot).filter_by(cycle_id=cycle_id).count()
        )

    try:
        resp = httpx.get(
            f"{API_BASE}/api/cycles/{VALIDATE_CYCLE_CODE}/truecost-snapshots",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=10.0,
        )
    except Exception as exc:
        check(False, f"GET /api/cycles/{VALIDATE_CYCLE_CODE}/truecost-snapshots reachable: {exc}")
        return

    if resp.status_code != 200:
        check(
            False,
            f"GET /api/cycles/{VALIDATE_CYCLE_CODE}/truecost-snapshots returned "
            f"{resp.status_code}: {resp.text[:300]!r}",
        )
        return

    body = resp.json()
    endpoint_row_count = sum(len(sku.get("tiers", [])) for sku in body.get("skus", []))
    check(
        endpoint_row_count == db_row_count,
        f"read endpoint row count matches DB row count ({endpoint_row_count} == {db_row_count})",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not VALIDATE_ENTITY_ID:
        fatal("VALIDATE_ENTITY_ID env var is required")
    entity_id = int(VALIDATE_ENTITY_ID)
    tiers = parse_tiers(VALIDATE_TIERS)
    info(f"entity_id={entity_id} tiers={tiers} cycle_code='{VALIDATE_CYCLE_CODE}' CLEAN={CLEAN}")

    step_preflight()
    step_schema()
    active_scope_count = step_scope_present(entity_id)
    step_cleanup()
    cycle_id = step_create_cycle(entity_id, tiers)
    step_run_sweep()

    with session_factory() as session:
        cycle_row = session.query(SoaCycle).filter_by(id=cycle_id).first()
        resolved_tiers = resolve_tiers(cycle_row)

    step_verify_snapshots(cycle_id, active_scope_count, resolved_tiers)
    step_read_endpoint(cycle_id)

    print_summary()
    sys.exit(0 if all(ok for ok, _ in results) else 1)


if __name__ == "__main__":
    main()
