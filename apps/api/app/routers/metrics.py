"""
Metrics endpoints for the SoA Platform API.

Join strategy (confirmed by Phase 0 audit):
  soa_dashboard_summary.merchant_slug = soa_entities.slug
  100% slug intersection verified for all complete cycles.

  RSI: raw DB value (-1.0 to +3.0) returned as-is (Option B denominator
  divides by total mentions). Frontend handles relative min-max
  normalisation for scatter chart layout and raw display in scorecard.

  All other ratios (mention_rate, soa_pct, position_index,
  deal_citation_rate, platform_dist_index) are 0.0-1.0 ratios
  normalized via normalize_metric() × 100.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from soa_shared.database import engine
from app.schemas import (
    CycleEntitiesResponse,
    CycleEntityInfo,
    normalize_metric,
    # normalize_rsi intentionally omitted: RSI now sent as raw DB value
)

router = APIRouter()

# ─── Slice type mapping ────────────────────────────────────────────────────────
# DB slice_type values → frontend key names
SLICE_TYPE_MAP = {
    "overall":     "overall",
    "stage":       "by_stage",
    "platform":    "by_platform",
    "category":    "by_category",
    "persona":     "by_persona",
    "specificity": "by_specificity",
}


# ─── GET /api/cycles/{cycle_code}/entities ────────────────────────────────────

@router.get(
    "/cycles/{cycle_code}/entities",
    response_model=CycleEntitiesResponse,
)
def get_cycle_entities(cycle_code: str):
    """
    Returns the comparison set for a cycle with entity names, slugs,
    roles, and comparison codes.
    Reads from soa_cycle_entities joined to soa_entities and soa_cycles.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
              ce.comparison_code,
              ce.role,
              e.name,
              e.slug,
              e.entity_type,
              e.category
            FROM soa_cycle_entities ce
            JOIN soa_cycles c
              ON c.id = ce.cycle_id
            JOIN soa_entities e
              ON e.id = ce.entity_id
            WHERE c.cycle_code = :code
            ORDER BY ce.comparison_code
        """), {"code": cycle_code}).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No entities found for cycle '{cycle_code}'. "
                f"Check the cycle code and comparison set."
            ),
        )

    entities = [
        CycleEntityInfo(
            code=r[0],
            role=r[1],
            name=r[2],
            slug=r[3],
            entity_type=r[4],
            category=r[5],
        )
        for r in rows
    ]

    return CycleEntitiesResponse(
        cycle_code=cycle_code,
        entities=entities,
    )


# ─── GET /api/cycles/{cycle_code}/metrics ────────────────────────────────────

@router.get("/cycles/{cycle_code}/metrics")
def get_cycle_metrics(cycle_code: str):
    """
    Returns all metric values for a cycle organized by slice type and entity.

    Data source: soa_dashboard_summary
    All raw values (0.0-1.0 ratios) normalized to 0-100 scale.
    RSI: raw DB value (-1.0 to +3.0) — no scaling applied.

    Response shape:
    {
      "cycle_code": "...",
      "entities": [...],
      "slices": {
        "overall": {
          "M001": { mention_rate, som, rsi, position_index,
                    pdi, deal_citation_rate, total_runs,
                    total_mentions },
          ...
        },
        "by_stage": {
          "Research": { "M001": {...}, ... },
          ...
        },
        "by_platform": { ... },
        "by_category": { ... },
      }
    }
    """
    with engine.connect() as conn:

        # Step 1: Get comparison set for this cycle
        entity_rows = conn.execute(text("""
            SELECT
              ce.comparison_code,
              ce.role,
              e.name,
              e.slug,
              e.entity_type,
              e.category
            FROM soa_cycle_entities ce
            JOIN soa_cycles c
              ON c.id = ce.cycle_id
            JOIN soa_entities e
              ON e.id = ce.entity_id
            WHERE c.cycle_code = :code
            ORDER BY ce.comparison_code
        """), {"code": cycle_code}).fetchall()

        if not entity_rows:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No entities found for cycle '{cycle_code}'."
                ),
            )

        # Build slug → comparison_code map
        # Confirmed join key: merchant_slug = entity.slug
        slug_to_code = {r[3]: r[0] for r in entity_rows}  # slug: comp_code
        name_to_code = {
            r[2].lower().strip(): r[0] for r in entity_rows
        }  # fallback: name match

        entities = [
            CycleEntityInfo(
                code=r[0],
                role=r[1],
                name=r[2],
                slug=r[3],
                entity_type=r[4],
                category=r[5],
            )
            for r in entity_rows
        ]

        # Step 2: Fetch all dashboard summary rows for this cycle
        summary_rows = conn.execute(text("""
            SELECT
              merchant_slug,
              merchant_name,
              slice_type,
              slice_value,
              total_runs,
              total_mentions,
              mention_rate,
              soa_pct,
              position_index,
              rsi_score,
              deal_citation_rate,
              platform_dist_index
            FROM soa_dashboard_summary
            WHERE cycle_code = :code
            ORDER BY slice_type, slice_value, merchant_slug
        """), {"code": cycle_code}).fetchall()

    if not summary_rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No metrics data found for cycle '{cycle_code}'. "
                f"Run the metrics calculator first: "
                f"python main.py metrics --cycle {cycle_code}"
            ),
        )

    def build_entity_metrics(row) -> dict:
        """
        Normalize one soa_dashboard_summary row.
        mention_rate, soa_pct, position_index, deal_citation_rate,
        platform_dist_index are 0.0-1.0 → normalize_metric() × 100.
        rsi_score is sent as the raw DB value (-1.0 to +3.0) — no scaling.
        The frontend applies relative min-max normalization for chart layout
        and displays the raw value in the scorecard.
        """
        return {
            "mention_rate":       normalize_metric(row[6]),
            "som":                normalize_metric(row[7]),
            "position_index":     normalize_metric(row[8]),
            "rsi":                (
                round(float(row[9]), 2)
                if row[9] is not None
                else None
            ),
            "deal_citation_rate": normalize_metric(row[10]),
            "pdi":                normalize_metric(row[11]),  # often None
            "total_runs":         row[4],
            "total_mentions":     row[5],
        }

    # Step 3: Organize rows into slices dict
    slices: dict = {}

    for row in summary_rows:
        m_slug      = row[0]   # merchant_slug
        m_name      = row[1]   # merchant_name
        slice_type  = row[2]
        slice_value = row[3]

        # Resolve comparison code: slug match first, name match as fallback
        comp_code = slug_to_code.get(m_slug)
        if not comp_code and m_name:
            comp_code = name_to_code.get(m_name.lower().strip())
        if not comp_code:
            # Entity from dashboard not in comparison set — skip
            continue

        mapped_slice  = SLICE_TYPE_MAP.get(slice_type, slice_type)
        metrics_dict  = build_entity_metrics(row)

        if slice_type == "overall":
            if "overall" not in slices:
                slices["overall"] = {}
            slices["overall"][comp_code] = metrics_dict
        else:
            if mapped_slice not in slices:
                slices[mapped_slice] = {}
            if slice_value not in slices[mapped_slice]:
                slices[mapped_slice][slice_value] = {}
            slices[mapped_slice][slice_value][comp_code] = metrics_dict

    return {
        "cycle_code": cycle_code,
        "entities":   [e.model_dump() for e in entities],
        "slices":     slices,
    }


# ─── GET /api/cycles/{cycle_code}/positions ───────────────────────────────────

@router.get(
    "/cycles/{cycle_code}/positions",
    response_model=None,
)
def get_cycle_positions(cycle_code: str):
    """
    Returns position distribution for each entity in the cycle.

    Data source: soa_coded_mentions
    Only rows where mentioned = true AND position IS NOT NULL are counted.
    Some rows have mentioned=true but null position — these are excluded.

    Position groupings:
      top: position = 1
      mid: position IN (2, 3)
      low: position >= 4

    Returns percentages (0-100) based on total mentions per entity.
    """
    from app.schemas import (
        EntityPositionBreakdown,
        CyclePositionsResponse,
    )
    from collections import defaultdict

    with engine.connect() as conn:

        # Verify cycle exists and get its ID
        cycle = conn.execute(text("""
            SELECT id FROM soa_cycles
            WHERE cycle_code = :code
        """), {"code": cycle_code}).fetchone()

        if not cycle:
            raise HTTPException(
                status_code=404,
                detail=f"Cycle '{cycle_code}' not found.",
            )

        # Get position counts per entity
        # Only mentioned=true rows with a non-null position value
        rows = conn.execute(text("""
            SELECT
              ce.comparison_code,
              cm.position,
              COUNT(*) AS cnt
            FROM soa_coded_mentions cm
            JOIN soa_runs r
              ON r.id = cm.run_id
            JOIN soa_cycle_entities ce
              ON ce.cycle_id = r.cycle_id
              AND ce.entity_id = cm.entity_id
            WHERE r.cycle_id = :cid
            AND cm.mentioned = true
            AND cm.position IS NOT NULL
            GROUP BY
              ce.comparison_code,
              cm.position
            ORDER BY
              ce.comparison_code,
              cm.position
        """), {"cid": cycle[0]}).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No position data found for cycle '{cycle_code}'. "
                f"Ensure coding has been run for this cycle."
            ),
        )

    # Aggregate counts by comparison_code
    counts = defaultdict(lambda: {"top": 0, "mid": 0, "low": 0})

    for row in rows:
        comp_code = row[0]
        position  = row[1]
        cnt       = row[2]

        if position == 1:
            counts[comp_code]["top"] += cnt
        elif position in (2, 3):
            counts[comp_code]["mid"] += cnt
        else:
            # position >= 4
            counts[comp_code]["low"] += cnt

    # Convert counts to percentages
    positions = {}
    for comp_code, c in counts.items():
        total = c["top"] + c["mid"] + c["low"]
        if total == 0:
            continue
        positions[comp_code] = EntityPositionBreakdown(
            top=round(c["top"] / total * 100, 1),
            mid=round(c["mid"] / total * 100, 1),
            low=round(c["low"] / total * 100, 1),
            mention_count=total,
        )

    return CyclePositionsResponse(
        cycle_code=cycle_code,
        positions={k: v.model_dump() for k, v in positions.items()},
    )
