"""Compliance status enum and precedence resolution.

Spec §4 (US 4.1) defines exactly four allowed statuses and their precedence:
    MATERIAL_CONTRADICTION > MISSING_EVIDENCE > SPECIALIST_REVIEW_REQUIRED > COMPLIANT_FOR_SUBMISSION
"""

from enum import StrEnum


class Status(StrEnum):
    COMPLIANT_FOR_SUBMISSION = "COMPLIANT_FOR_SUBMISSION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    MATERIAL_CONTRADICTION = "MATERIAL_CONTRADICTION"
    SPECIALIST_REVIEW_REQUIRED = "SPECIALIST_REVIEW_REQUIRED"


# Higher number = higher precedence (wins when multiple statuses are candidates)
_PRECEDENCE: dict[Status, int] = {
    Status.COMPLIANT_FOR_SUBMISSION: 0,
    Status.SPECIALIST_REVIEW_REQUIRED: 1,
    Status.MISSING_EVIDENCE: 2,
    Status.MATERIAL_CONTRADICTION: 3,
}


def resolve_status(candidates: list[Status]) -> Status:
    """Return the highest-precedence status from a list of candidates.

    If the list is empty, returns COMPLIANT_FOR_SUBMISSION (no issues found).

    Examples:
        >>> resolve_status([])
        <Status.COMPLIANT_FOR_SUBMISSION: 'COMPLIANT_FOR_SUBMISSION'>
        >>> resolve_status([Status.MISSING_EVIDENCE, Status.MATERIAL_CONTRADICTION])
        <Status.MATERIAL_CONTRADICTION: 'MATERIAL_CONTRADICTION'>
    """
    if not candidates:
        return Status.COMPLIANT_FOR_SUBMISSION
    return max(candidates, key=lambda s: _PRECEDENCE[s])
