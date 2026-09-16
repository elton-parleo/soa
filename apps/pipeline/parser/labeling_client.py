"""
The labelling call, and the merge of its answer back onto the record.

Same conventions as ExpectationClient — AsyncOpenAI, responses.create
with a strict json_schema, two attempts, never raises. A separate client
rather than a second method on the extractor, for the reason pass 2 is
separate from pass 1: it asks a different question with a different
prompt, and a client that could answer both would eventually be asked to.

It sees the answer and the spans. It does not see the expectation, the
published record, or any verdict — labelling is not scoring, and a
labeller that knew what a right answer looked like would start labelling
towards it.

A failed call is recorded, not guessed around. Every unlabelled sentence
keeps `kind` and `modality` absent, asserted_claims returns nothing for
it, and the row says so — because the alternative, treating an
unlabelled sentence as an asserted claim, is exactly the failure three
hand-checks found.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

import soa_shared.config as config
from parser.label_prompts import (
    build_labeling_prompt,
    build_labeling_schema,
    spans_to_label,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


@dataclass
class LabelingResult:
    labels: dict
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    usage: dict = field(default_factory=dict)


EMPTY_LABELS = {'spans': [], 'other_brands': [], 'retailers': []}


class LabelingClient:

    def __init__(self, model: str = "gpt-5.4-mini") -> None:
        if not config.OPEN_AI_API_KEY:
            raise RuntimeError("OPEN_AI_API_KEY is not set. Add it to /soa/.env.")
        self.model = model
        self._client = AsyncOpenAI(api_key=config.OPEN_AI_API_KEY)

    async def label(self, record: dict, *, answer_text: str) -> LabelingResult:
        spans = spans_to_label(record, answer_text)
        if not any(spans.values()):
            # Nothing to label is not a failure and is not a call.
            return LabelingResult(labels=dict(EMPTY_LABELS), model=self.model)

        t0 = time.monotonic()
        last_error = None
        payload = json.dumps({
            'answer': answer_text,
            'spans': [{'id': sp['id'], 'text': sp['text']} for sp in spans['spans']],
            'other_brands': spans['other_brands'],
            'retailers': spans['retailers'],
        }, ensure_ascii=False)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._client.responses.create(
                    model=self.model,
                    instructions=build_labeling_prompt(),
                    input=[{"role": "user", "content": payload}],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "span_labeling_schema",
                            "schema": build_labeling_schema(),
                            "strict": True,
                        }
                    },
                )
                usage = getattr(response, "usage", None)
                return LabelingResult(
                    labels=json.loads(response.output_text),
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
                    "[labeling] attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, exc,
                )

        return LabelingResult(
            labels=dict(EMPTY_LABELS),
            model=self.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=last_error,
        )
