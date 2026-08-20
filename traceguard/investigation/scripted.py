"""Deterministic offline investigator that still uses the real four tools."""

from uuid import UUID, uuid4

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    Confidence,
    EvidenceRole,
    EventOutcome,
    ProviderMode,
    RecoveryAction,
    WorkflowState,
)
from traceguard.domain.models import EvidenceItem, InvestigationReport
from traceguard.investigation.models import (
    InvestigationStartContext,
    InvestigatorModelResponseError,
    InvestigatorTurn,
    ToolCallRequest,
    ToolCallResult,
)
from traceguard.workflow.models import EventType, StageArtifactType


class ScriptedInvestigatorModel:
    """An explicitly non-AI diagnostic strategy driven only by tool results."""

    mode = ProviderMode.SCRIPTED

    def __init__(self) -> None:
        self._context: InvestigationStartContext | None = None
        self._turn = 0
        self._results: dict[str, object] = {}

    def start(
        self,
        context: InvestigationStartContext,
        tool_definitions: tuple[dict[str, object], ...],
    ) -> None:
        self._context = context
        self._turn = 0
        self._results = {}

    def next_turn(self) -> InvestigatorTurn:
        if self._context is None:
            raise InvestigatorModelResponseError("Scripted investigator was not started.")
        self._turn += 1
        run_id = self._context.run_id
        if self._turn == 1:
            return InvestigatorTurn(
                tool_calls=(
                    _call("scripted-overview", "get_run_overview", {"run_id": run_id}),
                    _call(
                        "scripted-events",
                        "get_run_events",
                        {"run_id": run_id, "stage": None, "limit": 50},
                    ),
                )
            )
        if self._turn == 2:
            terminal = self._terminal_event()
            stage = WorkflowState(terminal["workflow_stage"])
            artifact_type = _ARTIFACT_BY_STAGE[stage]
            code = _ERROR_BY_EVENT.get(EventType(terminal["event_type"]))
            return InvestigatorTurn(
                tool_calls=(
                    _call(
                        "scripted-artifact",
                        "get_stage_artifact",
                        {"run_id": run_id, "artifact_type": artifact_type},
                    ),
                    _call(
                        "scripted-runbook",
                        "search_runbook",
                        {
                            "query": _QUERY_BY_STAGE[stage],
                            "error_code": code,
                            "limit": 3,
                        },
                    ),
                )
            )
        if self._turn == 3:
            return InvestigatorTurn(report=self._build_report())
        raise InvestigatorModelResponseError("Scripted investigator exceeded its strategy.")

    def submit_tool_results(self, results: tuple[ToolCallResult, ...]) -> None:
        for result in results:
            self._results[result.name] = result.output

    def _terminal_event(self) -> dict[str, object]:
        result = self._results.get("get_run_events")
        if not isinstance(result, dict) or not isinstance(result.get("events"), list):
            raise InvestigatorModelResponseError("Event evidence is unavailable.")
        terminal = [
            event
            for event in result["events"]
            if isinstance(event, dict) and event.get("outcome") == EventOutcome.TERMINAL.value
        ]
        if not terminal:
            raise InvestigatorModelResponseError("No terminal event was retrieved.")
        return terminal[-1]

    def _build_report(self) -> InvestigationReport:
        if self._context is None:
            raise InvestigatorModelResponseError("Missing investigation context.")
        terminal = self._terminal_event()
        artifact_result = self._results.get("get_stage_artifact")
        runbook_result = self._results.get("search_runbook")
        if not isinstance(artifact_result, dict) or not isinstance(runbook_result, dict):
            raise InvestigatorModelResponseError("Required evidence was not retrieved.")
        artifact_data = artifact_result.get("data", {})
        code_value = artifact_data.get("error_code") if isinstance(artifact_data, dict) else None
        code = (
            CanonicalErrorCode(code_value)
            if isinstance(code_value, str)
            else _ERROR_BY_EVENT[EventType(terminal["event_type"])]
        )

        evidence = [
            EvidenceItem(
                event_id=UUID(terminal["event_id"]),
                role=EvidenceRole.TERMINAL_CAUSE,
                observation=f"{terminal['event_type']} was terminal: {terminal['details']}",
            )
        ]
        events_result = self._results["get_run_events"]
        for event in events_result["events"]:
            if event["outcome"] in {
                EventOutcome.CONTINUED.value,
                EventOutcome.RECOVERED.value,
            }:
                evidence.append(
                    EvidenceItem(
                        event_id=UUID(event["event_id"]),
                        role=EvidenceRole.NON_CAUSAL_CONTEXT,
                        observation=(
                            f"{event['event_type']} was {event['outcome']} and is not causal."
                        ),
                    )
                )
            if len(evidence) == 3:
                break

        references = [
            entry["entry_id"]
            for entry in runbook_result.get("results", [])
            if isinstance(entry, dict) and isinstance(entry.get("entry_id"), str)
        ][:3]
        return InvestigationReport(
            report_id=uuid4(),
            run_id=self._context.run_id,
            failure_category=CANONICAL_FAILURE_CATEGORY[code],
            diagnosed_error_code=code,
            root_cause=_ROOT_CAUSE[code],
            evidence=evidence,
            recommended_action=_ACTION[code],
            rationale=_RATIONALE[code],
            confidence=Confidence.HIGH,
            uncertainties=[],
            runbook_references=references,
        )


