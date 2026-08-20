"""Deterministic order workflow orchestration."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from traceguard.domain.enums import (
    CanonicalErrorCode,
    EventOutcome,
    FailureCategory,
    WorkflowState,
)
from traceguard.domain.errors import WorkflowValidationError
from traceguard.domain.validation import (
    validate_business_rules,
    validate_domain_requirements,
    validate_extracted_structure,
)
from traceguard.workflow.erp import MockErp
from traceguard.workflow.models import (
    EventSeverity,
    EventType,
    MockErpBehavior,
    PresetId,
    StageArtifact,
    StageArtifactType,
    TraceEvent,
    WorkflowRun,
)
from traceguard.workflow.repository import TraceRepository


ExtractionCallable = Callable[[str], object]
_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


class WorkflowOrchestrator:
    def __init__(self, repository: TraceRepository, erp: MockErp) -> None:
        self._repository = repository
        self._erp = erp

    def execute(
        self,
        *,
        order_request_text: str,
        mock_erp_behavior: MockErpBehavior,
        extraction: ExtractionCallable,
        preset_id: PresetId | None = None,
    ) -> WorkflowRun:
        run = self._repository.create_run(
            WorkflowRun(
                order_request_text=order_request_text,
                preset_id=preset_id,
                mock_erp_behavior=mock_erp_behavior,
            )
        )
        self._append_event(
            run,
            stage=WorkflowState.CREATED,
            event_type=EventType.RUN_CREATED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Workflow run created.",
        )

        run = self._repository.transition_workflow(
            run.run_id, WorkflowState.EXTRACTING
        )
        self._append_event(
            run,
            stage=WorkflowState.EXTRACTING,
            event_type=EventType.EXTRACTION_STARTED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.CONTINUED,
            details="Extraction dependency invoked.",
        )
        try:
            extraction_output = extraction(order_request_text)
        except Exception:
            self._append_artifact(
                run,
                StageArtifactType.EXTRACTION,
                {
                    "status": "failed",
                    "error_code": CanonicalErrorCode.EXTRACTION_MODEL_ERROR.value,
                },
            )
            self._append_event(
                run,
                stage=WorkflowState.EXTRACTING,
                event_type=EventType.EXTRACTION_FAILED,
                severity=EventSeverity.ERROR,
                outcome=EventOutcome.TERMINAL,
                details=(
                    "Extraction dependency failed; provider details were not retained."
                ),
            )
            return self._repository.mark_run_failed(
                run.run_id,
                failure_stage=WorkflowState.EXTRACTING,
                code=CanonicalErrorCode.EXTRACTION_MODEL_ERROR,
                category=FailureCategory.EXTRACTION_FAILURE,
            )

        self._append_artifact(
            run,
            StageArtifactType.EXTRACTION,
            {
                "status": "completed",
                "output": _safe_json_value(extraction_output),
            },
        )
        self._append_event(
            run,
            stage=WorkflowState.EXTRACTING,
            event_type=EventType.EXTRACTION_COMPLETED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Extraction dependency returned an output.",
        )

        run = self._repository.transition_workflow(
            run.run_id, WorkflowState.STRUCTURE_VALIDATING
        )
        try:
            candidate = validate_extracted_structure(extraction_output)
        except WorkflowValidationError as error:
            return self._fail_validation(
                run,
                artifact_type=StageArtifactType.STRUCTURAL_VALIDATION,
                event_type=EventType.STRUCTURAL_VALIDATION_FAILED,
                error=error,
            )
        self._append_artifact(
            run,
            StageArtifactType.STRUCTURAL_VALIDATION,
            {"status": "passed", "candidate": candidate.model_dump(mode="json")},
        )
        self._append_event(
            run,
            stage=WorkflowState.STRUCTURE_VALIDATING,
            event_type=EventType.STRUCTURAL_VALIDATION_COMPLETED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Extraction output passed structural and type validation.",
        )

        run = self._repository.transition_workflow(
            run.run_id, WorkflowState.DOMAIN_VALIDATING
        )
        try:
            domain_order = validate_domain_requirements(candidate)
        except WorkflowValidationError as error:
            return self._fail_validation(
                run,
                artifact_type=StageArtifactType.DOMAIN_VALIDATION,
                event_type=EventType.DOMAIN_VALIDATION_FAILED,
                error=error,
            )
        self._append_artifact(
            run,
            StageArtifactType.DOMAIN_VALIDATION,
            {"status": "passed", "order": domain_order.model_dump(mode="json")},
        )
        self._append_event(
            run,
            stage=WorkflowState.DOMAIN_VALIDATING,
            event_type=EventType.DOMAIN_VALIDATION_COMPLETED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Required domain fields are present.",
        )

        run = self._repository.transition_workflow(
            run.run_id, WorkflowState.BUSINESS_VALIDATING
        )
        try:
            validated_order = validate_business_rules(domain_order)
        except WorkflowValidationError as error:
            return self._fail_validation(
                run,
                artifact_type=StageArtifactType.BUSINESS_VALIDATION,
                event_type=EventType.BUSINESS_VALIDATION_FAILED,
                error=error,
            )
        self._append_artifact(
            run,
            StageArtifactType.BUSINESS_VALIDATION,
            {
                "status": "passed",
                "order": validated_order.model_dump(mode="json"),
            },
        )
        self._append_event(
            run,
            stage=WorkflowState.BUSINESS_VALIDATING,
            event_type=EventType.BUSINESS_VALIDATION_COMPLETED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Order passed deterministic business-rule validation.",
        )

        run = self._repository.transition_workflow(
            run.run_id, WorkflowState.ERP_CALLING
        )
        erp_result = self._erp.submit(run.run_id, validated_order)
        self._append_artifact(
            run,
            StageArtifactType.ERP,
            {
                "attempt_number": erp_result.attempt.attempt_number,
                "status_code": erp_result.attempt.status_code,
                "succeeded": erp_result.attempt.succeeded,
                "response_summary": erp_result.attempt.response_summary,
            },
        )
        for diagnostic in erp_result.diagnostics:
            self._append_event(
                run,
                stage=WorkflowState.ERP_CALLING,
                event_type=diagnostic.event_type,
                severity=diagnostic.severity,
                outcome=diagnostic.outcome,
                details=diagnostic.details,
            )

        if not erp_result.attempt.succeeded:
            self._append_event(
                run,
                stage=WorkflowState.ERP_CALLING,
                event_type=EventType.ERP_REQUEST_FAILED,
                severity=EventSeverity.ERROR,
                outcome=EventOutcome.TERMINAL,
                details="Mock ERP returned service unavailable (HTTP 503).",
            )
            return self._repository.mark_run_failed(
                run.run_id,
                failure_stage=WorkflowState.ERP_CALLING,
                code=CanonicalErrorCode.ERP_UNAVAILABLE,
                category=FailureCategory.EXTERNAL_TRANSIENT_FAILURE,
            )

        self._append_event(
            run,
            stage=WorkflowState.ERP_CALLING,
            event_type=EventType.ERP_REQUEST_SUCCEEDED,
            severity=EventSeverity.INFO,
            outcome=EventOutcome.SUCCESS,
            details="Mock ERP accepted the order.",
        )
        return self._repository.transition_workflow(
            run.run_id, WorkflowState.SUCCEEDED
        )

    def _fail_validation(
        self,
        run: WorkflowRun,
        *,
        artifact_type: StageArtifactType,
        event_type: EventType,
        error: WorkflowValidationError,
    ) -> WorkflowRun:
        self._append_artifact(
            run,
            artifact_type,
            {
                "status": "failed",
                "error_code": error.code.value,
                "failure_category": error.category.value,
            },
        )
        self._append_event(
            run,
            stage=run.workflow_state,
            event_type=event_type,
            severity=EventSeverity.ERROR,
            outcome=EventOutcome.TERMINAL,
            details="Deterministic validation rejected the order.",
        )
        return self._repository.mark_run_failed(
            run.run_id,
            failure_stage=run.workflow_state,
            code=error.code,
            category=error.category,
        )

    def _append_artifact(
        self,
        run: WorkflowRun,
        artifact_type: StageArtifactType,
        data: dict[str, JsonValue],
    ) -> None:
        self._repository.append_stage_artifact(
            StageArtifact(
                run_id=run.run_id,
                artifact_type=artifact_type,
                data=data,
            )
        )

    def _append_event(
        self,
        run: WorkflowRun,
        *,
        stage: WorkflowState,
        event_type: EventType,
        severity: EventSeverity,
        outcome: EventOutcome,
        details: str,
    ) -> None:
        self._repository.append_event(
            TraceEvent(
                run_id=run.run_id,
                workflow_stage=stage,
                event_type=event_type,
                severity=severity,
                outcome=outcome,
                details=details,
            )
        )


def _safe_json_value(value: Any) -> JsonValue:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    try:
        return _JSON_VALUE_ADAPTER.validate_python(value)
    except ValidationError:
        return {
            "captured": False,
            "output_type": type(value).__name__,
        }

