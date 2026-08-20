from copy import deepcopy
from uuid import uuid4

import pytest

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    DiagnosticToolName,
    InvestigationState,
    PolicyDecisionType,
    PolicyReason,
    ProviderMode,
    RecoveryAction,
    RecoveryExecutionStatus,
    RecoveryState,
    WorkflowState,
)
from traceguard.extraction import ScriptedExtractionProvider
from traceguard.investigation import (
    Investigator,
    LocalRunbook,
    ScriptedInvestigatorModel,
    TOOL_NAMES,
)
from traceguard.investigation.models import InvestigatorTurn, ToolCallRequest
from traceguard.recovery import RecoveryCoordinator, RecoveryPreconditionError
from traceguard.workflow.erp import MockErp
from traceguard.workflow.fixtures import SCENARIO_FIXTURES
from traceguard.workflow.models import (
    MockErpBehavior,
    MockErpResult,
    PresetId,
    StageArtifact,
    StageArtifactType,
)
from traceguard.workflow.orchestrator import WorkflowOrchestrator
from traceguard.workflow.repository import InMemoryTraceRepository

from tests.investigation.support import SequenceInvestigatorModel, report_for_event


def _failed_fixture(preset_id: PresetId):
    fixture = SCENARIO_FIXTURES[preset_id]
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)
    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text=fixture.order_request_text,
        preset_id=fixture.preset_id,
        mock_erp_behavior=fixture.mock_erp_behavior,
        provider=ScriptedExtractionProvider(),
    )
    return run, repository, erp


def _scripted_investigation(run_id, repository):
    return Investigator(repository, LocalRunbook()).investigate(
        run_id, ScriptedInvestigatorModel()
    )


def _custom_investigation(
    run_id,
    repository,
    *,
    diagnosed_code: CanonicalErrorCode,
    action: RecoveryAction,
):
    terminal = next(
        event
        for event in reversed(repository.list_events(run_id))
        if event.outcome.value == "TERMINAL"
    )
    report = report_for_event(run_id, terminal, code=diagnosed_code).model_copy(
        update={
            "recommended_action": action,
            "failure_category": CANONICAL_FAILURE_CATEGORY[diagnosed_code],
        }
    )
    model = SequenceInvestigatorModel(
        [
            InvestigatorTurn(
                tool_calls=(
                    ToolCallRequest(
                        provider_call_id="events",
                        name="get_run_events",
                        arguments={"run_id": run_id, "stage": None, "limit": 50},
                    ),
                )
            ),
            InvestigatorTurn(report=report),
        ]
    )
    return Investigator(repository, LocalRunbook()).investigate(run_id, model)


class FixedExtractionProvider:
    mode = ProviderMode.SCRIPTED

    def __init__(self, output: dict[str, object]) -> None:
        self.output = output

    def extract(self, order_request_text: str) -> object:
        return deepcopy(self.output)


class CountingErp:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, run_id, order):
        self.calls += 1
        raise AssertionError("ERP must not be called")


class FailingRetryErp:
    def __init__(self, repository: InMemoryTraceRepository) -> None:
        self.repository = repository
        self.orders = []

    def submit(self, run_id, order):
        self.orders.append(order)
        run = self.repository.get_run(run_id)
        attempt = self.repository.record_erp_attempt(
            run_id,
            behavior=run.mock_erp_behavior,
            status_code=503,
            succeeded=False,
            response_summary="Controlled recovery ERP attempt failed.",
        )
        return MockErpResult(attempt=attempt)


