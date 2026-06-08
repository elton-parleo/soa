"""
ResponseCoder — orchestrates one complete coding operation for a single soa_runs row.
Reads run, calls CodingClient, validates, writes all mentions in a single transaction.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import joinedload

from soa_shared.database import session_factory
from soa_shared.models.soa_models import (
    SoaCycle,
    SoaCodedMention,
    SoaCycleEntity,
    SoaOtherMention,
    SoaQuery,
    SoaRun,
)
from parser.coding_client import CodingClient
from parser.validator import CodingValidator

logger = logging.getLogger(__name__)


@dataclass
class CodeRunResult:
    run_id: int
    status: str  # success / validation_error / api_error / skipped / db_error
    needs_review: bool
    merchants_coded: int
    other_merchants_found: int
    error_message: Optional[str]
    input_tokens: int = 0
    output_tokens: int = 0


class ResponseCoder:

    def __init__(self, coding_client: CodingClient, validator: CodingValidator) -> None:
        self.coding_client = coding_client
        self.validator = validator

    def _load_cycle_entities(self, cycle_id: int) -> Dict[str, int]:
        """
        Returns mapping of comparison_code → soa_entity.id for this cycle.
        e.g. {"M001": 12, "M002": 7, ...}

        Raises ValueError if no entities are configured for this cycle.
        """
        with session_factory() as session:
            ces = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=cycle_id)
                .all()
            )
            if not ces:
                raise ValueError(
                    f"No entities configured for cycle_id={cycle_id}. "
                    "Populate soa_cycle_entities before running coding."
                )
            return {ce.comparison_code: ce.entity_id for ce in ces}

    def _load_cycle_entities_full(self, cycle_id: int) -> List[SoaCycleEntity]:
        """
        Returns full SoaCycleEntity objects with entity relationship loaded.
        Used to build the coding system prompt.
        """
        with session_factory() as session:
            ces = (
                session.query(SoaCycleEntity)
                .filter_by(cycle_id=cycle_id)
                .options(joinedload(SoaCycleEntity.entity))
                .order_by(SoaCycleEntity.comparison_code)
                .all()
            )
            for ce in ces:
                session.expunge(ce)
                session.expunge(ce.entity)
            return ces

    def _load_study_pattern(self, cycle_id: int) -> str:
        with session_factory() as session:
            cycle = session.get(SoaCycle, cycle_id)
            if cycle is None:
                return "retailer"
            return cycle.study_pattern or "retailer"

    async def code_run(self, run_id: int) -> CodeRunResult:
        # 1. Load SoaRun
        with session_factory() as session:
            run: Optional[SoaRun] = session.get(SoaRun, run_id)
            if run is None:
                return CodeRunResult(
                    run_id=run_id, status="skipped — run not found",
                    needs_review=False, merchants_coded=0, other_merchants_found=0,
                    error_message="run_id not found",
                )
            if run.status != "success":
                return CodeRunResult(
                    run_id=run_id, status="skipped — run not success",
                    needs_review=False, merchants_coded=0, other_merchants_found=0,
                    error_message=f"run.status={run.status}",
                )
            if not run.raw_response:
                return CodeRunResult(
                    run_id=run_id, status="skipped — empty response",
                    needs_review=False, merchants_coded=0, other_merchants_found=0,
                    error_message="raw_response is null or empty",
                )
            session.expunge(run)

        # 2. Load query — study_pattern is read from the query, not the cycle,
        #    so each run's coding prompt rubric matches its own query's pattern.
        with session_factory() as session:
            query: Optional[SoaQuery] = session.get(SoaQuery, run.query_id)
            if query is None:
                return CodeRunResult(
                    run_id=run_id, status="skipped — query not found",
                    needs_review=False, merchants_coded=0, other_merchants_found=0,
                    error_message=f"query_id={run.query_id} not found",
                )
            query_text = query.query_text
            query_study_pattern = query.study_pattern

        # 3. Idempotency check
        with session_factory() as session:
            existing = (
                session.query(SoaCodedMention)
                .filter(SoaCodedMention.run_id == run.id)
                .first()
            )
            if existing is not None:
                return CodeRunResult(
                    run_id=run_id, status="skipped — already coded",
                    needs_review=False, merchants_coded=0, other_merchants_found=0,
                    error_message=None,
                )

        # 4. Load cycle entities for this run's cycle
        try:
            code_to_entity_id = self._load_cycle_entities(run.cycle_id)
            cycle_entities = self._load_cycle_entities_full(run.cycle_id)
        except ValueError as exc:
            logger.error("[coder] run_id=%d entity_load_error: %s", run_id, exc)
            return CodeRunResult(
                run_id=run_id, status="skipped — no cycle entities",
                needs_review=False, merchants_coded=0, other_merchants_found=0,
                error_message=str(exc),
            )

        # 5. Call CodingClient — pass query-level study_pattern so each run uses
        #    the rubric for its own query, not the cycle-level aggregate value.
        try:
            coding = await self.coding_client.code_response(
                run, query_text, cycle_entities, query_study_pattern
            )
        except Exception as exc:
            logger.error("[coder] run_id=%d api_error: %s", run_id, exc)
            return CodeRunResult(
                run_id=run_id, status="api_error",
                needs_review=False, merchants_coded=0, other_merchants_found=0,
                error_message=str(exc),
            )

        # 6. Validate
        validation = self.validator.validate(coding, run)
        for warning in validation.warnings:
            logger.warning("[coder] run_id=%d warning: %s", run_id, warning)
        if not validation.is_valid:
            for error in validation.errors:
                logger.error("[coder] run_id=%d validation_error: %s", run_id, error)
            return CodeRunResult(
                run_id=run_id, status="validation_error",
                needs_review=False, merchants_coded=0, other_merchants_found=0,
                error_message="; ".join(validation.errors),
            )

        final_needs_review = validation.should_flag_review

        # 7. Build entity_id → merchant_id lookup for backward compat with calculator.py
        entity_id_to_merchant_id: Dict[int, Optional[int]] = {}
        with session_factory() as session:
            for ce in session.query(SoaCycleEntity).filter_by(cycle_id=run.cycle_id).options(
                joinedload(SoaCycleEntity.entity)
            ).all():
                entity_id_to_merchant_id[ce.entity_id] = ce.entity.merchant_id

        # 8. Write all rows in a single transaction
        try:
            with session_factory() as session:
                try:
                    for mid, mc in coding.merchants.items():
                        entity_id = code_to_entity_id.get(mid)
                        if entity_id is None:
                            raise ValueError(
                                f"Comparison code '{mid}' not found in cycle entities."
                            )

                        # merchant_id kept for backward compat with calculator.py
                        merchant_id = entity_id_to_merchant_id.get(entity_id)

                        session.add(SoaCodedMention(
                            run_id=run.id,
                            entity_id=entity_id,
                            merchant_id=merchant_id,
                            mentioned=mc.mentioned,
                            position=mc.position if mc.mentioned else None,
                            strength=mc.strength if mc.mentioned else None,
                            deal_cited=mc.deal_cited if mc.mentioned else False,
                            deal_types=mc.deal_types if mc.deal_types else None,
                            evidence=mc.evidence,
                            coded_by="llm_auto",
                            confidence=mc.confidence,
                            needs_review=final_needs_review,
                        ))

                    for om in coding.other_merchants:
                        session.add(SoaOtherMention(
                            run_id=run.id,
                            merchant_name=om.merchant_name,
                            position=om.position,
                            strength=om.strength,
                        ))

                    session.commit()

                except Exception:
                    session.rollback()
                    raise

        except Exception as exc:
            logger.error("[coder] run_id=%d db_error: %s", run_id, exc)
            return CodeRunResult(
                run_id=run_id, status="db_error",
                needs_review=False, merchants_coded=0, other_merchants_found=0,
                error_message=str(exc),
            )

        return CodeRunResult(
            run_id=run_id,
            status="success",
            needs_review=final_needs_review,
            merchants_coded=len(coding.merchants),
            other_merchants_found=len(coding.other_merchants),
            error_message=None,
            input_tokens=coding.input_tokens,
            output_tokens=coding.output_tokens,
        )
