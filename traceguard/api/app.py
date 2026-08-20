"""FastAPI composition root and thin HTTP boundary for TraceGuard."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Body, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from traceguard.domain.enums import InvestigationState, ProviderMode
from traceguard.domain.errors import IllegalStateTransition
from traceguard.extraction import (
    ExtractionProvider,
    OpenAIExtractionProvider,
    ProviderConfigurationError,
    ScriptedExtractionProvider,
    UnsupportedScriptedInputError,
)
from traceguard.investigation import (
    InvestigationFailedError,
    InvestigationNotAllowedError,
    Investigator,
    LocalRunbook,
    OpenAIInvestigatorModel,
    ScriptedInvestigatorModel,
)
from traceguard.investigation.models import InvestigatorModel, InvestigatorModelError
from traceguard.recovery import RecoveryCoordinator, RecoveryPreconditionError
from traceguard.recovery.coordinator import RecoveryResult
from traceguard.workflow import (
    InMemoryTraceRepository,
    MockErp,
    SCENARIO_FIXTURES,
    WorkflowOrchestrator,
)
from traceguard.workflow.models import (
    RecoveryDecisionRecord,
    RecoveryExecutionRecord,
    WorkflowRun,
)
from traceguard.workflow.repository import (
    InvestigationRecordNotFoundError,
    RunNotFoundError,
    TraceRepository,
    TraceRepositoryError,
)

from traceguard.api.schemas import CreateRunRequest, EmptyActionRequest, InvestigateRequest


STATIC_DIR = Path(__file__).with_name("static")


@dataclass(frozen=True)
class ApplicationServices:
    repository: TraceRepository
    erp: MockErp
    runbook: LocalRunbook
    workflow: WorkflowOrchestrator
    investigator: Investigator
    recovery: RecoveryCoordinator
    extraction_provider_factories: Mapping[
        ProviderMode, Callable[[], ExtractionProvider]
    ]
    investigator_model_factories: Mapping[
        ProviderMode, Callable[[], InvestigatorModel]
    ]


def create_services(
    *,
    repository: InMemoryTraceRepository | None = None,
    extraction_provider_factories: Mapping[
        ProviderMode, Callable[[], ExtractionProvider]
    ] | None = None,
    investigator_model_factories: Mapping[
        ProviderMode, Callable[[], InvestigatorModel]
    ] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> ApplicationServices:
    """Compose one process-local service graph; tests can inject every boundary."""

    repository = repository or InMemoryTraceRepository()
    erp = MockErp(repository)
    runbook = LocalRunbook()
    workflow = WorkflowOrchestrator(repository, erp)
    investigator = Investigator(repository, runbook)
    recovery = (
        RecoveryCoordinator(repository, erp)
        if sleeper is None
        else RecoveryCoordinator(repository, erp, sleeper=sleeper)
    )
    return ApplicationServices(
        repository=repository,
        erp=erp,
        runbook=runbook,
        workflow=workflow,
        investigator=investigator,
        recovery=recovery,
        extraction_provider_factories=extraction_provider_factories
        or {
            ProviderMode.SCRIPTED: ScriptedExtractionProvider,
            ProviderMode.LIVE: OpenAIExtractionProvider,
        },
        investigator_model_factories=investigator_model_factories
        or {
            ProviderMode.SCRIPTED: ScriptedInvestigatorModel,
            ProviderMode.LIVE: OpenAIInvestigatorModel,
        },
    )


def create_app(services: ApplicationServices | None = None) -> FastAPI:
    services = services or create_services()
    application = FastAPI(title="TraceGuard", version="0.1.0")
    application.state.services = services
    application.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
    _register_error_handlers(application)

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @application.get("/api/presets")
    def list_presets() -> dict[str, object]:
        return {
            "presets": [
                {
                    "preset_id": fixture.preset_id.value,
                    "order_request_text": fixture.order_request_text,
                    "mock_erp_behavior": fixture.mock_erp_behavior.value,
                }
                for fixture in SCENARIO_FIXTURES.values()
            ]
        }

    @application.post("/api/runs", status_code=status.HTTP_201_CREATED)
    def create_run(payload: CreateRunRequest) -> dict[str, object]:
        provider = services.extraction_provider_factories[
            payload.extraction_provider_mode
        ]()
        if (
            isinstance(provider, ScriptedExtractionProvider)
            and not provider.supports(payload.order_request_text)
        ):
            raise UnsupportedScriptedInputError(
                "Scripted extraction supports exact demo fixtures only. "
                "Edited or custom input requires LIVE extraction."
            )
        run = services.workflow.execute(
            order_request_text=payload.order_request_text,
            preset_id=payload.preset_id,
            mock_erp_behavior=payload.mock_erp_behavior,
            provider=provider,
        )
        return _run_view(run)

    @application.get("/api/runs/{run_id}")
    def inspect_run(run_id: UUID) -> dict[str, object]:
        return _aggregate_view(services.repository, run_id)

    @application.post("/api/runs/{run_id}/investigate")
    def investigate(run_id: UUID, payload: InvestigateRequest) -> dict[str, object]:
        model = services.investigator_model_factories[
            payload.investigation_provider_mode
        ]()
        report = services.investigator.investigate(run_id, model)
        return {
            "report": report.model_dump(mode="json"),
            "run": _run_view(services.repository.get_run(run_id)),
        }

    @application.post("/api/runs/{run_id}/recovery/evaluate")
    def evaluate_recovery(
        run_id: UUID,
        payload: EmptyActionRequest = Body(default=EmptyActionRequest()),
    ) -> dict[str, object]:
        del payload
        decision = services.recovery.evaluate(run_id)
        return {
            "decision": _decision_view(decision),
            "recovery_state": services.repository.get_run(run_id).recovery_state.value,
        }

    @application.post("/api/runs/{run_id}/recover")
    def recover(
        run_id: UUID,
        payload: EmptyActionRequest = Body(default=EmptyActionRequest()),
    ) -> dict[str, object]:
        del payload
        result = services.recovery.recover(run_id)
        return _recovery_result_view(
            result, services.repository.get_run(run_id).recovery_state.value
        )

    return application


def _register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request, error
        return _error(400, "INVALID_REQUEST", "Request fields or enum values are invalid.")

    @application.exception_handler(RunNotFoundError)
    async def unknown_run(request: Request, error: RunNotFoundError) -> JSONResponse:
        del request, error
        return _error(404, "RUN_NOT_FOUND", "The requested workflow run does not exist.")

    @application.exception_handler(UnsupportedScriptedInputError)
    async def scripted_input(
        request: Request, error: UnsupportedScriptedInputError
    ) -> JSONResponse:
        del request, error
        return _error(
            400,
            "LIVE_PROVIDER_REQUIRED",
            "Scripted extraction supports exact demo fixtures only. Edited or custom input requires LIVE mode.",
        )

    @application.exception_handler(ProviderConfigurationError)
    @application.exception_handler(InvestigatorModelError)
    async def live_unavailable(request: Request, error: Exception) -> JSONResponse:
        del request, error
        return _error(
            503,
            "LIVE_PROVIDER_UNAVAILABLE",
            "LIVE mode is not configured or the provider is unavailable.",
        )

    @application.exception_handler(InvestigationFailedError)
    async def investigation_failed(
        request: Request, error: InvestigationFailedError
    ) -> JSONResponse:
        del request
        return _error(
            503,
            "INVESTIGATION_FAILED",
            f"Investigation terminated safely: {error.reason.value}.",
        )

    @application.exception_handler(InvestigationNotAllowedError)
    @application.exception_handler(RecoveryPreconditionError)
    @application.exception_handler(IllegalStateTransition)
    @application.exception_handler(TraceRepositoryError)
    async def operation_conflict(request: Request, error: Exception) -> JSONResponse:
        del request, error
        return _error(
            409,
            "OPERATION_CONFLICT",
            "The requested operation is not valid for the run's current state.",
        )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message},
    )


def _run_view(run: WorkflowRun) -> dict[str, Any]:
    return {
        "run_id": str(run.run_id),
        "order_request_text": run.order_request_text,
        "preset_id": run.preset_id.value if run.preset_id else None,
        "mock_erp_behavior": run.mock_erp_behavior.value,
        "workflow_state": run.workflow_state.value,
        "investigation_state": run.investigation_state.value,
        "recovery_state": run.recovery_state.value,
        "extraction_provider_mode": (
            run.extraction_provider_mode.value if run.extraction_provider_mode else None
        ),
        "investigation_provider_mode": (
            run.investigation_provider_mode.value
            if run.investigation_provider_mode
            else None
        ),
        "canonical_failure_code": (
            run.canonical_failure_code.value if run.canonical_failure_code else None
        ),
        "canonical_failure_category": (
            run.canonical_failure_category.value
            if run.canonical_failure_category
            else None
        ),
        "failure_stage": run.failure_stage.value if run.failure_stage else None,
        "erp_attempt_count": run.erp_attempt_count,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _aggregate_view(repository: TraceRepository, run_id: UUID) -> dict[str, object]:
    run = repository.get_run(run_id)
    report = None
    failure = None
    if run.investigation_state is InvestigationState.COMPLETED:
        report = repository.get_investigation_report(run_id).model_dump(mode="json")
    elif run.investigation_state is InvestigationState.FAILED:
        try:
            failure = repository.get_investigation_failure(run_id).model_dump(mode="json")
        except InvestigationRecordNotFoundError:
            failure = None
    return {
        "run": _run_view(run),
        "events": [item.model_dump(mode="json") for item in repository.list_events(run_id)],
        "artifacts": [
            item.model_dump(mode="json")
            for item in repository.list_stage_artifacts(run_id)
        ],
        "erp_attempts": [
            item.model_dump(mode="json")
            for item in repository.list_erp_attempts(run_id)
        ],
        "investigation_tool_calls": [
            item.model_dump(mode="json")
            for item in repository.list_investigation_tool_calls(run_id)
        ],
        "investigation_report": report,
        "investigation_failure": failure,
        "recovery_decisions": [
            _decision_view(item) for item in repository.list_recovery_decisions(run_id)
        ],
        "recovery_executions": [
            _execution_view(item) for item in repository.list_recovery_executions(run_id)
        ],
    }


def _decision_view(record: RecoveryDecisionRecord) -> dict[str, object]:
    return {
        "decision_record_id": str(record.decision_record_id),
        "timestamp": record.timestamp.isoformat(),
        "run_id": str(record.run_id),
        "investigation_report_id": str(record.investigation_report_id),
        "decision": record.decision.value,
        "allowed_action": record.allowed_action.value if record.allowed_action else None,
        "reason_codes": [reason.value for reason in record.reason_codes],
        "constraints": {
            "max_total_erp_attempts": record.constraints.max_total_erp_attempts,
            "backoff_seconds": record.constraints.backoff_seconds,
            "idempotency_key_present": record.constraints.idempotency_key is not None,
        },
    }


def _execution_view(record: RecoveryExecutionRecord) -> dict[str, object]:
    return {
        "record_id": str(record.record_id),
        "execution_id": str(record.execution_id),
        "timestamp": record.timestamp.isoformat(),
        "run_id": str(record.run_id),
        "decision_record_id": str(record.decision_record_id),
        "investigation_report_id": str(record.investigation_report_id),
        "action": record.action.value,
        "status": record.status.value,
        "erp_attempt_number": record.erp_attempt_number,
        "result_summary": record.result_summary,
        "idempotency_enforced": True,
    }


def _recovery_result_view(result: RecoveryResult, recovery_state: str) -> dict[str, object]:
    return {
        "decision": _decision_view(result.decision),
        "execution": _execution_view(result.execution) if result.execution else None,
        "idempotent_replay": result.idempotent_replay,
        "recovery_state": recovery_state,
    }


app = create_app()