def test_correct_erp_diagnosis_allows_bounded_retry_and_duplicate_is_idempotent():
    run, repository, erp = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    report = _scripted_investigation(run.run_id, repository)
    original_events = repository.list_events(run.run_id)
    original_failure = (
        run.canonical_failure_code,
        run.canonical_failure_category,
        run.failure_stage,
    )
    slept = []
    coordinator = RecoveryCoordinator(repository, erp, sleeper=slept.append)

    result = coordinator.recover(run.run_id)

    assert result.decision.decision is PolicyDecisionType.ALLOW
    assert result.decision.allowed_action is RecoveryAction.RETRY_SAME_INPUT
    assert result.decision.reason_codes == (PolicyReason.ELIGIBLE_TRANSIENT_RETRY,)
    assert result.decision.constraints.max_total_erp_attempts == 2
    assert result.decision.constraints.backoff_seconds == 1
    assert result.decision.constraints.idempotency_key == run.idempotency_key
    assert slept == [1.0]
    assert result.execution.status is RecoveryExecutionStatus.SUCCEEDED
    assert result.execution.erp_attempt_number == 2

    recovered = repository.get_run(run.run_id)
    assert recovered.recovery_state is RecoveryState.RECOVERED
    assert recovered.workflow_state is WorkflowState.FAILED
    assert recovered.investigation_state is InvestigationState.COMPLETED
    assert recovered.erp_attempt_count == 2
    assert (
        recovered.canonical_failure_code,
        recovered.canonical_failure_category,
        recovered.failure_stage,
    ) == original_failure
    assert repository.list_events(run.run_id) == original_events
    assert repository.get_investigation_report(run.run_id) == report

    replay = coordinator.recover(run.run_id)
    assert replay.idempotent_replay is True
    assert replay.execution.execution_id == result.execution.execution_id
    assert repository.get_run(run.run_id).erp_attempt_count == 2
    assert slept == [1.0]
    execution_history = repository.list_recovery_executions(run.run_id)
    assert [item.status for item in execution_history] == [
        RecoveryExecutionStatus.STARTED,
        RecoveryExecutionStatus.SUCCEEDED,
    ]


def test_evidence_valid_but_conflicting_diagnosis_is_blocked_without_erp():
    run, repository, _ = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    report = _custom_investigation(
        run.run_id,
        repository,
        diagnosed_code=CanonicalErrorCode.ERP_REJECTED,
        action=RecoveryAction.RETRY_SAME_INPUT,
    )
    assert repository.get_investigation_report(run.run_id) == report
    erp = CountingErp()

    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )

    assert result.decision.decision is PolicyDecisionType.BLOCK
    assert PolicyReason.DIAGNOSIS_CONFLICT in result.decision.reason_codes
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.BLOCK
    assert repository.get_run(run.run_id).erp_attempt_count == 1
    assert erp.calls == 0
    assert repository.list_recovery_executions(run.run_id) == ()


def test_conflicting_erp_recommendation_blocks_without_execution():
    run, repository, _ = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    _custom_investigation(
        run.run_id,
        repository,
        diagnosed_code=CanonicalErrorCode.ERP_UNAVAILABLE,
        action=RecoveryAction.REQUEST_HUMAN_REVIEW,
    )
    erp = CountingErp()
    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )
    assert result.decision.decision is PolicyDecisionType.BLOCK
    assert result.decision.reason_codes == (PolicyReason.ACTION_CONFLICT,)
    assert erp.calls == 0


def test_missing_required_input_retry_recommendation_is_blocked():
    run, repository, _ = _failed_fixture(PresetId.MISSING_CUSTOMER)
    _custom_investigation(
        run.run_id,
        repository,
        diagnosed_code=CanonicalErrorCode.CUSTOMER_NUMBER_MISSING,
        action=RecoveryAction.RETRY_SAME_INPUT,
    )
    erp = CountingErp()
    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )
    assert result.decision.decision is PolicyDecisionType.BLOCK
    assert result.decision.reason_codes == (PolicyReason.ACTION_CONFLICT,)
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.BLOCK
    assert erp.calls == 0


@pytest.mark.parametrize(
    ("candidate", "code"),
    [
        ({"customer_number": None, "product_code": "P-1", "quantity": 1,
          "delivery_instructions": None}, CanonicalErrorCode.CUSTOMER_NUMBER_MISSING),
        ({"customer_number": "C-1", "product_code": None, "quantity": 1,
          "delivery_instructions": None}, CanonicalErrorCode.PRODUCT_CODE_MISSING),
        ({"customer_number": "C-1", "product_code": "P-1", "quantity": None,
          "delivery_instructions": None}, CanonicalErrorCode.QUANTITY_MISSING),
    ],
)
def test_all_missing_required_inputs_require_review_without_execution(candidate, code):
    repository = InMemoryTraceRepository()
    run = WorkflowOrchestrator(repository, MockErp(repository)).execute(
        order_request_text="Editable request with a required field omitted.",
        preset_id=None,
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=FixedExtractionProvider(candidate),
    )
    assert run.canonical_failure_code is code
    _custom_investigation(
        run.run_id,
        repository,
        diagnosed_code=code,
        action=RecoveryAction.REQUEST_INPUT_CORRECTION,
    )
    erp = CountingErp()
    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )
    assert result.decision.decision is PolicyDecisionType.REQUIRE_REVIEW
    assert result.decision.allowed_action is None
    assert result.decision.reason_codes == (PolicyReason.HUMAN_INPUT_REQUIRED,)
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.REQUIRE_REVIEW
    assert erp.calls == 0
    assert repository.list_erp_attempts(run.run_id) == ()


