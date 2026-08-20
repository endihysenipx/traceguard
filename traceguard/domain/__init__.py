"""Deterministic domain contracts and rules for TraceGuard."""

from traceguard.domain.enums import (
    CanonicalErrorCode,
    Confidence,
    EventOutcome,
    EvidenceSource,
    FailureCategory,
    InvestigationState,
    PolicyDecisionType,
    PolicyReason,
    RecoveryAction,
    RecoveryState,
    WorkflowState,
)
from traceguard.domain.errors import IllegalStateTransition, WorkflowValidationError
from traceguard.domain.models import (
    DomainOrder,
    EvidenceItem,
    ExtractedOrderCandidate,
    InvestigationReport,
    PolicyConstraints,
    PolicyInput,
    PolicyOutput,
    RetryMetadata,
    ValidatedOrder,
)
from traceguard.domain.policy import evaluate_recovery_policy
from traceguard.domain.transitions import (
    ensure_investigation_transition,
    ensure_recovery_transition,
    ensure_workflow_transition,
)
from traceguard.domain.validation import (
    validate_business_rules,
    validate_domain_requirements,
    validate_extracted_structure,
)

__all__ = [
    "CanonicalErrorCode",
    "Confidence",
    "DomainOrder",
    "EventOutcome",
    "EvidenceItem",
    "EvidenceSource",
    "ExtractedOrderCandidate",
    "FailureCategory",
    "IllegalStateTransition",
    "InvestigationReport",
    "InvestigationState",
    "PolicyConstraints",
    "PolicyDecisionType",
    "PolicyInput",
    "PolicyOutput",
    "PolicyReason",
    "RecoveryAction",
    "RecoveryState",
    "RetryMetadata",
    "ValidatedOrder",
    "WorkflowState",
    "WorkflowValidationError",
    "ensure_investigation_transition",
    "ensure_recovery_transition",
    "ensure_workflow_transition",
    "evaluate_recovery_policy",
    "validate_business_rules",
    "validate_domain_requirements",
    "validate_extracted_structure",
]

