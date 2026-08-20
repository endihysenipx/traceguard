from uuid import uuid4

import pytest

from traceguard.domain.enums import (
    CanonicalErrorCode,
    InvestigationFailureReason,
    InvestigationState,
)
from traceguard.investigation import InvestigationFailedError, Investigator, LocalRunbook
from traceguard.investigation.models import (
    InvestigatorModelTimeoutError,
    InvestigatorTurn,
    ToolCallRequest,
)
from traceguard.workflow.models import PresetId

from tests.investigation.support import SequenceInvestigatorModel, execute_fixture


def call(name: str, arguments: object, index: int = 1) -> ToolCallRequest:
    return ToolCallRequest(
        provider_call_id=f"call-{index}", name=name, arguments=arguments
    )


@pytest.mark.parametrize(
    ("request_factory", "reason"),
    [
        (
            lambda run_id: call("retry_erp", {"run_id": run_id}),
            InvestigationFailureReason.UNKNOWN_TOOL,
        ),
        (
            lambda run_id: call("get_run_events", {"run_id": run_id, "limit": 999}),
            InvestigationFailureReason.INVALID_TOOL_ARGUMENTS,
        ),
        (
            lambda run_id: call(
                "get_run_overview", {"run_id": uuid4()}
            ),
            InvestigationFailureReason.CROSS_RUN_ACCESS,
        ),
    ],
)
def test_invalid_tool_requests_are_recorded_and_terminate_safely(request_factory, reason) -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    model = SequenceInvestigatorModel(
        [InvestigatorTurn(tool_calls=(request_factory(run.run_id),))]
    )

    with pytest.raises(InvestigationFailedError) as raised:
        Investigator(repository, LocalRunbook()).investigate(run.run_id, model)

    assert raised.value.reason is reason
    history = repository.list_investigation_tool_calls(run.run_id)
    assert len(history) == 1
    assert not history[0].succeeded
    assert history[0].failure_reason == reason.value
    assert repository.get_run(run.run_id).canonical_failure_code is CanonicalErrorCode.ERP_UNAVAILABLE


def test_more_than_six_requested_tool_calls_execute_none_and_fail() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    requests = tuple(
        call("get_run_overview", {"run_id": run.run_id}, index)
        for index in range(1, 8)
    )
    model = SequenceInvestigatorModel([InvestigatorTurn(tool_calls=requests)])

    with pytest.raises(InvestigationFailedError) as raised:
        Investigator(repository, LocalRunbook()).investigate(run.run_id, model)

    assert raised.value.reason is InvestigationFailureReason.TOOL_CALL_LIMIT
    assert repository.list_investigation_tool_calls(run.run_id) == ()


def test_three_model_turns_are_hard_limit() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    turns = [
        InvestigatorTurn(
            tool_calls=(
                call("get_run_overview", {"run_id": run.run_id}, index),
            )
        )
        for index in range(1, 4)
    ]
    model = SequenceInvestigatorModel(turns)

    with pytest.raises(InvestigationFailedError) as raised:
        Investigator(repository, LocalRunbook()).investigate(run.run_id, model)

    assert raised.value.reason is InvestigationFailureReason.MODEL_TURN_LIMIT
    assert model.turn_count == 3
    assert len(repository.list_investigation_tool_calls(run.run_id)) == 3


@pytest.mark.parametrize(
    ("turn", "reason"),
    [
        (InvestigatorTurn(report={"not": "a report"}), InvestigationFailureReason.MALFORMED_REPORT),
        (InvestigatorTurn(refused=True), InvestigationFailureReason.MODEL_REFUSAL),
        (InvestigatorModelTimeoutError("secret timeout detail"), InvestigationFailureReason.MODEL_TIMEOUT),
        (RuntimeError("api_key=secret"), InvestigationFailureReason.MODEL_FAILURE),
    ],
)
def test_model_failures_are_sanitized_and_do_not_overwrite_workflow_failure(
    turn, reason
) -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    model = SequenceInvestigatorModel([turn])

    with pytest.raises(InvestigationFailedError) as raised:
        Investigator(repository, LocalRunbook()).investigate(run.run_id, model)

    assert raised.value.reason is reason
    stored = repository.get_investigation_failure(run.run_id)
    assert stored.reason is reason
    assert "secret" not in stored.details
    final_run = repository.get_run(run.run_id)
    assert final_run.investigation_state is InvestigationState.FAILED
    assert final_run.canonical_failure_code is CanonicalErrorCode.ERP_UNAVAILABLE
