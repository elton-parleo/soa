"""
Validates a CodingResponse before writing to the database.
Catches logical inconsistencies that the JSON schema cannot enforce.
"""
from dataclasses import dataclass, field
from typing import List

from parser.coding_response import CodingResponse, MerchantCoding
from soa_shared.models.soa_models import SoaRun

VALID_DEAL_TYPES = {
    "discount_pct",
    "promo_name",
    "loyalty_points",
    "member_price",
    "free_shipping",
    "gift_with_purchase",
}


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    should_flag_review: bool


class CodingValidator:

    def validate(self, coding: CodingResponse, run: SoaRun) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        should_flag_review = False

        mentioned_merchants = {
            mid: mc for mid, mc in coding.merchants.items() if mc.mentioned
        }

        # 1. Position consistency — no two mentioned merchants share the same position
        positions = [mc.position for mc in mentioned_merchants.values() if mc.position is not None]
        if len(positions) != len(set(positions)):
            errors.append("Duplicate position values.")

        # 2. Null consistency — if mentioned=False, position/strength must be null, deal_cited must be False
        for mid, mc in coding.merchants.items():
            if not mc.mentioned:
                if mc.position is not None:
                    errors.append(f"{mid}: position must be null when mentioned=False.")
                if mc.strength is not None:
                    errors.append(f"{mid}: strength must be null when mentioned=False.")
                if mc.deal_cited:
                    errors.append(f"{mid}: deal_cited must be False when mentioned=False.")

        # 3. Primary uniqueness — Primary requires singularity (at most one per response)
        primaries = [mid for mid, mc in coding.merchants.items() if mc.strength == "Primary"]
        if len(primaries) > 1:
            warnings.append(
                f"Multiple Primary assignments ({', '.join(primaries)}) — Primary requires "
                "singularity. Only one entity can be Primary per response. Review whether "
                "these should be downgraded to Positive."
            )
            should_flag_review = True

        # 3b. Primary alongside other favorable entities — catches the most common coding
        #     error: strong language used for multiple entities, coder awards Primary to first.
        if len(primaries) == 1:
            positive_or_primary = [
                mid for mid, mc in coding.merchants.items()
                if mc.strength in ("Primary", "Positive")
            ]
            if len(positive_or_primary) > 1:
                warnings.append(
                    "Primary assigned alongside other positive entities — verify the agent "
                    "truly singled out this entity as the sole recommendation."
                )

        # 4. Hallucination check — Primary with no evidence
        for mid, mc in coding.merchants.items():
            if mc.strength == "Primary" and not mc.evidence:
                warnings.append(f"{mid}: strength=Primary but evidence is null or empty.")
                should_flag_review = True

        # 5. Confidence threshold
        for mid, mc in coding.merchants.items():
            if mc.confidence < 0.75:
                should_flag_review = True
                break

        # 6. Deal type vocabulary
        # Valid: discount_pct, promo_name, loyalty_points, member_price,
        #        free_shipping, gift_with_purchase.
        for mid, mc in coding.merchants.items():
            bad = set(mc.deal_types) - VALID_DEAL_TYPES
            if bad:
                errors.append(f"{mid}: invalid deal_types: {bad}.")

        # 7. Empty response guard
        if not run.raw_response and any(mc.mentioned for mc in coding.merchants.values()):
            errors.append("raw_response is empty but merchants are marked as mentioned.")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            should_flag_review=should_flag_review or coding.needs_review,
        )
