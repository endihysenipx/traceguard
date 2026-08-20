"""Process-local append-only trace repository."""

from collections.abc import Sequence
from threading import RLock
from typing import Protocol
from uuid import UUID

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    FailureCategory,
    InvestigationState,
    ProviderMode,
    WorkflowState,
)
from traceguard.domain.models import InvestigationReport
from traceguard.domain.transitions import (
    ensure_investigation_transition,
    ensure_workflow_transition,
)
from traceguard.workflow.models import (
    ErpAttempt,
    InvestigationFailure,
    InvestigationToolCall,
    MockErpBehavior,
    StageArtifact,
    StageArtifactType,
    TraceEvent,
    WorkflowRun,
    utc_now,
)


class TraceRepository(Protocol):
    def create_run(self, run: WorkflowRun) -> WorkflowRun: ...

    def get_run(self, run_id: UUID) -> WorkflowRun: ...

    def transition_workflow(
        self, run_id: UUID, target: WorkflowState
    ) -> WorkflowRun: ...

    def mark_run_failed(
        self,
        run_id: UUID,
        *,
        failure_stage: WorkflowState,
        code: CanonicalErrorCode,
        category: FailureCategory,
    ) -> WorkflowRun: ...

    def append_event(self, event: TraceEvent) -> TraceEvent: ...

    def list_events(self, run_id: UUID) -> Sequence[TraceEvent]: ...

    def append_stage_artifact(self, artifact: StageArtifact) -> StageArtifact: ...

    def list_stage_artifacts(
        self,
        run_id: UUID,
        artifact_type: StageArtifactType | None = None,
    ) -> Sequence[StageArtifact]: ...

    def get_latest_stage_artifact(
        self, run_id: UUID, artifact_type: StageArtifactType
    ) -> StageArtifact: ...

    def record_erp_attempt(
        self,
        run_id: UUID,
        *,
        behavior: MockErpBehavior,
        status_code: int,
        succeeded: bool,
        response_summary: str,
    ) -> ErpAttempt: ...

    def list_erp_attempts(self, run_id: UUID) -> Sequence[ErpAttempt]: ...

    def transition_investigation(
        self,
        run_id: UUID,
        target: InvestigationState,
        *,
        provider_mode: ProviderMode | None = None,
    ) -> WorkflowRun: ...

    def append_investigation_tool_call(
        self, call: InvestigationToolCall
    ) -> InvestigationToolCall: ...

    def list_investigation_tool_calls(
        self, run_id: UUID
    ) -> Sequence[InvestigationToolCall]: ...

    def complete_investigation(
        self, report: InvestigationReport
    ) -> WorkflowRun: ...

    def get_investigation_report(self, run_id: UUID) -> InvestigationReport: ...

    def fail_investigation(
        self, failure: InvestigationFailure
    ) -> WorkflowRun: ...

    def get_investigation_failure(self, run_id: UUID) -> InvestigationFailure: ...


class TraceRepositoryError(RuntimeError):
    """Base error for explicit repository failures."""


class RunNotFoundError(TraceRepositoryError):
    pass


class RunAlreadyExistsError(TraceRepositoryError):
    pass


class ArtifactNotFoundError(TraceRepositoryError):
    pass


class DuplicateTraceRecordError(TraceRepositoryError):
    pass


class InvestigationRecordNotFoundError(TraceRepositoryError):
    pass


