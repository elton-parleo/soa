"""
2I-9: the revenue model behind the console's Impact screen, its Overview
block and the dollars on the screens the demo puts them on.

The model is the console demo's (parleohq/truesync apps/console/src/data/
v2common.ts computeRevenue), unchanged: the console computes the dollars; soa
serves the inputs and the measured shares in the RevenueModel shape it takes.

Inputs (B1): one row per org x merchant (soa_merchant_revenue_inputs), the
merchant's sales in scope and its own values of the three public parameters
and the win-back share of Lost. A null field reads the default
(soa_shared/revenue.py); sales in scope has none, and with no sales in scope
the console shows the shares and no dollars. Sales in scope is a customer's
financial figure: it is served on that merchant's own console reads (these
endpoints) and nowhere else.

Pure functions over rows (the loaders at the bottom do the SQL).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from soa_shared import revenue as defaults

INPUT_FIELDS = ('scope_value', 'scope_display', 'scope_source', 'influence', 'horizon', 'penalty', 'lost_gainable',
                'currency')


def _billions(value: float, cur: str) -> str:
    """$3.99e9 -> '$4.0B', as the demo's scope display reads."""
    a = float(value)
    if a >= 1e9:
        return f"{cur}{a / 1e9:.{0 if a >= 1e10 else 1}f}B"
    if a >= 1e6:
        return f"{cur}{a / 1e6:.{1 if a < 9.95e6 else 0}f}M"
    return f"{cur}{a:,.0f}"


def inputs_view(row: Optional[dict], merchant: str) -> dict:
    """The inputs as the console reads them: each field with its value, its
    display, its source line and whether it is the default. Sales in scope
    with no value is `entered: false`."""
    row = row or {}
    cur = row.get('currency') or defaults.DEFAULT_CURRENCY
    scope_value = row.get('scope_value')
    scope_value = float(scope_value) if scope_value is not None else None
    out = {
        'merchant': merchant,
        'currency': cur,
        'scope': {'label': defaults.SCOPE['label'], 'value': scope_value, 'entered': scope_value is not None,
                  'display': (row.get('scope_display') or _billions(scope_value, cur)) if scope_value is not None else None,
                  'source': row.get('scope_source') or defaults.SCOPE['source']},
        'updated_by': row.get('updated_by'),
        'updated_at': _iso(row.get('updated_at')),
        'saved': bool(row),
    }
    for field, d in defaults.SHARE_DEFAULTS.items():
        v = row.get(field)
        value = float(v) if v is not None else d['value']
        out[field] = {'label': d['label'], 'value': value, 'display': defaults.display_share(value),
                      'source': d['source'], 'default': v is None, 'default_value': d['value']}
    return out


def _iso(v) -> Optional[str]:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, 'isoformat') else str(v)


class InputError(ValueError):
    """A value the inputs refuse, with the reason."""


def validated(body: dict) -> dict:
    """The fields of a PUT body to write: those sent, each checked. A field
    sent as null resets to its default. Unknown fields are refused."""
    unknown = set(body) - set(INPUT_FIELDS)
    if unknown:
        raise InputError(f"unknown field {sorted(unknown)[0]!r}")
    out = {}
    for field, value in body.items():
        if field in defaults.RANGES:
            why = defaults.out_of_range(field, value)
            if why:
                raise InputError(why)
            out[field] = None if value is None else float(value)
        elif field == 'currency':
            if value is not None and value not in defaults.CURRENCIES:
                raise InputError(f"currency must be one of {', '.join(repr(c) for c in defaults.CURRENCIES)}")
            out[field] = value
        else:
            if value is not None and (not isinstance(value, str) or len(value) > 600):
                raise InputError(f'{field} must be text of at most 600 characters')
            out[field] = value.strip() or None if isinstance(value, str) else None
    return out


# ─── loaders ───────────────────────────────────────────────────────────────

def load_inputs(conn, org_id: int, merchant: str) -> Optional[dict]:
    row = conn.execute(text("""
        SELECT * FROM soa_merchant_revenue_inputs WHERE org_id = :o AND merchant_slug = :m
    """), {'o': org_id, 'm': merchant}).mappings().fetchone()
    return dict(row) if row else None


def save_inputs(conn, org_id: int, merchant: str, fields: dict, user: Optional[str]) -> None:
    """Upsert the fields sent (the others keep their stored value)."""
    current = load_inputs(conn, org_id, merchant)
    now = datetime.now(timezone.utc)
    if current is None:
        values = {f: fields.get(f) for f in INPUT_FIELDS}
        conn.execute(text(f"""
            INSERT INTO soa_merchant_revenue_inputs (org_id, merchant_slug, {', '.join(INPUT_FIELDS)}, updated_by, updated_at)
            VALUES (:org_id, :merchant_slug, {', '.join(':' + f for f in INPUT_FIELDS)}, :updated_by, :updated_at)
        """), {'org_id': org_id, 'merchant_slug': merchant, **values, 'updated_by': user, 'updated_at': now})
        return
    if not fields:
        return
    sets = ', '.join(f"{f} = :{f}" for f in fields)
    conn.execute(text(f"""
        UPDATE soa_merchant_revenue_inputs SET {sets}, updated_by = :updated_by, updated_at = :updated_at
        WHERE org_id = :org_id AND merchant_slug = :merchant_slug
    """), {**fields, 'updated_by': user, 'updated_at': now, 'org_id': org_id, 'merchant_slug': merchant})


def delete_inputs(conn, org_id: int, merchant: str) -> None:
    conn.execute(text("DELETE FROM soa_merchant_revenue_inputs WHERE org_id = :o AND merchant_slug = :m"),
                 {'o': org_id, 'm': merchant})
