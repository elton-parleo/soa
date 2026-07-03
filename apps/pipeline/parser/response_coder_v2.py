"""
ResponseCoderV2 — pass-2 extraction for a single soa_runs row, from stored
raw_response and pass-1's existing soa_coded_mentions only (no agent
re-query, no re-derivation of mentioned/position/strength/deal_cited).
Writes to soa_price_observations / soa_citations. Never touches
soa_coded_mentions (pass 1) and never calls the incentive scorer.

See apps/pipeline/scripts/recode_cycle_pass2.py for the batch driver.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from soa_shared.database import session_factory
from soa_shared.models.soa_models import (
    SoaCitation,
    SoaCodedMention,
    SoaCycleEntity,
    SoaEntity,
    SoaPass2CodingLog,
    SoaPriceObservation,
    SoaRun,
)
from parser.coding_client_v2 import CodingClientV2
from parser.merchant_resolution import classify_attribution, load_known_merchants

logger = logging.getLogger(__name__)


@dataclass
class CodeRunV2Result:
    run_id: int
    status: str  # success / skipped / api_error / db_error
    observations_written: int
    citations_written: int
    error_message: Optional[str] = None


class ResponseCoderV2:

    def __init__(self, coding_client: CodingClientV2) -> None:
        self.coding_client = coding_client

    def _load_mentioned_entities(self, run_id: int, cycle_id: int) -> List[dict]:
        """
        Entities pass 1 confirmed mentioned in this run, as
        [{"comparison_code", "entity_id", "name"}, ...]. Reads
        soa_coded_mentions + soa_cycle_entities + soa_entities — never
        re-derives "mentioned" itself.
        """
        with session_factory() as session:
            rows = (
                session.query(SoaCodedMention.entity_id, SoaCycleEntity.comparison_code, SoaEntity.name)
                .join(SoaCycleEntity, (SoaCycleEntity.entity_id == SoaCodedMention.entity_id) & (SoaCycleEntity.cycle_id == cycle_id))
                .join(SoaEntity, SoaEntity.id == SoaCodedMention.entity_id)
                .filter(SoaCodedMention.run_id == run_id, SoaCodedMention.mentioned.is_(True))
                .all()
            )
            return [
                {"comparison_code": r.comparison_code, "entity_id": r.entity_id, "name": r.name}
                for r in rows
            ]

    async def code_run(self, run_id: int) -> CodeRunV2Result:
        with session_factory() as session:
            run: Optional[SoaRun] = session.get(SoaRun, run_id)
            if run is None:
                return CodeRunV2Result(run_id, "skipped — run not found", 0, 0, "run_id not found")
            if run.status != "success":
                return CodeRunV2Result(run_id, "skipped — run not success", 0, 0, f"run.status={run.status}")
            if not run.raw_response:
                return CodeRunV2Result(run_id, "skipped — empty response", 0, 0, "raw_response is null or empty")
            session.expunge(run)

        # Idempotency for this pass only. Checked via the sentinel log, not
        # by looking for existing observations/citations — a run that
        # legitimately produces zero of both (e.g. a pure ingredient-
        # comparison response) still needs to be recognized as "already
        # processed" so a re-run doesn't needlessly re-call the API.
        with session_factory() as session:
            already_logged = (
                session.query(SoaPass2CodingLog)
                .filter(SoaPass2CodingLog.run_id == run.id, SoaPass2CodingLog.coding_pass_version == 2)
                .first()
            )
            if already_logged is not None:
                return CodeRunV2Result(run_id, "skipped — already pass-2 coded", 0, 0)

        # No "skip if nothing mentioned" gate here — citation extraction is
        # response-level, not entity-scoped, so a response with zero
        # tracked-entity mentions (e.g. a pure third-party/medical-sourcing
        # answer) can still have real VIS-02-relevant citations worth
        # capturing. price_observations will simply be empty in that case.
        mentioned_entities = self._load_mentioned_entities(run.id, run.cycle_id)

        try:
            result = await self.coding_client.code_observations(run, mentioned_entities)
        except Exception as exc:
            logger.error("[coder_v2] run_id=%d api_error: %s", run_id, exc)
            return CodeRunV2Result(run_id, "api_error", 0, 0, str(exc))

        code_to_entity_id = {e["comparison_code"]: e["entity_id"] for e in mentioned_entities}
        entity_id_to_name = {e["entity_id"]: e["name"] for e in mentioned_entities}
        run_citation_domains = {c.domain for c in result.citations if c.domain}

        try:
            with session_factory() as session:
                known_merchants = load_known_merchants(session)

                observations_written = 0
                for obs in result.price_observations:
                    entity_id = code_to_entity_id.get(obs.comparison_code)
                    if entity_id is None:
                        logger.warning(
                            "[coder_v2] run_id=%d unknown comparison_code=%s, skipping observation",
                            run_id, obs.comparison_code,
                        )
                        continue

                    entity_name = entity_id_to_name[entity_id]
                    merchant_slug, attribution_status = classify_attribution(
                        entity_name, obs.merchant_name, known_merchants, run_citation_domains,
                    )

                    session.add(SoaPriceObservation(
                        run_id=run.id,
                        entity_id=entity_id,
                        stated_price=obs.stated_price,
                        claimed_net_price=obs.claimed_net_price,
                        claimed_discount_value=obs.claimed_discount_value,
                        claimed_discount_pct=obs.claimed_discount_pct,
                        claimed_terms=obs.claimed_terms if obs.claimed_terms else None,
                        member_price_claimed=obs.member_price_claimed,
                        subscription_offer_claimed=obs.subscription_offer_claimed,
                        merchant_name=obs.merchant_name,
                        merchant_slug=merchant_slug,
                        attribution_status=attribution_status,
                        evidence=obs.evidence,
                        coding_pass_version=2,
                    ))
                    observations_written += 1

                citations_written = 0
                for c in result.citations:
                    session.add(SoaCitation(
                        run_id=run.id, url=c.url, domain=c.domain, context=c.context,
                        coding_pass_version=2,
                    ))
                    citations_written += 1

                session.add(SoaPass2CodingLog(
                    run_id=run.id,
                    coding_pass_version=2,
                    observations_written=observations_written,
                    citations_written=citations_written,
                ))

                session.commit()
        except Exception as exc:
            logger.error("[coder_v2] run_id=%d db_error: %s", run_id, exc)
            return CodeRunV2Result(run_id, "db_error", 0, 0, str(exc))

        return CodeRunV2Result(run_id, "success", observations_written, citations_written)
