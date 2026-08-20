"""Pydantic contracts for the deterministic domain and policy boundaries."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from traceguard.domain.enums import (
    CanonicalErrorCode,
    Confidence,
    EvidenceSource,
    FailureCategory,
    PolicyDecisionType,
    PolicyReason,
    RecoveryAction,
    WorkflowState,
)


class DomainModel(BaseModel):
    """Base configuration for immutable, closed domain contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtractedOrderCandidate(DomainModel):
    """Structurally valid extraction; business completeness is not implied."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_number: StrictStr | None = None
    product_code: StrictStr | None = None
    quantity: StrictInt | None = None
    delivery_instructions: StrictStr | None = None


class DomainOrder(DomainModel):
    """Order with all required business fields present and normalized."""

    customer_number: str = Field(min_length=1)
    product_code: str = Field(min_length=1)
    quantity: int
    delivery_instructions: str | None = None


class ValidatedOrder(DomainModel):
    """Domain-complete order that also satisfies deterministic business rules."""

    customer_number: str = Field(min_length=1)
    product_code: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    delivery_instructions: str | None = None


class EvidenceItem(DomainModel):
    event_id: str = Field(min_length=1, max_length=100)
    source: EvidenceSource
    observation: str = Field(min_length=1, max_length=240)


class InvestigationReport(DomainModel):
    report_id: UUID
    run_id: UUID
    failure_category: FailureCategory
    diagnosed_error_code: CanonicalErrorCode
    root_cause: str = Field(min_length=1, max_length=500)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=5)
    recommended_action: RecoveryAction
    rationale: str = Field(min_length=1, max_length=500)
    confidence: Confidence
    uncertainties: list[str] = Field(default_factory=list, max_length=3)
    runbook_references: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("uncertainties", "runbook_references")
    @classmethod
    def reject_blank_list_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list items must not be blank")
        return values


class RetryMetadata(DomainModel):
    attempt_count: int = Field(ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    prior_result_fingerprint: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("idempotency_key", "prior_result_fingerprint")
    @classmethod
    def reject_blank_optional_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be blank")
        return value


class PolicyInput(DomainModel):
    canonical_error_code: CanonicalErrorCode
    diagnosed_error_code: CanonicalErrorCode | None = None
    diagnosed_failure_category: FailureCategory | None = None
    recommended_action: RecoveryAction | None = None
    workflow_state: WorkflowState
    investigation_output_valid: bool
    retry: RetryMetadata


class PolicyConstraints(DomainModel):
    max_total_erp_attempts: int | None = Field(default=None, ge=1)
    backoff_seconds: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class PolicyOutput(DomainModel):
    decision: PolicyDecisionType
    allowed_action: RecoveryAction | None = None
    reason_codes: list[PolicyReason] = Field(min_length=1)
    constraints: PolicyConstraints = Field(default_factory=PolicyConstraints)
