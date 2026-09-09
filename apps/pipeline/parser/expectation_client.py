"""
ExpectationClient — the one model call in Layer 2.

Same conventions as CodingClientV2: AsyncOpenAI, responses.create with a
strict json_schema, two attempts, latency recorded. Deliberately a
separate client rather than another method on CodingClientV2, for the
same reason pass 2 is separate from pass 1: it asks a different question
of a different prompt, and a client that could answer both would
eventually be asked to.

It transcribes and never judges — see parser/expectation_prompts.py.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

import soa_shared.config as config
from parser.expectation_prompts import (
    EMPTY_EXTRACTION,
    build_extraction_prompt,
    build_extraction_schema,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


@dataclass
class ExtractionResult:
    record: dict
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    usage: dict = field(default_factory=dict)


def _unreadable(note: str) -> dict:
    """
    An extraction record for an answer we could not read.

    extraction_confident=False, which the comparator turns into
    `unscoreable` — never into `wrong`. A model call that failed is our
    failure, and recording it as an assistant error would inflate the
    error rate with our own outages.
    """
    return {**EMPTY_EXTRACTION, 'extraction_note': note}


class ExpectationClient:

    def __init__(self, model: str = "gpt-5.4-mini") -> None:
        if not config.OPEN_AI_API_KEY:
            raise RuntimeError("OPEN_AI_API_KEY is not set. Add it to /soa/.env.")
        self.model = model
        self._client = AsyncOpenAI(api_key=config.OPEN_AI_API_KEY)

    async def extract(self, answer_text: str, *, brand: str = None) -> ExtractionResult:
        """
        One answer -> one extraction record. Never raises.

        `brand` is the ONLY thing about the expectation this call is told,
        and only the name: brand_mentioned is unanswerable without knowing
        which brand is meant, while every other field is a transcription
        that needs no target. Passing the price would be handing the
        extractor the answer and asking it to find it.
        """
        if not answer_text or not answer_text.strip():
            return ExtractionResult(
                record=_unreadable('no answer text to read'), model=self.model,
            )

        instructions = build_extraction_prompt(brand)
        schema = build_extraction_schema()
        t0 = time.monotonic()
        last_error = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    input=[{
                        "role": "user",
                        "content": f"Answer to transcribe:\n{answer_text}",
                    }],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "expectation_extraction_schema",
                            "schema": schema,
                            "strict": True,
                        }
                    },
                )
                record = json.loads(response.output_text)
                usage = getattr(response, "usage", None)
                return ExtractionResult(
                    record=record,
                    model=self.model,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    usage={
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                    } if usage else {},
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[expectation] extraction attempt %d/%d failed: %s",
                    attempt, MAX_ATTEMPTS, exc,
                )

        return ExtractionResult(
            record=_unreadable(f"extraction call failed: {last_error}"),
            model=self.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=last_error,
        )
