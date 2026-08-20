from uuid import uuid4

import pytest

from traceguard.domain.enums import (
    CanonicalErrorCode,
    EventOutcome,
    FailureCategory,
    InvestigationState,
    WorkflowState,
)
from traceguard.domain.errors import IllegalStateTransition
from traceguard.workflow.models import (
    EventSeverity,
    EventType,
    MockErpBehavior,
    StageArtifact,
    StageArtifactType,
    TraceEvent,
    WorkflowRun,
)
from traceguard.workflow.repository import (
    ArtifactNotFoundError,
    InMemoryTraceRepository,
    RunNotFoundError,
    TraceRepositoryError,
)


def create_run(repository: InMemoryTraceRepository) -> WorkflowRun:
    return repository.create_run(
        WorkflowRun(
            order_request_text="Order 2 units for customer C-1.",
            mock_erp_behavior=MockErpBehavior.SUCCEED,
        )
    )


def test_events_are_append_only_ordered_and_returned_as_a_snapshot() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)
    first = TraceEvent(
        run_id=run.run_id,
        workflow_stage=WorkflowState.CREATED,
        event_type=EventType.RUN_CREATED,
        severity=EventSeverity.INFO,
        outcome=EventOutcome.SUCCESS,
        details="Run created.",
    )
    second = TraceEvent(
        run_id=run.run_id,
        workflow_stage=WorkflowState.EXTRACTING,
        event_type=EventType.EXTRACTION_STARTED,
        severity=EventSeverity.INFO,
        outcome=EventOutcome.CONTINUED,
        details="Extraction started.",
    )

    repository.append_event(first)
    original_snapshot = repository.list_events(run.run_id)
    repository.append_event(second)

    assert isinstance(original_snapshot, tuple)
    assert original_snapshot == (first,)
    assert repository.list_events(run.run_id) == (first, second)


def test_stage_artifact_reads_cannot_mutate_stored_history() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)
    repository.append_stage_artifact(
        StageArtifact(
            run_id=run.run_id,
            artifact_type=StageArtifactType.EXTRACTION,
            data={"output": {"customer_number": "C-1"}},
        )
    )

    retrieved = repository.get_latest_stage_artifact(
        run.run_id, StageArtifactType.EXTRACTION
    )
    retrieved.data["output"]["customer_number"] = "MUTATED"

    stored = repository.get_latest_stage_artifact(
        run.run_id, StageArtifactType.EXTRACTION
    )
    assert stored.data["output"]["customer_number"] == "C-1"


def test_artifacts_are_appended_instead_of_replaced() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)
    for attempt_number in (1, 2):
        repository.append_stage_artifact(
            StageArtifact(
                run_id=run.run_id,
                artifact_type=StageArtifactType.ERP,
                data={"attempt_number": attempt_number},
            )
        )

    artifacts = repository.list_stage_artifacts(
        run.run_id, StageArtifactType.ERP
    )
    assert [artifact.data["attempt_number"] for artifact in artifacts] == [1, 2]


def test_unknown_run_and_artifact_access_fail_clearly() -> None:
    repository = InMemoryTraceRepository()
    unknown_run_id = uuid4()

    with pytest.raises(RunNotFoundError, match="Unknown run"):
        repository.get_run(unknown_run_id)

    run = create_run(repository)
    with pytest.raises(ArtifactNotFoundError, match="No ERP artifact"):
        repository.get_latest_stage_artifact(run.run_id, StageArtifactType.ERP)


def test_repository_rejects_illegal_workflow_transition() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)

    with pytest.raises(IllegalStateTransition):
        repository.transition_workflow(run.run_id, WorkflowState.SUCCEEDED)

    assert repository.get_run(run.run_id).workflow_state is WorkflowState.CREATED


def test_failure_facts_must_match_current_stage_and_canonical_category() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)
    repository.transition_workflow(run.run_id, WorkflowState.EXTRACTING)

    with pytest.raises(TraceRepositoryError, match="current active stage"):
        repository.mark_run_failed(
            run.run_id,
            failure_stage=WorkflowState.DOMAIN_VALIDATING,
            code=CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
            category=FailureCategory.EXTRACTION_FAILURE,
        )

    with pytest.raises(TraceRepositoryError, match="canonical error code"):
        repository.mark_run_failed(
            run.run_id,
            failure_stage=WorkflowState.EXTRACTING,
            code=CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
            category=FailureCategory.DOMAIN_VALIDATION_FAILURE,
        )


def test_marking_failure_preserves_history_and_sets_investigation_pending() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)
    repository.transition_workflow(run.run_id, WorkflowState.EXTRACTING)
    event = repository.append_event(
        TraceEvent(
            run_id=run.run_id,
            workflow_stage=WorkflowState.EXTRACTING,
            event_type=EventType.EXTRACTION_FAILED,
            severity=EventSeverity.ERROR,
            outcome=EventOutcome.TERMINAL,
            details="Sanitized extraction failure.",
        )
    )

    failed = repository.mark_run_failed(
        run.run_id,
        failure_stage=WorkflowState.EXTRACTING,
        code=CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
        category=FailureCategory.EXTRACTION_FAILURE,
    )

    assert failed.workflow_state is WorkflowState.FAILED
    assert failed.investigation_state is InvestigationState.PENDING
    assert repository.list_events(run.run_id) == (event,)


def test_erp_attempts_are_sequential_and_observable_on_run() -> None:
    repository = InMemoryTraceRepository()
    run = create_run(repository)

    first = repository.record_erp_attempt(
        run.run_id,
        behavior=MockErpBehavior.FAIL_ONCE_503,
        status_code=503,
        succeeded=False,
        response_summary="Unavailable.",
    )
    second = repository.record_erp_attempt(
        run.run_id,
        behavior=MockErpBehavior.FAIL_ONCE_503,
        status_code=200,
        succeeded=True,
        response_summary="Accepted.",
    )

    assert (first.attempt_number, second.attempt_number) == (1, 2)
    assert repository.get_run(run.run_id).erp_attempt_count == 2
    assert repository.list_erp_attempts(run.run_id) == (first, second)

