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
    WorkflowState,
)
from traceguard.domain.transitions import (
    ensure_investigation_transition,
    ensure_workflow_transition,
)
from traceguard.workflow.models import (
    ErpAttempt,
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


class InMemoryTraceRepository:
    """Thread-safe process-local storage; intentionally not production persistence."""

    def __init__(self) -> None:
        self._runs: dict[UUID, WorkflowRun] = {}
        self._events: dict[UUID, list[TraceEvent]] = {}
        self._artifacts: dict[UUID, list[StageArtifact]] = {}
        self._erp_attempts: dict[UUID, list[ErpAttempt]] = {}
        self._event_ids: set[UUID] = set()
        self._artifact_ids: set[UUID] = set()
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

