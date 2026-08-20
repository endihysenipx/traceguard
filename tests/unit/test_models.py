from uuid import uuid4

import pytest
from pydantic import ValidationError

from traceguard.domain.enums import (
    CanonicalErrorCode,
    Confidence,
    EvidenceRole,
    FailureCategory,
    RecoveryAction,
)
from traceguard.domain.models import (
    EvidenceItem,
    InvestigationReport,
    RetryMetadata,
)


def valid_report_values() -> dict[str, object]:
    return {
        "report_id": uuid4(),
        "run_id": uuid4(),
        "failure_category": FailureCategory.EXTERNAL_TRANSIENT_FAILURE,
        "diagnosed_error_code": CanonicalErrorCode.ERP_UNAVAILABLE,
        "root_cause": "The ERP returned HTTP 503.",
        "evidence": [
            EvidenceItem(
                event_id=uuid4(),
                role=EvidenceRole.TERMINAL_CAUSE,
                observation="The terminal ERP call returned 503.",
            )
        ],
        "recommended_action": RecoveryAction.RETRY_SAME_INPUT,
        "rationale": "The failure is transient and the retry is bounded.",
        "confidence": Confidence.HIGH,
        "uncertainties": [],
        "runbook_references": ["erp-unavailable"],
    }


def test_investigation_report_accepts_bounded_structured_evidence() -> None:
    report = InvestigationReport.model_validate(valid_report_values())

    assert report.diagnosed_error_code is CanonicalErrorCode.ERP_UNAVAILABLE
    assert len(report.evidence) == 1


def test_investigation_report_requires_evidence() -> None:
    values = valid_report_values()
    values["evidence"] = []

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(values)


def test_investigation_report_rejects_blank_reference() -> None:
    values = valid_report_values()
    values["runbook_references"] = ["   "]

    with pytest.raises(ValidationError):
        InvestigationReport.model_validate(values)


def test_retry_metadata_rejects_negative_attempt_count() -> None:
    with pytest.raises(ValidationError):
        RetryMetadata(attempt_count=-1, idempotency_key="run-1")


def test_retry_metadata_rejects_blank_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        RetryMetadata(attempt_count=1, idempotency_key="   ")


def test_retry_metadata_allows_absent_idempotency_for_fail_closed_policy() -> None:
    metadata = RetryMetadata(attempt_count=1)

    assert metadata.idempotency_key is None
