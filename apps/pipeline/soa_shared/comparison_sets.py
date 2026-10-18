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

  1. The study's latest cycle has entities: copied, and (2I-6) the
     merchant's current competitor list (rule 3) is added after them: the
     rivals are the previous cycle's rivals, then any listed domain not yet
     among them, in list order, numbered on from the last code. A domain
     removed from the list stays in the set until an operator removes it
     from the cycle's entities: a set only grows by itself, so a later
     cycle still compares against what the earlier ones did. A study with
     no merchant, or a list that cannot be read, is copied as it was (a
     later cycle picks the addition up; nothing is lost by waiting).
  2. Else the study's merchant, tier_config.merchant.slug else
     syndicated_merchant (elton-parleo/soa#120 sets one of them on every
     console study), is the primary, M001: its soa_entities row by slug,
     created when there is none from supply's /tenant record (name, own
     domain); the domain is stored as an alias and as website_url.
  3. The rivals are the merchant's comparison_domains from supply's
     GET /merchants/{slug}/retailers (2A-4), in its order, M002 onward: each
     the soa_entities row whose alias or website_url is that domain, else a
     new row NAMED BY ITS DOMAIN. 2I-6: the soa wizard and Command Center
     save each competitor as name + domain (upsert_competitor below), so a
     listed domain normally has its named entity before any cycle reads it;
     the domain-named row is for a list entered on supply directly. An
     empty list: the primary alone.
  4. A study whose merchant cannot be resolved (no job row in this org, or
     a job naming no merchant: a study generated before #120): []. The
     caller fails with "the study belongs to no merchant".

`supply` is anything with the TrueSyncCatalogClient's two synchronous
reads, each (payload, error): merchant_record(slug) and retailers(slug).
A first cycle reads what it has to create and the rivals; a later cycle
reads the rivals only. On a first cycle a read that fails raises
ComparisonSetError with the reason: a first cycle is not created on a
guessed set, because every later cycle starts from it.
"""
import json
import logging
from typing import List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

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


def match_entity(conn, domain: str, known: Optional[List[dict]] = None) -> Optional[int]:
    """The soa_entities row whose alias or website_url host is `domain`, else None."""
    if known is None:
        known = [dict(r) for r in conn.execute(text(
            "SELECT id, website_url, aliases FROM soa_entities ORDER BY id")).mappings()]
    return next((e['id'] for e in known if domain in _entity_domains(e)), None)


def upsert_competitor(conn, name: str, domain: str, entity_type: str) -> tuple:
    """2I-6: a competitor saved as name + domain, as (entity_id, action):
    `matched` (an entity with that alias or site, name kept), `renamed` (a
    match named by its domain, as rule 3 creates one, now given the name),
    `created` (name, slug from the name, website https://<domain>/, the
    domain as alias). Entities are global: nothing here deletes one."""
    domain = normalize_domain(domain)
    found = match_entity(conn, domain)
    if found is not None:
        current = conn.execute(text("SELECT name FROM soa_entities WHERE id = :i"), {'i': found}).scalar()
        if normalize_domain(current) == domain and name and normalize_domain(name) != domain:
            conn.execute(text("UPDATE soa_entities SET name = :n WHERE id = :i"), {'n': name, 'i': found})
            return found, 'renamed'
        return found, 'matched'
    created = _insert_entity(conn, name=name, slug=unique_slug(conn, slugify(name) or slugify(domain)),
                             entity_type=entity_type, domain=domain)
    return created, 'created'


def _rivals(conn, listed: List[str], *, skip: set, entity_type: str, exclude: set) -> List[int]:
    """Rule 3: each listed domain's entity (created named by its domain when
    missing), in list order, without `skip` domains or `exclude` ids."""
    known = [dict(r) for r in conn.execute(text(
        "SELECT id, website_url, aliases FROM soa_entities ORDER BY id")).mappings()]
    seen, out = set(skip), []
    for domain in (normalize_domain(d) for d in listed):
        if not domain or domain in seen:
            continue
        seen.add(domain)
        match = match_entity(conn, domain, known)
        if match is None:
            match = _insert_entity(conn, name=domain, slug=unique_slug(conn, slugify(domain)),
                                   entity_type=entity_type, domain=domain)
            known.append({'id': match, 'website_url': f"https://{domain}/", 'aliases': [domain]})
        if match not in exclude and match not in out:
            out.append(match)
    return out


def _with_added_rivals(conn, copied: List[dict], slug: Optional[str], supply) -> List[dict]:
    """Rule 1: the copy, then the listed rivals it does not hold yet."""
    if not slug or supply is None:
        return copied
    try:
        listed = _read(supply, 'retailers', slug).get('comparison_domains') or []
    except ComparisonSetError as exc:
        logger.warning("[comparison-set] %s: competitor list not read, the set is copied as it was: %s", slug, exc)
        return copied
    if not listed:
        return copied
    held = {c['entity_id'] for c in copied}
    primary = next((c['entity_id'] for c in copied if c['role'] == 'primary'), None)
    row = conn.execute(text("SELECT entity_type, website_url, aliases FROM soa_entities WHERE id = :i"),
                       {'i': primary}).mappings().fetchone() if primary is not None else None
    added = _rivals(conn, listed, skip=_entity_domains(row) if row else set(),
                    entity_type=(row or {}).get('entity_type') or 'brand', exclude=held)
    last = max((int(c['comparison_code'][1:]) for c in copied if str(c['comparison_code'])[1:].isdigit()), default=1)
    return copied + [{'entity_id': e, 'comparison_code': f"M{n:03d}", 'role': 'competitor'}
                     for n, e in enumerate(added, start=last + 1)]


def comparison_set_for_study(conn, study_type: str, org_id: int, supply=None) -> List[dict]:
    """The comparison set for the study's next cycle (the module docstring's
    rules 1-4). Writes soa_entities rows a first cycle needs; the caller owns
    the transaction."""
    copied = latest_cycle_set(conn, study_type)
    slug = study_merchant(conn, study_type, org_id)
    if copied:
        return _with_added_rivals(conn, copied, slug, supply)
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
    rivals = _rivals(conn, listed, skip=own, entity_type=kind, exclude={primary_id}) if listed else []

    out = [{'entity_id': primary_id, 'comparison_code': 'M001', 'role': 'primary'}]
    out += [{'entity_id': e, 'comparison_code': f"M{i:03d}", 'role': 'competitor'}
            for i, e in enumerate(rivals, start=2)]
    return out
