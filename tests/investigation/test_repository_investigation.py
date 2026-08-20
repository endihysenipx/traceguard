from traceguard.domain.enums import (
    CanonicalErrorCode,
    InvestigationFailureReason,
    InvestigationState,
)
from traceguard.investigation.models import InvestigationStartContext
from traceguard.workflow.models import InvestigationFailure, InvestigationToolCall, PresetId

from tests.investigation.support import execute_fixture


def test_tool_history_is_append_only_ordered_and_defensive() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    repository.transition_investigation(run.run_id, InvestigationState.RUNNING)
    first = repository.append_investigation_tool_call(
        InvestigationToolCall(
            run_id=run.run_id,
            sequence_number=1,
            tool_name="get_run_overview",
            arguments={"run_id": str(run.run_id)},
            succeeded=True,
            result={"workflow_state": "FAILED"},
        )
    )
    snapshot = repository.list_investigation_tool_calls(run.run_id)
    repository.append_investigation_tool_call(
        InvestigationToolCall(
            run_id=run.run_id,
            sequence_number=2,
            tool_name="get_run_events",
            arguments={"run_id": str(run.run_id)},
            succeeded=True,
            result={"events": []},
        )
    )

    assert snapshot == (first,)
    assert [item.sequence_number for item in repository.list_investigation_tool_calls(run.run_id)] == [1, 2]


def test_investigation_failure_changes_only_orthogonal_state() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    original_events = repository.list_events(run.run_id)
    original_artifacts = repository.list_stage_artifacts(run.run_id)
    repository.transition_investigation(run.run_id, InvestigationState.RUNNING)
    repository.fail_investigation(
        InvestigationFailure(
            run_id=run.run_id,
            reason=InvestigationFailureReason.MODEL_FAILURE,
            details="Investigation failed safely.",
        )
    )

    final = repository.get_run(run.run_id)
    assert final.investigation_state is InvestigationState.FAILED
    assert final.canonical_failure_code is CanonicalErrorCode.ERP_UNAVAILABLE
    assert repository.list_events(run.run_id) == original_events
    assert repository.list_stage_artifacts(run.run_id) == original_artifacts
