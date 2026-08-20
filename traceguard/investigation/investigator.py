"""Deterministic three-turn/six-call investigator orchestration."""

from uuid import UUID

from pydantic import ValidationError

from traceguard.domain.enums import InvestigationFailureReason, InvestigationState, WorkflowState
from traceguard.domain.models import InvestigationReport
from traceguard.investigation.models import (
    InvestigationStartContext,
    InvestigatorModel,
    InvestigatorModelRefusalError,
    InvestigatorModelTimeoutError,
    ToolCallResult,
)
from traceguard.investigation.runbook import LocalRunbook
from traceguard.investigation.tools import DiagnosticToolRegistry, ToolInvocationError
from traceguard.investigation.validation import (
    InvestigationReportValidationError,
    validate_investigation_report,
)
from traceguard.workflow.models import InvestigationFailure, InvestigationToolCall
from traceguard.workflow.repository import TraceRepository


MAX_MODEL_TURNS = 3
MAX_TOOL_CALLS = 6


class InvestigationNotAllowedError(RuntimeError):
    pass


class InvestigationFailedError(RuntimeError):
    def __init__(self, reason: InvestigationFailureReason) -> None:
        super().__init__(f"Investigation failed safely: {reason.value}")
        self.reason = reason


class Investigator:
    def __init__(self, repository: TraceRepository, runbook: LocalRunbook) -> None:
        self._repository = repository
        self._runbook = runbook

    def investigate(self, run_id: UUID, model: InvestigatorModel) -> InvestigationReport:
        run = self._repository.get_run(run_id)
        if run.workflow_state is not WorkflowState.FAILED:
            raise InvestigationNotAllowedError("Only failed workflow runs may be investigated.")
        if run.investigation_state is not InvestigationState.PENDING:
            raise InvestigationNotAllowedError("The run is not pending investigation.")

        self._repository.transition_investigation(
            run_id, InvestigationState.RUNNING, provider_mode=model.mode
        )
        registry = DiagnosticToolRegistry(self._repository, self._runbook, run_id)
        context = InvestigationStartContext(
            run_id=run_id,
            max_model_turns=MAX_MODEL_TURNS,
            max_tool_calls=MAX_TOOL_CALLS,
        )
        try:
            model.start(context, registry.definitions())
        except InvestigatorModelTimeoutError:
            self._fail(run_id, InvestigationFailureReason.MODEL_TIMEOUT)
        except Exception:
            self._fail(run_id, InvestigationFailureReason.MODEL_FAILURE)

        tool_calls_used = 0
        for _turn_number in range(1, MAX_MODEL_TURNS + 1):
            try:
                turn = model.next_turn()
            except InvestigatorModelTimeoutError:
                self._fail(run_id, InvestigationFailureReason.MODEL_TIMEOUT)
            except InvestigatorModelRefusalError:
                self._fail(run_id, InvestigationFailureReason.MODEL_REFUSAL)
            except Exception:
                self._fail(run_id, InvestigationFailureReason.MODEL_FAILURE)

            if turn.refused:
                self._fail(run_id, InvestigationFailureReason.MODEL_REFUSAL)
            if turn.report is not None and turn.tool_calls:
                self._fail(run_id, InvestigationFailureReason.MALFORMED_REPORT)

            if turn.report is not None:
                try:
                    report = InvestigationReport.model_validate(turn.report)
                except ValidationError:
                    self._fail(run_id, InvestigationFailureReason.MALFORMED_REPORT)
                try:
                    validate_investigation_report(
                        report,
                        target_run_id=run_id,
                        events=self._repository.list_events(run_id),
                        runbook=self._runbook,
                        retrieved_event_ids=self._retrieved_event_ids(run_id),
                        retrieved_runbook_ids=self._retrieved_runbook_ids(run_id),
                    )
                except InvestigationReportValidationError:
                    self._fail(run_id, InvestigationFailureReason.REPORT_NOT_GROUNDED)
                self._repository.complete_investigation(report)
                return report

            if not turn.tool_calls:
                self._fail(run_id, InvestigationFailureReason.MALFORMED_REPORT)
            if tool_calls_used + len(turn.tool_calls) > MAX_TOOL_CALLS:
                self._fail(run_id, InvestigationFailureReason.TOOL_CALL_LIMIT)

            results: list[ToolCallResult] = []
            for requested in turn.tool_calls:
                tool_calls_used += 1
                sequence_number = len(
                    self._repository.list_investigation_tool_calls(run_id)
                ) + 1
                try:
                    invocation = registry.invoke(requested.name, requested.arguments)
                except ToolInvocationError as error:
                    self._repository.append_investigation_tool_call(
                        InvestigationToolCall(
                            run_id=run_id,
                            sequence_number=sequence_number,
                            tool_name=requested.name,
                            arguments=error.safe_arguments,
                            succeeded=False,
                            failure_reason=error.reason,
                        )
                    )
                    self._fail(run_id, InvestigationFailureReason(error.reason))
                self._repository.append_investigation_tool_call(
                    InvestigationToolCall(
                        run_id=run_id,
                        sequence_number=sequence_number,
                        tool_name=requested.name,
                        arguments=invocation.arguments,
                        succeeded=True,
                        result=invocation.output,
                    )
                )
                results.append(
                    ToolCallResult(
                        provider_call_id=requested.provider_call_id,
                        name=requested.name,
                        output=invocation.output,
                    )
                )
            try:
                model.submit_tool_results(tuple(results))
            except InvestigatorModelTimeoutError:
                self._fail(run_id, InvestigationFailureReason.MODEL_TIMEOUT)
            except Exception:
                self._fail(run_id, InvestigationFailureReason.MODEL_FAILURE)

        self._fail(run_id, InvestigationFailureReason.MODEL_TURN_LIMIT)

    def _retrieved_event_ids(self, run_id: UUID) -> frozenset[UUID]:
        identifiers: set[UUID] = set()
        for call in self._repository.list_investigation_tool_calls(run_id):
            if not call.succeeded or call.tool_name != "get_run_events":
                continue
            if not isinstance(call.result, dict):
                continue
            for event in call.result.get("events", []):
                if isinstance(event, dict) and isinstance(event.get("event_id"), str):
                    try:
                        identifiers.add(UUID(event["event_id"]))
                    except ValueError:
                        continue
        return frozenset(identifiers)

    def _retrieved_runbook_ids(self, run_id: UUID) -> frozenset[str]:
        identifiers: set[str] = set()
        for call in self._repository.list_investigation_tool_calls(run_id):
            if not call.succeeded or call.tool_name != "search_runbook":
                continue
            if not isinstance(call.result, dict):
                continue
            for entry in call.result.get("results", []):
                if isinstance(entry, dict) and isinstance(entry.get("entry_id"), str):
                    identifiers.add(entry["entry_id"])
        return frozenset(identifiers)

    def _fail(self, run_id: UUID, reason: InvestigationFailureReason) -> None:
        self._repository.fail_investigation(
            InvestigationFailure(
                run_id=run_id,
                reason=reason,
                details=f"Investigation terminated safely: {reason.value}.",
            )
        )
        raise InvestigationFailedError(reason)
