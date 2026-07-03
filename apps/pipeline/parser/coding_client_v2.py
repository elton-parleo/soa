"""
CodingClientV2 — pass-2 extraction call (merchant attribution + citations
only). Deliberately separate from parser/coding_client.py (pass 1, one
call per soa_runs row that also derives mentioned/position/strength/
deal_cited) — pass 2 never asks for those fields at all, so there is
nothing for them to drift from pass 1's values. See
parser/prompts_v2.py and parser/coding_response_v2.py.
"""
import asyncio
import json
import logging
import time
from typing import List

from openai import AsyncOpenAI

import soa_shared.config as config
from soa_shared.models.soa_models import SoaRun
from parser.coding_response_v2 import CitationCoding, Pass2CodingResult, PriceObservationCoding
from parser.prompts_v2 import build_pass2_schema, build_pass2_system_prompt

logger = logging.getLogger(__name__)

_RETRY_DELAY_SECONDS = 5


class CodingClientV2:

    def __init__(self) -> None:
        if not config.OPEN_AI_API_KEY:
            raise RuntimeError("OPEN_AI_API_KEY is not set. Add it to /soa/.env.")
        self.model = "gpt-5.4-mini"
        self._client = AsyncOpenAI(api_key=config.OPEN_AI_API_KEY)

    async def code_observations(
        self,
        run: SoaRun,
        mentioned_entities: List[dict],
    ) -> Pass2CodingResult:
        """
        mentioned_entities: [{"comparison_code": str, "name": str}, ...] —
        entities pass 1 already confirmed mentioned in this run.
        """
        system_prompt = build_pass2_system_prompt(mentioned_entities)
        schema = build_pass2_schema()

        user_message = f"Agent response to extract from:\n{run.raw_response}"

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
                            "name": "pass2_extraction_schema",
                            "schema": schema,
                            "strict": True,
                        }
                    },
                )
                latency_ms = int((time.monotonic() - t0) * 1000)

                result = json.loads(response.output_text)
                usage = response.usage

                price_observations = [
                    PriceObservationCoding(
                        comparison_code=obs["comparison_code"],
                        stated_price=obs.get("stated_price"),
                        claimed_net_price=obs.get("claimed_net_price"),
                        claimed_discount_value=obs.get("claimed_discount_value"),
                        claimed_discount_pct=obs.get("claimed_discount_pct"),
                        claimed_terms=obs.get("claimed_terms") or [],
                        member_price_claimed=obs.get("member_price_claimed"),
                        subscription_offer_claimed=obs.get("subscription_offer_claimed"),
                        merchant_name=obs.get("merchant_name"),
                        evidence=obs.get("evidence"),
                    )
                    for obs in (result.get("price_observations") or [])
                ]

                # Anti-hallucination guard: only keep citations whose url is
                # verbatim present in the response the coder was given.
                citations: List[CitationCoding] = []
                for c in (result.get("citations") or []):
                    url = c.get("url")
                    if not url or url not in run.raw_response:
                        continue
                    citations.append(CitationCoding(
                        url=url, domain=c.get("domain") or "", context=c.get("context"),
                    ))

                logger.info(
                    "[coding_v2] run_id=%d model=%s latency=%dms attempt=%d observations=%d citations=%d",
                    run.id, self.model, latency_ms, attempt, len(price_observations), len(citations),
                )

                return Pass2CodingResult(
                    run_id=run.id,
                    price_observations=price_observations,
                    citations=citations,
                    coding_latency_ms=latency_ms,
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                )

            except Exception as exc:
                last_exc = exc
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.error(
                    "[coding_v2] run_id=%d attempt=%d/%d FAILED after %dms: %s",
                    run.id, attempt, 2, latency_ms, exc,
                )
                if attempt < 2:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

        raise last_exc
