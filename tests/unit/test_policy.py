import pytest

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    FailureCategory,
    PolicyDecisionType,
    PolicyReason,
    RecoveryAction,
    WorkflowState,
)
from traceguard.domain.models import PolicyInput, RetryMetadata
from traceguard.domain.policy import evaluate_recovery_policy


def policy_input(
    code: CanonicalErrorCode,
    action: RecoveryAction,
    **overrides: object,
) -> PolicyInput:
    values: dict[str, object] = {
        "canonical_error_code": code,
        "diagnosed_error_code": code,
        "diagnosed_failure_category": CANONICAL_FAILURE_CATEGORY[code],
        "recommended_action": action,
        "workflow_state": WorkflowState.FAILED,
        "investigation_output_valid": True,
        "retry": RetryMetadata(attempt_count=1, idempotency_key="run-1"),
    }
    values.update(overrides)
    return PolicyInput.model_validate(values)


def assert_blocked(result: object, reason: PolicyReason) -> None:
    assert result.decision is PolicyDecisionType.BLOCK
    assert result.allowed_action is None
    assert result.reason_codes == [reason]
    assert result.constraints.max_total_erp_attempts is None


def test_policy_blocks_when_workflow_is_not_failed() -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            workflow_state=WorkflowState.SUCCEEDED,
        )
    )

    assert_blocked(result, PolicyReason.WORKFLOW_NOT_FAILED)


def test_policy_blocks_invalid_investigation_output() -> None:
    result = evaluate_recovery_policy(
        PolicyInput(
            canonical_error_code=CanonicalErrorCode.ERP_UNAVAILABLE,
            workflow_state=WorkflowState.FAILED,
            investigation_output_valid=False,
            retry=RetryMetadata(attempt_count=1, idempotency_key="run-1"),
        )
    )

    assert_blocked(result, PolicyReason.INVALID_INVESTIGATION)


def test_policy_blocks_report_marked_valid_but_missing_required_diagnosis() -> None:
    result = evaluate_recovery_policy(
        PolicyInput(
            canonical_error_code=CanonicalErrorCode.ERP_UNAVAILABLE,
            workflow_state=WorkflowState.FAILED,
            investigation_output_valid=True,
            retry=RetryMetadata(attempt_count=1, idempotency_key="run-1"),
        )
    )

    assert_blocked(result, PolicyReason.INVALID_INVESTIGATION)


def test_policy_blocks_conflicting_diagnosed_error_code() -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            diagnosed_error_code=CanonicalErrorCode.QUANTITY_NON_POSITIVE,
        )
    )

    assert_blocked(result, PolicyReason.DIAGNOSIS_CONFLICT)


def test_policy_blocks_conflicting_diagnosed_category() -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            diagnosed_failure_category=FailureCategory.BUSINESS_RULE_VIOLATION,
        )
    )

    assert_blocked(result, PolicyReason.DIAGNOSIS_CONFLICT)


@pytest.mark.parametrize(
    "action",
    [
        RecoveryAction.REQUEST_INPUT_CORRECTION,
        RecoveryAction.REQUEST_HUMAN_REVIEW,
    ],
)
@pytest.mark.parametrize(
    "code",
    [
        CanonicalErrorCode.CUSTOMER_NUMBER_MISSING,
        CanonicalErrorCode.PRODUCT_CODE_MISSING,
        CanonicalErrorCode.QUANTITY_MISSING,
    ],
)
def test_missing_required_input_requires_review(
    code: CanonicalErrorCode,
    action: RecoveryAction,
) -> None:
    result = evaluate_recovery_policy(
        policy_input(code, action)
    )

    assert result.decision is PolicyDecisionType.REQUIRE_REVIEW
    assert result.allowed_action is None
    assert result.reason_codes == [PolicyReason.HUMAN_INPUT_REQUIRED]


@pytest.mark.parametrize(
    "code",
    [
        CanonicalErrorCode.CUSTOMER_NUMBER_MISSING,
        CanonicalErrorCode.PRODUCT_CODE_MISSING,
        CanonicalErrorCode.QUANTITY_MISSING,
    ],
)
@pytest.mark.parametrize(
    "action",
    [RecoveryAction.NO_ACTION, RecoveryAction.RETRY_SAME_INPUT],
)
def test_missing_required_input_blocks_conflicting_action(
    code: CanonicalErrorCode,
    action: RecoveryAction,
) -> None:
    result = evaluate_recovery_policy(
        policy_input(code, action)
    )

    assert_blocked(result, PolicyReason.ACTION_CONFLICT)


@pytest.mark.parametrize("action", list(RecoveryAction))
def test_non_positive_quantity_is_always_blocked(action: RecoveryAction) -> None:
    result = evaluate_recovery_policy(
        policy_input(CanonicalErrorCode.QUANTITY_NON_POSITIVE, action)
    )

    assert_blocked(result, PolicyReason.NON_RETRYABLE_BUSINESS_RULE)


def test_erp_unavailable_blocks_non_retry_action() -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.REQUEST_HUMAN_REVIEW,
        )
    )

    assert_blocked(result, PolicyReason.ACTION_CONFLICT)


def test_erp_unavailable_requires_idempotency_key() -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            retry=RetryMetadata(attempt_count=1, idempotency_key=None),
        )
    )

    assert_blocked(result, PolicyReason.IDEMPOTENCY_KEY_MISSING)


@pytest.mark.parametrize("attempt_count", [2, 3])
def test_erp_unavailable_blocks_exhausted_retry_limit(attempt_count: int) -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            retry=RetryMetadata(
                attempt_count=attempt_count,
                idempotency_key="run-1",
            ),
        )
    )

    assert_blocked(result, PolicyReason.RETRY_LIMIT_REACHED)


@pytest.mark.parametrize("attempt_count", [0, 1])
def test_erp_unavailable_allows_bounded_idempotent_retry(
    attempt_count: int,
) -> None:
    result = evaluate_recovery_policy(
        policy_input(
            CanonicalErrorCode.ERP_UNAVAILABLE,
            RecoveryAction.RETRY_SAME_INPUT,
            retry=RetryMetadata(
                attempt_count=attempt_count,
                idempotency_key="run-1",
            ),
        )
    )

    assert result.decision is PolicyDecisionType.ALLOW
    assert result.allowed_action is RecoveryAction.RETRY_SAME_INPUT
    assert result.reason_codes == [PolicyReason.ELIGIBLE_TRANSIENT_RETRY]
    assert result.constraints.max_total_erp_attempts == 2
    assert result.constraints.backoff_seconds == 1
    assert result.constraints.idempotency_key == "run-1"


@pytest.mark.parametrize(
    "code",
    [
        CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
        CanonicalErrorCode.ORDER_STRUCTURE_INVALID,
        CanonicalErrorCode.ERP_REJECTED,
        CanonicalErrorCode.INVESTIGATION_INVALID_OUTPUT,
        CanonicalErrorCode.ERP_RETRY_EXHAUSTED,
    ],
)
def test_unhandled_canonical_errors_fail_closed(code: CanonicalErrorCode) -> None:
    result = evaluate_recovery_policy(policy_input(code, RecoveryAction.NO_ACTION))

    assert_blocked(result, PolicyReason.UNKNOWN_ERROR)
