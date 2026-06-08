"""
CodingClient — wraps the gpt-5.4-nano Responses API call with structured
JSON output enforcement. One call per soa_runs row.
"""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, List

from openai import AsyncOpenAI

import soa_shared.config as config
from soa_shared.models.soa_models import SoaRun
from parser.coding_response import CodingResponse, MerchantCoding, OtherMerchantCoding
from parser.prompts import build_coding_schema, build_system_prompt

if TYPE_CHECKING:
    from models.soa_models import SoaCycleEntity

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 5


class CodingClient:

    def __init__(self) -> None:
        if not config.OPEN_AI_API_KEY:
            raise RuntimeError("OPEN_AI_API_KEY is not set. Add it to /soa/.env.")
        self.model = "gpt-5.4-mini" #"gpt-5.4-nano-2026-03-17"
        self._client = AsyncOpenAI(api_key=config.OPEN_AI_API_KEY)

    async def code_response(
        self,
        run: SoaRun,
        query_text: str,
        cycle_entities: "List[SoaCycleEntity]",
        study_pattern: str,
    ) -> CodingResponse:
        system_prompt = build_system_prompt(
            cycle_entities=cycle_entities,
            study_pattern=study_pattern,
        )
        comparison_codes = sorted(ce.comparison_code for ce in cycle_entities)
        coding_schema = build_coding_schema(comparison_codes)

        user_message = (
            f"Query submitted to agent: {query_text}\n"
            f"Web search triggered: {run.search_triggered}\n"
            f"Platform: {run.platform}\n\n"
            f"Agent response to code:\n{run.raw_response}"
        )

        t0 = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, 3):  # max 2 attempts
            try:
                response = await self._client.responses.create(
                    model=self.model,
                    instructions=system_prompt,
                    input=[{"role": "user", "content": user_message}],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "entity_coding_schema",
                            "schema": coding_schema,
                            "strict": True,
                        }
                    },
                )
                latency_ms = int((time.monotonic() - t0) * 1000)

                result = json.loads(response.output_text)
                usage = response.usage

                merchants: dict[str, MerchantCoding] = {}
                for mid, data in result["merchants"].items():
                    merchants[mid] = MerchantCoding(
                        merchant_id=mid,
                        mentioned=data["mentioned"],
                        position=data["position"],
                        strength=data["strength"],
                        deal_cited=data["deal_cited"],
                        deal_types=data["deal_types"] or [],
                        evidence=data["evidence"],
                        confidence=data["confidence"],
                    )

                other_merchants = [
                    OtherMerchantCoding(
                        merchant_name=om["merchant_name"],
                        position=om["position"],
                        strength=om["strength"],
                    )
                    for om in result["other_merchants"]
                ]

                logger.info(
                    "[coding] run_id=%d model=%s latency=%dms attempt=%d",
                    run.id, self.model, latency_ms, attempt,
                )

                return CodingResponse(
                    run_id=run.id,
                    merchants=merchants,
                    other_merchants=other_merchants,
                    needs_review=result["needs_review"],
                    coder_notes=result["coder_notes"],
                    coding_latency_ms=latency_ms,
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                )

            except Exception as exc:
                last_exc = exc
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.error(
                    "[coding] run_id=%d attempt=%d/%d FAILED after %dms: %s",
                    run.id, attempt, 2, latency_ms, exc,
                )
                if attempt < 2:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        raise last_exc
