"""Inspectable run, trace, artifact, and mock-ERP contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, JsonValue

from traceguard.domain.enums import (
    CanonicalErrorCode,
    EventOutcome,
    FailureCategory,
    InvestigationState,
    ProviderMode,
    RecoveryState,
    WorkflowState,
)
from traceguard.domain.models import DomainModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class PresetId(StrEnum):
    SUCCESS = "SUCCESS"
    MISSING_CUSTOMER = "MISSING_CUSTOMER"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    ERP_UNAVAILABLE = "ERP_UNAVAILABLE"


class MockErpBehavior(StrEnum):
    SUCCEED = "SUCCEED"
    FAIL_ONCE_503 = "FAIL_ONCE_503"


class EventSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class EventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    EXTRACTION_STARTED = "EXTRACTION_STARTED"
    EXTRACTION_COMPLETED = "EXTRACTION_COMPLETED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    STRUCTURAL_VALIDATION_COMPLETED = "STRUCTURAL_VALIDATION_COMPLETED"
    STRUCTURAL_VALIDATION_FAILED = "STRUCTURAL_VALIDATION_FAILED"
    DOMAIN_VALIDATION_COMPLETED = "DOMAIN_VALIDATION_COMPLETED"
    DOMAIN_VALIDATION_FAILED = "DOMAIN_VALIDATION_FAILED"
    BUSINESS_VALIDATION_COMPLETED = "BUSINESS_VALIDATION_COMPLETED"
    BUSINESS_VALIDATION_FAILED = "BUSINESS_VALIDATION_FAILED"
    OPTIONAL_FIELD_DEFAULTED = "OPTIONAL_FIELD_DEFAULTED"
    CACHE_LOOKUP_FAILED = "CACHE_LOOKUP_FAILED"
    CACHE_FALLBACK_SUCCEEDED = "CACHE_FALLBACK_SUCCEEDED"
    ERP_REQUEST_SUCCEEDED = "ERP_REQUEST_SUCCEEDED"
    ERP_REQUEST_FAILED = "ERP_REQUEST_FAILED"


class StageArtifactType(StrEnum):
    EXTRACTION = "EXTRACTION"
    STRUCTURAL_VALIDATION = "STRUCTURAL_VALIDATION"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    BUSINESS_VALIDATION = "BUSINESS_VALIDATION"
    ERP = "ERP"


class WorkflowRun(DomainModel):
    run_id: UUID = Field(default_factory=uuid4)
    order_request_text: str = Field(min_length=1, max_length=10_000)
    preset_id: PresetId | None = None
    mock_erp_behavior: MockErpBehavior
    extraction_provider_mode: ProviderMode | None = None
    workflow_state: WorkflowState = WorkflowState.CREATED
    investigation_state: InvestigationState = InvestigationState.NOT_REQUIRED
    recovery_state: RecoveryState = RecoveryState.NONE
    canonical_failure_code: CanonicalErrorCode | None = None
    canonical_failure_category: FailureCategory | None = None
    failure_stage: WorkflowState | None = None
    idempotency_key: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    erp_attempt_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TraceEvent(DomainModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)
    run_id: UUID
    workflow_stage: WorkflowState
    event_type: EventType
    severity: EventSeverity
    outcome: EventOutcome
    details: str = Field(min_length=1, max_length=500)


class StageArtifact(DomainModel):
    artifact_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)
    run_id: UUID
    artifact_type: StageArtifactType
    data: dict[str, JsonValue]


class ErpAttempt(DomainModel):
    attempt_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)
    run_id: UUID
    attempt_number: int = Field(ge=1)
    behavior: MockErpBehavior
    status_code: int = Field(ge=100, le=599)
    succeeded: bool
    response_summary: str = Field(min_length=1, max_length=240)


class ErpDiagnostic(DomainModel):
    event_type: EventType
    severity: EventSeverity
    outcome: EventOutcome
    details: str = Field(min_length=1, max_length=500)


class MockErpResult(DomainModel):
    attempt: ErpAttempt
    diagnostics: tuple[ErpDiagnostic, ...] = ()
