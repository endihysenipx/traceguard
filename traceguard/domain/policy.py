"""Fail-closed deterministic recovery authorization."""

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    PolicyDecisionType,
    PolicyReason,
    RecoveryAction,
    WorkflowState,
)
from traceguard.domain.models import PolicyConstraints, PolicyInput, PolicyOutput


MAX_TOTAL_ERP_ATTEMPTS = 2
ERP_RETRY_BACKOFF_SECONDS = 1


def evaluate_recovery_policy(policy_input: PolicyInput) -> PolicyOutput:
    """Return a deterministic authorization decision for an agent recommendation."""

    if policy_input.workflow_state is not WorkflowState.FAILED:
        return _block(PolicyReason.WORKFLOW_NOT_FAILED)

    if not policy_input.investigation_output_valid:
        return _block(PolicyReason.INVALID_INVESTIGATION)

    if (
        policy_input.diagnosed_error_code is None
        or policy_input.diagnosed_failure_category is None
        or policy_input.recommended_action is None
    ):
        return _block(PolicyReason.INVALID_INVESTIGATION)

    expected_category = CANONICAL_FAILURE_CATEGORY[policy_input.canonical_error_code]
    if (
        policy_input.diagnosed_error_code is not policy_input.canonical_error_code
        or policy_input.diagnosed_failure_category is not expected_category
    ):
        return _block(PolicyReason.DIAGNOSIS_CONFLICT)

    if policy_input.canonical_error_code is CanonicalErrorCode.CUSTOMER_NUMBER_MISSING:
        if policy_input.recommended_action in {
            RecoveryAction.REQUEST_INPUT_CORRECTION,
            RecoveryAction.REQUEST_HUMAN_REVIEW,
        }:
            return PolicyOutput(
                decision=PolicyDecisionType.REQUIRE_REVIEW,
                allowed_action=None,
                reason_codes=[PolicyReason.HUMAN_INPUT_REQUIRED],
            )
        return _block(PolicyReason.ACTION_CONFLICT)

    if policy_input.canonical_error_code is CanonicalErrorCode.QUANTITY_NON_POSITIVE:
        return _block(PolicyReason.NON_RETRYABLE_BUSINESS_RULE)

    if policy_input.canonical_error_code is CanonicalErrorCode.ERP_UNAVAILABLE:
        return _evaluate_erp_retry(policy_input)

    return _block(PolicyReason.UNKNOWN_ERROR)


def _evaluate_erp_retry(policy_input: PolicyInput) -> PolicyOutput:
    if policy_input.recommended_action is not RecoveryAction.RETRY_SAME_INPUT:
        return _block(PolicyReason.ACTION_CONFLICT)

    idempotency_key = policy_input.retry.idempotency_key
    if idempotency_key is None:
        return _block(PolicyReason.IDEMPOTENCY_KEY_MISSING)

    if policy_input.retry.attempt_count >= MAX_TOTAL_ERP_ATTEMPTS:
        return _block(PolicyReason.RETRY_LIMIT_REACHED)

    return PolicyOutput(
        decision=PolicyDecisionType.ALLOW,
        allowed_action=RecoveryAction.RETRY_SAME_INPUT,
        reason_codes=[PolicyReason.ELIGIBLE_TRANSIENT_RETRY],
        constraints=PolicyConstraints(
            max_total_erp_attempts=MAX_TOTAL_ERP_ATTEMPTS,
            backoff_seconds=ERP_RETRY_BACKOFF_SECONDS,
            idempotency_key=idempotency_key,
        ),
    )


def _block(reason: PolicyReason) -> PolicyOutput:
    return PolicyOutput(
        decision=PolicyDecisionType.BLOCK,
        allowed_action=None,
        reason_codes=[reason],
    )
