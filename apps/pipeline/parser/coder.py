"""
Coding LLM — converts raw platform text into structured SoaCodedMention rows.

This is the only place in /soa that calls an LLM with structured output
(JSON schema enforcement). The runners return raw text; the coder makes
a separate LLM call to turn that text into coded data.
"""
import json
import os
from typing import Any

from openai import OpenAI

from parser.prompts import CODER_SYSTEM_PROMPT, CODER_USER_TEMPLATE
from parser.validator import validate_coded_mention

_CODING_SCHEMA = {
    "type": "object",
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "merchant_name": {"type": "string"},
                    "mentioned": {"type": "boolean"},
                    "position": {"type": ["integer", "null"]},
                    "strength": {
                        "type": ["string", "null"],
                        "enum": ["Primary", "Positive", "Neutral", "Negative", None],
                    },
                    "deal_cited": {"type": "boolean"},
                    "deal_types": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                    "evidence": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
                "required": [
                    "merchant_name", "mentioned", "position", "strength",
                    "deal_cited", "deal_types", "evidence", "confidence",
                ],
            },
        }
    },
    "required": ["mentions"],
}


class Coder:
    def __init__(
        self,
        model: str = "gpt-5.5",
        api_key: str | None = None,
    ):
        self._client = OpenAI(api_key=api_key or os.environ["OPEN_AI_API_KEY"])
        self.model = model

    def _build_messages(
        self, query_text: str, raw_response: str, merchant_names: list[str]
    ) -> list[dict]:
        user_content = CODER_USER_TEMPLATE.format(
            query_text=query_text,
            raw_response=raw_response,
            merchant_names=", ".join(merchant_names),
        )
        return [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def code(
        self,
        query_text: str,
        raw_response: str,
        merchant_names: list[str],
    ) -> list[dict[str, Any]]:
        """
        Returns a list of validated coded mention dicts, one per merchant.
        Raises ValidationError if the LLM output violates any constraint.
        """
        messages = self._build_messages(query_text, raw_response, merchant_names)

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "coded_mentions",
                    "schema": _CODING_SCHEMA,
                    "strict": True,
                },
            },
        )

        data = json.loads(response.choices[0].message.content)
        mentions = data["mentions"]

        for mention in mentions:
            validate_coded_mention(mention)

        return mentions