def _call(call_id: str, name: str, arguments: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(provider_call_id=call_id, name=name, arguments=arguments)


_ARTIFACT_BY_STAGE = {
    WorkflowState.EXTRACTING: StageArtifactType.EXTRACTION,
    WorkflowState.STRUCTURE_VALIDATING: StageArtifactType.STRUCTURAL_VALIDATION,
    WorkflowState.DOMAIN_VALIDATING: StageArtifactType.DOMAIN_VALIDATION,
    WorkflowState.BUSINESS_VALIDATING: StageArtifactType.BUSINESS_VALIDATION,
    WorkflowState.ERP_CALLING: StageArtifactType.ERP,
}

_ERROR_BY_EVENT = {
    EventType.EXTRACTION_FAILED: CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
    EventType.STRUCTURAL_VALIDATION_FAILED: CanonicalErrorCode.ORDER_STRUCTURE_INVALID,
    EventType.BUSINESS_VALIDATION_FAILED: CanonicalErrorCode.QUANTITY_NON_POSITIVE,
    EventType.ERP_REQUEST_FAILED: CanonicalErrorCode.ERP_UNAVAILABLE,
}

_QUERY_BY_STAGE = {
    WorkflowState.EXTRACTING: "extraction provider failure",
    WorkflowState.STRUCTURE_VALIDATING: "invalid structure field type",
    WorkflowState.DOMAIN_VALIDATING: "domain validation missing required business input",
    WorkflowState.BUSINESS_VALIDATING: "business validation non positive quantity",
    WorkflowState.ERP_CALLING: "ERP service unavailable terminal HTTP 503",
}

_ACTION = {
    CanonicalErrorCode.EXTRACTION_MODEL_ERROR: RecoveryAction.REQUEST_HUMAN_REVIEW,
    CanonicalErrorCode.ORDER_STRUCTURE_INVALID: RecoveryAction.REQUEST_INPUT_CORRECTION,
    CanonicalErrorCode.CUSTOMER_NUMBER_MISSING: RecoveryAction.REQUEST_INPUT_CORRECTION,
    CanonicalErrorCode.PRODUCT_CODE_MISSING: RecoveryAction.REQUEST_INPUT_CORRECTION,
    CanonicalErrorCode.QUANTITY_MISSING: RecoveryAction.REQUEST_INPUT_CORRECTION,
    CanonicalErrorCode.QUANTITY_NON_POSITIVE: RecoveryAction.REQUEST_INPUT_CORRECTION,
    CanonicalErrorCode.ERP_UNAVAILABLE: RecoveryAction.RETRY_SAME_INPUT,
}

_ROOT_CAUSE = {
    CanonicalErrorCode.EXTRACTION_MODEL_ERROR: "The extraction provider failed before returning usable structured output.",
    CanonicalErrorCode.ORDER_STRUCTURE_INVALID: "The extracted order failed deterministic structural/type validation.",
    CanonicalErrorCode.CUSTOMER_NUMBER_MISSING: "The required customer number is absent from the extracted order.",
    CanonicalErrorCode.PRODUCT_CODE_MISSING: "The required product code is absent from the extracted order.",
    CanonicalErrorCode.QUANTITY_MISSING: "The required quantity is absent from the extracted order.",
    CanonicalErrorCode.QUANTITY_NON_POSITIVE: "The supplied quantity violates the positive-quantity business rule.",
    CanonicalErrorCode.ERP_UNAVAILABLE: "The terminal ERP request returned service unavailable (HTTP 503).",
}

_RATIONALE = {
    code: (
        "The recommendation follows retrieved terminal evidence and local runbook guidance; "
        "it does not authorize or execute recovery."
    )
    for code in _ROOT_CAUSE
}
