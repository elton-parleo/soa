"""
2I-5: a cycle's comparison set, one rule for the full loop's coordinator
(apps/pipeline/fullloop/coordinator.py) and the console's Start cycle
(apps/api/app/routers/console_ops.py). Identical in apps/api/soa_shared,
apps/pipeline/soa_shared and packages/shared/soa_shared.

A study's first cycle needs nothing declared. The mention coder learns the
brands the answers name (the ranking, "who agents name first" and the agent
columns come from coding, not from this set); the set only decides which
rivals are tracked (full rows) and which are "also named but not tracked"
(the Visibility footer, 2G).

  1. The study's latest cycle has entities: copy them (every second cycle).
  2. Else the study's merchant, tier_config.merchant.slug else
     syndicated_merchant (elton-parleo/soa#120 sets one of them on every
     console study), is the primary, M001: its soa_entities row by slug,
     created when there is none from supply's /tenant record (name, own
     domain); the domain is stored as an alias and as website_url.
  3. The rivals are the merchant's comparison_domains from supply's
     GET /merchants/{slug}/retailers (2A-4), in its order, M002 onward: each
     the soa_entities row whose alias or website_url is that domain, else a
     new row NAMED BY ITS DOMAIN. The soa wizard's competitor field (2I-6)
     will supply proper names; until then a created rival reads as its
     domain. An empty list: the primary alone.
  4. A study whose merchant cannot be resolved (no job row in this org, or
     a job naming no merchant: a study generated before #120): []. The
     caller fails with "the study belongs to no merchant".

`supply` is anything with the TrueSyncCatalogClient's two synchronous
reads, each (payload, error): merchant_record(slug) and retailers(slug).
It is only read when something has to be created or the rivals listed,
so a second cycle makes no call. A read that fails raises
ComparisonSetError with the reason: a first cycle is not created on a
guessed set, because every later cycle copies it.
"""
import json
from typing import List, Optional

from sqlalchemy import text

from soa_shared.entity_helpers import slugify, unique_slug
from soa_shared.expected_answers import normalize_domain


class ComparisonSetError(RuntimeError):
    """The set could not be built (a supply read failed); str() says why."""


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def latest_cycle_set(conn, study_type: str) -> List[dict]:
    """Rule 1: the study's latest cycle's entities, by comparison code."""
    prior = conn.execute(text(
        "SELECT id FROM soa_cycles WHERE study_type = :st ORDER BY start_date DESC, id DESC LIMIT 1"
    ), {'st': study_type}).fetchone()
    if prior is None:
        return []
    rows = conn.execute(text(
        "SELECT entity_id, comparison_code, role FROM soa_cycle_entities WHERE cycle_id = :c "
        "ORDER BY comparison_code, id"
    ), {'c': prior[0]}).mappings().all()
    return [dict(r) for r in rows]


def study_merchant(conn, study_type: str, org_id: int) -> Optional[str]:
    """The merchant the study was generated for, in this org; None when it has none."""
    job = conn.execute(text(
        "SELECT syndicated_merchant, tier_config FROM soa_query_generation_jobs "
        "WHERE study_type = :st AND COALESCE(customer_organization_id, organization_id) = :org"
    ), {'st': study_type, 'org': org_id}).mappings().fetchone()
    if job is None:
        return None
    tier = _json(job['tier_config']) or {}
    merchant = tier.get('merchant') if isinstance(tier, dict) else None
    return (merchant or {}).get('slug') or job['syndicated_merchant'] or None


def _entity_domains(row) -> set:
    found = {normalize_domain(a) for a in (_json(row['aliases']) or []) if isinstance(a, str)}
    found.add(normalize_domain(row['website_url']))
    return {d for d in found if d}


def _insert_entity(conn, *, name: str, slug: str, entity_type: str, domain: Optional[str]) -> int:
    return conn.execute(text(
        "INSERT INTO soa_entities (name, slug, entity_type, website_url, aliases) "
        "VALUES (:name, :slug, :type, :url, :aliases) RETURNING id"
    ), {'name': name, 'slug': slug, 'type': entity_type,
        'url': f"https://{domain}/" if domain else None,
        'aliases': json.dumps([domain] if domain else [])}).scalar()


def _read(supply, method: str, slug: str):
    if supply is None:
        raise ComparisonSetError(f"TrueSync was not asked for {slug!r}'s {method.replace('_', ' ')}")
    payload, error = getattr(supply, method)(slug)
    if error is not None:
        raise ComparisonSetError(f"could not read {slug!r}'s {method.replace('_', ' ')} from TrueSync: {error}")
    return payload or {}


def comparison_set_for_study(conn, study_type: str, org_id: int, supply=None) -> List[dict]:
    """The comparison set for the study's next cycle (the module docstring's
    rules 1-4). Writes soa_entities rows a first cycle needs; the caller owns
    the transaction."""
    copied = latest_cycle_set(conn, study_type)
    if copied:
        return copied
    slug = study_merchant(conn, study_type, org_id)
    if not slug:
        return []

    primary = conn.execute(text("SELECT id, entity_type, website_url, aliases FROM soa_entities WHERE slug = :s"),
                           {'s': slug}).mappings().fetchone()
    if primary is None:
        record = _read(supply, 'merchant_record', slug)
        domain = normalize_domain(record.get('domain') or (record.get('own_domains') or [None])[0])
        kind = 'brand' if record.get('kind') == 'brand' else 'retailer'
        primary_id = _insert_entity(conn, name=record.get('name') or slug, slug=slug, entity_type=kind, domain=domain)
        own = {domain} if domain else set()
    else:
        primary_id, kind, own = primary['id'], primary['entity_type'], _entity_domains(primary)

    listed = _read(supply, 'retailers', slug).get('comparison_domains') or []
    rivals: List[int] = []
    if listed:
        known = [dict(r) for r in conn.execute(text(
            "SELECT id, website_url, aliases FROM soa_entities ORDER BY id")).mappings()]
        seen = set(own)
        for domain in (normalize_domain(d) for d in listed):
            if not domain or domain in seen:
                continue
            seen.add(domain)
            match = next((e['id'] for e in known if domain in _entity_domains(e)), None)
            if match is None:
                match = _insert_entity(conn, name=domain, slug=unique_slug(conn, slugify(domain)),
                                       entity_type=kind, domain=domain)
            if match != primary_id and match not in rivals:
                rivals.append(match)

    out = [{'entity_id': primary_id, 'comparison_code': 'M001', 'role': 'primary'}]
    out += [{'entity_id': e, 'comparison_code': f"M{i:03d}", 'role': 'competitor'}
            for i, e in enumerate(rivals, start=2)]
    return out