def test_invalid_quantity_blocks_without_correction_or_retry():
    run, repository, _ = _failed_fixture(PresetId.INVALID_QUANTITY)
    _scripted_investigation(run.run_id, repository)
    erp = CountingErp()
    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )
    assert result.decision.decision is PolicyDecisionType.BLOCK
    assert result.decision.reason_codes == (
        PolicyReason.NON_RETRYABLE_BUSINESS_RULE,
    )
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.BLOCK
    assert repository.get_run(run.run_id).erp_attempt_count == 0
    assert erp.calls == 0


def test_stale_attempt_limit_blocks_authorized_retry_without_side_effect():
    run, repository, _ = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    _scripted_investigation(run.run_id, repository)
    erp = CountingErp()
    coordinator = RecoveryCoordinator(repository, erp, sleeper=lambda _: None)
    decision = coordinator.evaluate(run.run_id)
    assert decision.decision is PolicyDecisionType.ALLOW
    repository.record_erp_attempt(
        run.run_id,
        behavior=MockErpBehavior.FAIL_ONCE_503,
        status_code=503,
        succeeded=False,
        response_summary="Concurrent second attempt already consumed the limit.",
    )

    result = coordinator.recover(run.run_id)

    assert result.execution.status is RecoveryExecutionStatus.BLOCKED
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.BLOCK
    assert repository.get_run(run.run_id).erp_attempt_count == 2
    assert erp.calls == 0


def test_malformed_latest_validated_order_artifact_fails_closed():
    run, repository, _ = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    _scripted_investigation(run.run_id, repository)
    repository.append_stage_artifact(
        StageArtifact(
            run_id=run.run_id,
            artifact_type=StageArtifactType.BUSINESS_VALIDATION,
            data={"status": "passed", "order": {"quantity": "not-an-integer"}},
        )
    )
    erp = CountingErp()

    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )

    assert result.decision.decision is PolicyDecisionType.ALLOW
    assert result.execution.status is RecoveryExecutionStatus.BLOCKED
    assert "artifact" in result.execution.result_summary.lower()
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.BLOCK
    assert repository.get_run(run.run_id).erp_attempt_count == 1
    assert erp.calls == 0


def test_failed_authorized_retry_exhausts_without_replacing_original_failure():
    run, repository, _ = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    _scripted_investigation(run.run_id, repository)
    original_error = run.canonical_failure_code
    erp = FailingRetryErp(repository)

    result = RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(
        run.run_id
    )

    final = repository.get_run(run.run_id)
    assert result.execution.status is RecoveryExecutionStatus.FAILED
    assert result.execution.erp_attempt_number == 2
    assert final.recovery_state is RecoveryState.RETRY_EXHAUSTED
    assert final.erp_attempt_count == 2
    assert final.workflow_state is WorkflowState.FAILED
    assert final.canonical_failure_code is original_error
    assert len(erp.orders) == 1


def test_recovery_requires_completed_stored_investigation():
    run, repository, erp = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    with pytest.raises(RecoveryPreconditionError, match="completed"):
        RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(run.run_id)
    assert repository.get_run(run.run_id).recovery_state is RecoveryState.NONE
    assert repository.get_run(run.run_id).erp_attempt_count == 1


def test_investigator_registry_remains_exactly_four_read_only_tools():
    assert TOOL_NAMES == tuple(tool.value for tool in DiagnosticToolName)
    assert set(TOOL_NAMES) == {
        "get_run_overview",
        "get_run_events",
        "get_stage_artifact",
        "search_runbook",
    }
    assert not any("retry" in name or "recovery" in name for name in TOOL_NAMES)


def test_recovery_history_reads_are_ordered_defensive_copies():
    run, repository, erp = _failed_fixture(PresetId.ERP_UNAVAILABLE)
    _scripted_investigation(run.run_id, repository)
    RecoveryCoordinator(repository, erp, sleeper=lambda _: None).recover(run.run_id)

    first_decisions = repository.list_recovery_decisions(run.run_id)
    second_decisions = repository.list_recovery_decisions(run.run_id)
    first_executions = repository.list_recovery_executions(run.run_id)
    second_executions = repository.list_recovery_executions(run.run_id)

    assert isinstance(first_decisions, tuple)
    assert isinstance(first_executions, tuple)
    assert first_decisions == second_decisions
    assert first_decisions[0] is not second_decisions[0]
    assert first_executions == second_executions
    assert first_executions[0] is not second_executions[0]