class InMemoryTraceRepository:
    """Thread-safe process-local storage; intentionally not production persistence."""

    def __init__(self) -> None:
        self._runs: dict[UUID, WorkflowRun] = {}
        self._events: dict[UUID, list[TraceEvent]] = {}
        self._artifacts: dict[UUID, list[StageArtifact]] = {}
        self._erp_attempts: dict[UUID, list[ErpAttempt]] = {}
        self._investigation_calls: dict[UUID, list[InvestigationToolCall]] = {}
        self._investigation_reports: dict[UUID, InvestigationReport] = {}
        self._investigation_failures: dict[UUID, InvestigationFailure] = {}
        self._event_ids: set[UUID] = set()
        self._artifact_ids: set[UUID] = set()
        self._investigation_call_ids: set[UUID] = set()
        self._lock = RLock()

    def create_run(self, run: WorkflowRun) -> WorkflowRun:
        with self._lock:
            if run.run_id in self._runs:
                raise RunAlreadyExistsError(f"Run already exists: {run.run_id}")
            if run.workflow_state is not WorkflowState.CREATED:
                raise TraceRepositoryError("A new run must start in CREATED.")
            stored = run.model_copy(deep=True)
            self._runs[run.run_id] = stored
            self._events[run.run_id] = []
            self._artifacts[run.run_id] = []
            self._erp_attempts[run.run_id] = []
            self._investigation_calls[run.run_id] = []
            return stored.model_copy(deep=True)

    def get_run(self, run_id: UUID) -> WorkflowRun:
        with self._lock:
            return self._require_run(run_id).model_copy(deep=True)

    def transition_workflow(
        self, run_id: UUID, target: WorkflowState
    ) -> WorkflowRun:
        with self._lock:
            current = self._require_run(run_id)
            ensure_workflow_transition(current.workflow_state, target)
            updated = self._replace_run(current, workflow_state=target)
            self._runs[run_id] = updated
            return updated.model_copy(deep=True)

    def mark_run_failed(
        self,
        run_id: UUID,
        *,
        failure_stage: WorkflowState,
        code: CanonicalErrorCode,
        category: FailureCategory,
    ) -> WorkflowRun:
        with self._lock:
            current = self._require_run(run_id)
            ensure_workflow_transition(current.workflow_state, WorkflowState.FAILED)
            if current.workflow_state is not failure_stage:
                raise TraceRepositoryError(
                    "Failure stage must match the run's current active stage."
                )
            if CANONICAL_FAILURE_CATEGORY[code] is not category:
                raise TraceRepositoryError(
                    "Failure category does not match the canonical error code."
                )
            ensure_investigation_transition(
                current.investigation_state, InvestigationState.PENDING
            )
            updated = self._replace_run(
                current,
                workflow_state=WorkflowState.FAILED,
                investigation_state=InvestigationState.PENDING,
                canonical_failure_code=code,
                canonical_failure_category=category,
                failure_stage=failure_stage,
            )
            self._runs[run_id] = updated
            return updated.model_copy(deep=True)

    def append_event(self, event: TraceEvent) -> TraceEvent:
        with self._lock:
            current = self._require_run(event.run_id)
            if event.event_id in self._event_ids:
                raise DuplicateTraceRecordError(
                    f"Event already exists: {event.event_id}"
                )
            events = self._events[event.run_id]
            if events and event.timestamp < events[-1].timestamp:
                raise TraceRepositoryError("Events must be appended chronologically.")
            stored = event.model_copy(deep=True)
            events.append(stored)
            self._event_ids.add(event.event_id)
            self._runs[event.run_id] = self._replace_run(current)
            return stored.model_copy(deep=True)

    def list_events(self, run_id: UUID) -> tuple[TraceEvent, ...]:
        with self._lock:
            self._require_run(run_id)
            return tuple(event.model_copy(deep=True) for event in self._events[run_id])

    def append_stage_artifact(self, artifact: StageArtifact) -> StageArtifact:
        with self._lock:
            current = self._require_run(artifact.run_id)
            if artifact.artifact_id in self._artifact_ids:
                raise DuplicateTraceRecordError(
                    f"Artifact already exists: {artifact.artifact_id}"
                )
            stored = artifact.model_copy(deep=True)
            self._artifacts[artifact.run_id].append(stored)
            self._artifact_ids.add(artifact.artifact_id)
            self._runs[artifact.run_id] = self._replace_run(current)
            return stored.model_copy(deep=True)

    def list_stage_artifacts(
        self,
        run_id: UUID,
        artifact_type: StageArtifactType | None = None,
    ) -> tuple[StageArtifact, ...]:
        with self._lock:
            self._require_run(run_id)
            artifacts = self._artifacts[run_id]
            if artifact_type is not None:
                artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact.artifact_type is artifact_type
                ]
            return tuple(
                artifact.model_copy(deep=True) for artifact in artifacts
            )

    def get_latest_stage_artifact(
        self, run_id: UUID, artifact_type: StageArtifactType
    ) -> StageArtifact:
        artifacts = self.list_stage_artifacts(run_id, artifact_type)
        if not artifacts:
            raise ArtifactNotFoundError(
                f"No {artifact_type.value} artifact for run {run_id}"
            )
        return artifacts[-1]

    def record_erp_attempt(
        self,
        run_id: UUID,
        *,
        behavior: MockErpBehavior,
        status_code: int,
        succeeded: bool,
        response_summary: str,
    ) -> ErpAttempt:
        with self._lock:
            current = self._require_run(run_id)
            attempt = ErpAttempt(
                run_id=run_id,
                attempt_number=len(self._erp_attempts[run_id]) + 1,
                behavior=behavior,
                status_code=status_code,
                succeeded=succeeded,
                response_summary=response_summary,
            )
            self._erp_attempts[run_id].append(attempt)
            self._runs[run_id] = self._replace_run(
                current, erp_attempt_count=attempt.attempt_number
            )
            return attempt.model_copy(deep=True)

    def list_erp_attempts(self, run_id: UUID) -> tuple[ErpAttempt, ...]:
        with self._lock:
            self._require_run(run_id)
            return tuple(
                attempt.model_copy(deep=True)
                for attempt in self._erp_attempts[run_id]
            )

    def transition_investigation(
        self,
        run_id: UUID,
        target: InvestigationState,
        *,
        provider_mode: ProviderMode | None = None,
    ) -> WorkflowRun:
        with self._lock:
            current = self._require_run(run_id)
            if current.workflow_state is not WorkflowState.FAILED:
                raise TraceRepositoryError(
                    "Investigation state may change only for a failed workflow run."
                )
            ensure_investigation_transition(current.investigation_state, target)
            updates: dict[str, object] = {"investigation_state": target}
            if provider_mode is not None:
                updates["investigation_provider_mode"] = provider_mode
            updated = self._replace_run(current, **updates)
            self._runs[run_id] = updated
            return updated.model_copy(deep=True)

    def append_investigation_tool_call(
        self, call: InvestigationToolCall
    ) -> InvestigationToolCall:
        with self._lock:
            self._require_run(call.run_id)
            if call.call_id in self._investigation_call_ids:
                raise DuplicateTraceRecordError(
                    f"Investigation call already exists: {call.call_id}"
                )
            calls = self._investigation_calls[call.run_id]
            if call.sequence_number != len(calls) + 1:
                raise TraceRepositoryError(
                    "Investigation tool-call sequence numbers must be contiguous."
                )
            stored = call.model_copy(deep=True)
            calls.append(stored)
            self._investigation_call_ids.add(call.call_id)
            return stored.model_copy(deep=True)

    def list_investigation_tool_calls(
        self, run_id: UUID
    ) -> tuple[InvestigationToolCall, ...]:
        with self._lock:
            self._require_run(run_id)
            return tuple(
                call.model_copy(deep=True)
                for call in self._investigation_calls[run_id]
            )

    def complete_investigation(
        self, report: InvestigationReport
    ) -> WorkflowRun:
        with self._lock:
            current = self._require_run(report.run_id)
            ensure_investigation_transition(
                current.investigation_state, InvestigationState.COMPLETED
            )
            if report.run_id in self._investigation_reports:
                raise DuplicateTraceRecordError(
                    f"Investigation report already exists: {report.run_id}"
                )
            self._investigation_reports[report.run_id] = report.model_copy(deep=True)
            updated = self._replace_run(
                current, investigation_state=InvestigationState.COMPLETED
            )
            self._runs[report.run_id] = updated
            return updated.model_copy(deep=True)

    def get_investigation_report(self, run_id: UUID) -> InvestigationReport:
        with self._lock:
            self._require_run(run_id)
            try:
                return self._investigation_reports[run_id].model_copy(deep=True)
            except KeyError as exc:
                raise InvestigationRecordNotFoundError(
                    f"No investigation report for run {run_id}"
                ) from exc

    def fail_investigation(
        self, failure: InvestigationFailure
    ) -> WorkflowRun:
        with self._lock:
            current = self._require_run(failure.run_id)
            ensure_investigation_transition(
                current.investigation_state, InvestigationState.FAILED
            )
            if failure.run_id in self._investigation_failures:
                raise DuplicateTraceRecordError(
                    f"Investigation failure already exists: {failure.run_id}"
                )
            self._investigation_failures[failure.run_id] = failure.model_copy(deep=True)
            updated = self._replace_run(
                current, investigation_state=InvestigationState.FAILED
            )
            self._runs[failure.run_id] = updated
            return updated.model_copy(deep=True)

    def get_investigation_failure(self, run_id: UUID) -> InvestigationFailure:
        with self._lock:
            self._require_run(run_id)
            try:
                return self._investigation_failures[run_id].model_copy(deep=True)
            except KeyError as exc:
                raise InvestigationRecordNotFoundError(
                    f"No investigation failure for run {run_id}"
                ) from exc

    def _require_run(self, run_id: UUID) -> WorkflowRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFoundError(f"Unknown run: {run_id}") from exc

    @staticmethod
    def _replace_run(run: WorkflowRun, **updates: object) -> WorkflowRun:
        values = run.model_dump()
        values.update(updates)
        values["updated_at"] = utc_now()
        return WorkflowRun.model_validate(values)
