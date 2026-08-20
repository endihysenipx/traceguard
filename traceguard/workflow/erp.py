"""Stateful deterministic mock ERP adapter."""

from uuid import UUID

from traceguard.domain.enums import EventOutcome
from traceguard.domain.models import ValidatedOrder
from traceguard.workflow.models import (
    ErpDiagnostic,
    EventSeverity,
    EventType,
    MockErpBehavior,
    MockErpResult,
)
from traceguard.workflow.repository import TraceRepository


class MockErp:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    def submit(self, run_id: UUID, order: ValidatedOrder) -> MockErpResult:
        """Record one attempt; FAIL_ONCE_503 succeeds from attempt two onward."""

        run = self._repository.get_run(run_id)
        first_attempt = run.erp_attempt_count == 0
        should_fail = (
            run.mock_erp_behavior is MockErpBehavior.FAIL_ONCE_503
            and first_attempt
        )

        if should_fail:
            diagnostics: list[ErpDiagnostic] = []
            if order.delivery_instructions is None:
                diagnostics.append(
                    ErpDiagnostic(
                        event_type=EventType.OPTIONAL_FIELD_DEFAULTED,
                        severity=EventSeverity.WARNING,
                        outcome=EventOutcome.CONTINUED,
                        details=(
                            "Optional delivery instructions were absent; the safe "
                            "default was used."
                        ),
                    ),
                )
            diagnostics.extend(
                [
                    ErpDiagnostic(
                    event_type=EventType.CACHE_LOOKUP_FAILED,
                    severity=EventSeverity.WARNING,
                    outcome=EventOutcome.RECOVERED,
                    details=(
                        "The non-critical routing cache lookup failed; fallback "
                        "processing continued."
                    ),
                    ),
                    ErpDiagnostic(
                        event_type=EventType.CACHE_FALLBACK_SUCCEEDED,
                        severity=EventSeverity.INFO,
                        outcome=EventOutcome.SUCCESS,
                        details="The routing fallback completed successfully.",
                    ),
                ]
            )
            attempt = self._repository.record_erp_attempt(
                run_id,
                behavior=run.mock_erp_behavior,
                status_code=503,
                succeeded=False,
                response_summary="Mock ERP service unavailable.",
            )
            return MockErpResult(attempt=attempt, diagnostics=tuple(diagnostics))

        attempt = self._repository.record_erp_attempt(
            run_id,
            behavior=run.mock_erp_behavior,
            status_code=200,
            succeeded=True,
            response_summary="Mock ERP accepted the order.",
        )
        return MockErpResult(attempt=attempt)
