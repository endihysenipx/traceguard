"""Exactly four scoped, bounded, read-only diagnostic tools."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from traceguard.domain.enums import CanonicalErrorCode, DiagnosticToolName, WorkflowState
from traceguard.investigation.runbook import LocalRunbook
from traceguard.workflow.models import StageArtifactType
from traceguard.workflow.repository import TraceRepository


class _ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetRunOverviewArguments(_ToolArguments):
    run_id: UUID


class GetRunEventsArguments(_ToolArguments):
    run_id: UUID
    stage: WorkflowState | None = None
    limit: int = Field(default=30, ge=1, le=50)


class GetStageArtifactArguments(_ToolArguments):
    run_id: UUID
    artifact_type: StageArtifactType


class SearchRunbookArguments(_ToolArguments):
    query: str = Field(min_length=1, max_length=240)
    error_code: CanonicalErrorCode | None = None
    limit: int = Field(default=3, ge=1, le=5)


class ToolInvocationError(RuntimeError):
    def __init__(self, reason: str, safe_arguments: dict[str, JsonValue]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.safe_arguments = safe_arguments


class ToolInvocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arguments: dict[str, JsonValue]
    output: JsonValue


TOOL_NAMES = tuple(tool.value for tool in DiagnosticToolName)


class DiagnosticToolRegistry:
    def __init__(
        self,
        repository: TraceRepository,
        runbook: LocalRunbook,
        target_run_id: UUID,
    ) -> None:
        self._repository = repository
        self._runbook = runbook
        self.target_run_id = target_run_id

    @property
    def names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def definitions(self) -> tuple[dict[str, object], ...]:
        run_id = {"type": "string", "format": "uuid"}
        nullable_stage = {
            "anyOf": [
                {"type": "string", "enum": [state.value for state in WorkflowState]},
                {"type": "null"},
            ]
        }
        nullable_error = {
            "anyOf": [
                {
                    "type": "string",
                    "enum": [code.value for code in CanonicalErrorCode],
                },
                {"type": "null"},
            ]
        }
        return (
            _definition(
                DiagnosticToolName.GET_RUN_OVERVIEW,
                "Read bounded run status, stage progression, timing, attempts, provider mode, and available artifacts. Canonical failure facts are omitted.",
                {"run_id": run_id},
                ["run_id"],
            ),
            _definition(
                DiagnosticToolName.GET_RUN_EVENTS,
                "Read chronological sanitized events for the target run, retaining outcome semantics.",
                {
                    "run_id": run_id,
                    "stage": nullable_stage,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["run_id", "stage", "limit"],
            ),
            _definition(
                DiagnosticToolName.GET_STAGE_ARTIFACT,
                "Read one allowlisted stage artifact for the target run.",
                {
                    "run_id": run_id,
                    "artifact_type": {
                        "type": "string",
                        "enum": [item.value for item in StageArtifactType],
                    },
                },
                ["run_id", "artifact_type"],
            ),
            _definition(
                DiagnosticToolName.SEARCH_RUNBOOK,
                "Search only the controlled local runbook using the supplied query and optional diagnosis tag.",
                {
                    "query": {"type": "string", "minLength": 1, "maxLength": 240},
                    "error_code": nullable_error,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                ["query", "error_code", "limit"],
            ),
        )

    def invoke(self, name: str, raw_arguments: object) -> ToolInvocationResult:
        safe_arguments = sanitize_tool_arguments(raw_arguments)
        try:
            tool_name = DiagnosticToolName(name)
        except ValueError:
            raise ToolInvocationError("UNKNOWN_TOOL", safe_arguments) from None

        model_type: type[_ToolArguments]
        model_type = {
            DiagnosticToolName.GET_RUN_OVERVIEW: GetRunOverviewArguments,
            DiagnosticToolName.GET_RUN_EVENTS: GetRunEventsArguments,
            DiagnosticToolName.GET_STAGE_ARTIFACT: GetStageArtifactArguments,
            DiagnosticToolName.SEARCH_RUNBOOK: SearchRunbookArguments,
        }[tool_name]
        try:
            arguments = model_type.model_validate(raw_arguments)
        except ValidationError:
            raise ToolInvocationError("INVALID_TOOL_ARGUMENTS", safe_arguments) from None

        validated = arguments.model_dump(mode="json")
        if hasattr(arguments, "run_id") and arguments.run_id != self.target_run_id:
            raise ToolInvocationError("CROSS_RUN_ACCESS", validated)

        try:
            if isinstance(arguments, GetRunOverviewArguments):
                output = self._get_run_overview(arguments)
            elif isinstance(arguments, GetRunEventsArguments):
                output = self._get_run_events(arguments)
            elif isinstance(arguments, GetStageArtifactArguments):
                output = self._get_stage_artifact(arguments)
            else:
                output = self._search_runbook(arguments)
        except ToolInvocationError:
            raise
        except Exception:
            raise ToolInvocationError("TOOL_EXECUTION_FAILED", validated) from None
        return ToolInvocationResult(arguments=validated, output=_bounded_json(output))

    def _get_run_overview(self, arguments: GetRunOverviewArguments) -> dict[str, object]:
        run = self._repository.get_run(arguments.run_id)
        events = self._repository.list_events(arguments.run_id)
        artifacts = self._repository.list_stage_artifacts(arguments.run_id)
        progression = list(dict.fromkeys(event.workflow_stage.value for event in events))
        available = list(dict.fromkeys(item.artifact_type.value for item in artifacts))
        return {
            "run_id": str(run.run_id),
            "workflow_state": run.workflow_state.value,
            "investigation_state": run.investigation_state.value,
            "recovery_state": run.recovery_state.value,
            "stage_progression": progression,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "erp_attempt_count": run.erp_attempt_count,
            "extraction_provider_mode": (
                run.extraction_provider_mode.value
                if run.extraction_provider_mode is not None
                else None
            ),
            "investigation_provider_mode": (
                run.investigation_provider_mode.value
                if run.investigation_provider_mode is not None
                else None
            ),
            "available_artifact_types": available,
        }

    def _get_run_events(self, arguments: GetRunEventsArguments) -> dict[str, object]:
        events = self._repository.list_events(arguments.run_id)
        if arguments.stage is not None:
            events = tuple(
                event for event in events if event.workflow_stage is arguments.stage
            )
        return {
            "run_id": str(arguments.run_id),
            "events": [
                {
                    "event_id": str(event.event_id),
                    "timestamp": event.timestamp.isoformat(),
                    "workflow_stage": event.workflow_stage.value,
                    "event_type": event.event_type.value,
                    "severity": event.severity.value,
                    "outcome": event.outcome.value,
                    "details": event.details,
                }
                for event in events[: arguments.limit]
            ],
        }

    def _get_stage_artifact(
        self, arguments: GetStageArtifactArguments
    ) -> dict[str, object]:
        artifact = self._repository.get_latest_stage_artifact(
            arguments.run_id, arguments.artifact_type
        )
        return {
            "run_id": str(arguments.run_id),
            "artifact_id": str(artifact.artifact_id),
            "timestamp": artifact.timestamp.isoformat(),
            "artifact_type": artifact.artifact_type.value,
            "data": artifact.data,
        }

    def _search_runbook(self, arguments: SearchRunbookArguments) -> dict[str, object]:
        entries = self._runbook.search(
            arguments.query,
            error_code=arguments.error_code,
            limit=arguments.limit,
        )
        return {
            "results": [entry.model_dump(mode="json") for entry in entries]
        }


def _definition(
    name: DiagnosticToolName,
    description: str,
    properties: dict[str, object],
    required: list[str],
) -> dict[str, object]:
    return {
        "type": "function",
        "name": name.value,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": True,
    }


def sanitize_tool_arguments(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        return {"rejected_argument_type": type(value).__name__}
    return _bounded_json(value)


def _bounded_json(value: Any, *, depth: int = 0) -> JsonValue:
    if depth >= 6:
        return "[depth limit]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _bounded_json(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_json(item, depth=depth + 1) for item in value[:50]]
    return str(value)[:200]
