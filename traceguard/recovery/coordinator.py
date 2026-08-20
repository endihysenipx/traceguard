"""Deterministic recovery authorization and one narrowly scoped ERP retry."""

from collections.abc import Callable
from time import sleep
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from traceguard.domain.enums import (
    InvestigationState,
    PolicyDecisionType,
    RecoveryAction,
    RecoveryExecutionStatus,
    RecoveryState,
    WorkflowState,
)
from traceguard.domain.models import (
    DomainModel,
    InvestigationReport,
    PolicyInput,
    RetryMetadata,
    ValidatedOrder,
)
from traceguard.domain.policy import evaluate_recovery_policy
from traceguard.workflow.models import (
    MockErpResult,
    RecoveryDecisionRecord,
    RecoveryExecutionRecord,
    StageArtifactType,
    WorkflowRun,
)
from traceguard.workflow.repository import (
    ArtifactNotFoundError,
    InvestigationRecordNotFoundError,
    RecoveryRecordNotFoundError,
    TraceRepository,
)


class ErpSubmitter(Protocol):
    def submit(self, run_id: UUID, order: ValidatedOrder) -> MockErpResult: ...


class RecoveryCoordinatorError(RuntimeError):
    pass


class RecoveryPreconditionError(RecoveryCoordinatorError):
    pass


class RecoveryResult(DomainModel):
    decision: RecoveryDecisionRecord
    execution: RecoveryExecutionRecord | None = None
    idempotent_replay: bool = False


class RecoveryCoordinator:
    """Build trusted policy input, persist the decision, and execute only retry."""

    def __init__(
        self,
        repository: TraceRepository,
        erp: ErpSubmitter,
        *,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._repository = repository
        self._erp = erp
        self._sleeper = sleeper

    def recover(self, run_id: UUID) -> RecoveryResult:
        """Evaluate if needed, then perform only a policy-authorized retry."""

        run = self._repository.get_run(run_id)
        existing = self._existing_execution(run_id, run.idempotency_key)
        if existing is not None:
            decision = self._repository.get_recovery_decision(
                run_id, existing.decision_record_id
            )
            return RecoveryResult(
                decision=decision,
                execution=existing,
                idempotent_replay=True,
            )

        if run.recovery_state is RecoveryState.NONE:
            decision = self.evaluate(run_id)
        else:
            decisions = self._repository.list_recovery_decisions(run_id)
            if not decisions:
                raise RecoveryPreconditionError(
                    "Recovery state has no corresponding policy decision."
                )
            decision = decisions[-1]

        if decision.decision is not PolicyDecisionType.ALLOW:
            return RecoveryResult(decision=decision)
        if self._repository.get_run(run_id).recovery_state is not RecoveryState.ALLOW:
            raise RecoveryPreconditionError(
                "An ALLOW decision is not in an executable recovery state."
            )
        return self._execute_retry(run_id, decision)

    def evaluate(self, run_id: UUID) -> RecoveryDecisionRecord:
        """Construct PolicyInput solely from stored workflow and report facts."""

        run, report = self._load_eligible_run_and_report(run_id)
        if run.recovery_state is not RecoveryState.NONE:
            decisions = self._repository.list_recovery_decisions(run_id)
            if decisions:
                return decisions[-1]
            raise RecoveryPreconditionError(
                "Recovery was already evaluated without an observable decision."
            )

        output = evaluate_recovery_policy(self._policy_input(run, report))
        record = self._repository.append_recovery_decision(
            RecoveryDecisionRecord(
                run_id=run_id,
                investigation_report_id=report.report_id,
                decision=output.decision,
                allowed_action=output.allowed_action,
                reason_codes=tuple(output.reason_codes),
                constraints=output.constraints,
            )
        )
        target = RecoveryState(output.decision.value)
        self._repository.transition_recovery(run_id, target)
        return record

    def _execute_retry(
        self, run_id: UUID, decision: RecoveryDecisionRecord
    ) -> RecoveryResult:
        run, report = self._load_eligible_run_and_report(run_id)
        stale_reason = self._authorization_problem(run, report, decision)
        if stale_reason is not None:
            return self._block_execution(run_id, decision, stale_reason)

        try:
            order = self._load_validated_order(run_id)
        except (ArtifactNotFoundError, ValidationError, TypeError, ValueError):
            return self._block_execution(
                run_id,
                decision,
                "Validated business-order artifact is unavailable or malformed.",
            )

        execution, created = self._repository.begin_recovery_execution(
            run_id,
            decision_record_id=decision.decision_record_id,
            investigation_report_id=report.report_id,
            idempotency_key=run.idempotency_key,
            action=RecoveryAction.RETRY_SAME_INPUT,
        )
        if not created:
            return RecoveryResult(
                decision=decision,
                execution=execution,
                idempotent_replay=True,
            )

        self._repository.transition_recovery(run_id, RecoveryState.RETRYING)
        try:
            self._sleeper(float(decision.constraints.backoff_seconds))
            erp_result = self._erp.submit(run_id, order)
        except Exception:
            completed = self._repository.complete_recovery_execution(
                run_id,
                execution_id=execution.execution_id,
                status=RecoveryExecutionStatus.FAILED,
                erp_attempt_number=None,
                result_summary="The authorized retry failed safely before a usable result.",
            )
            self._repository.transition_recovery(
                run_id, RecoveryState.RETRY_EXHAUSTED
            )
            return RecoveryResult(decision=decision, execution=completed)

        status = (
            RecoveryExecutionStatus.SUCCEEDED
            if erp_result.attempt.succeeded
            else RecoveryExecutionStatus.FAILED
        )
        completed = self._repository.complete_recovery_execution(
            run_id,
            execution_id=execution.execution_id,
            status=status,
            erp_attempt_number=erp_result.attempt.attempt_number,
            result_summary=erp_result.attempt.response_summary,
        )
        target = (
            RecoveryState.RECOVERED
            if erp_result.attempt.succeeded
            else RecoveryState.RETRY_EXHAUSTED
        )
        self._repository.transition_recovery(run_id, target)
        return RecoveryResult(decision=decision, execution=completed)

    def _authorization_problem(
        self,
        run: WorkflowRun,
        report: InvestigationReport,
        decision: RecoveryDecisionRecord,
    ) -> str | None:
        decisions = self._repository.list_recovery_decisions(run.run_id)
        if not decisions or decisions[-1].decision_record_id != decision.decision_record_id:
            return "The stored ALLOW decision is no longer current."
        stored = self._repository.get_recovery_decision(
            run.run_id, decision.decision_record_id
        )
        if (
            stored.decision is not PolicyDecisionType.ALLOW
            or stored.allowed_action is not RecoveryAction.RETRY_SAME_INPUT
            or stored.investigation_report_id != report.report_id
            or stored.constraints.idempotency_key != run.idempotency_key
            or stored.constraints.max_total_erp_attempts is None
            or stored.constraints.backoff_seconds is None
            or run.erp_attempt_count >= stored.constraints.max_total_erp_attempts
        ):
            return "Stored retry authorization or constraints are inconsistent."
        current_output = evaluate_recovery_policy(self._policy_input(run, report))
        if (
            current_output.decision is not PolicyDecisionType.ALLOW
            or current_output.allowed_action is not RecoveryAction.RETRY_SAME_INPUT
            or current_output.constraints != stored.constraints
        ):
            return "Current repository state no longer satisfies retry policy."
        if self._existing_execution(run.run_id, run.idempotency_key) is not None:
            return "The idempotency key already has a recovery execution."
        return None

    def _block_execution(
        self,
        run_id: UUID,
        decision: RecoveryDecisionRecord,
        summary: str,
    ) -> RecoveryResult:
        run = self._repository.get_run(run_id)
        execution, created = self._repository.begin_recovery_execution(
            run_id,
            decision_record_id=decision.decision_record_id,
            investigation_report_id=decision.investigation_report_id,
            idempotency_key=run.idempotency_key,
            action=RecoveryAction.RETRY_SAME_INPUT,
        )
        if created:
            execution = self._repository.complete_recovery_execution(
                run_id,
                execution_id=execution.execution_id,
                status=RecoveryExecutionStatus.BLOCKED,
                erp_attempt_number=None,
                result_summary=summary,
            )
            self._repository.transition_recovery(run_id, RecoveryState.BLOCK)
        return RecoveryResult(
            decision=decision,
            execution=execution,
            idempotent_replay=not created,
        )

    def _load_eligible_run_and_report(
        self, run_id: UUID
    ) -> tuple[WorkflowRun, InvestigationReport]:
        run = self._repository.get_run(run_id)
        if run.workflow_state is not WorkflowState.FAILED:
            raise RecoveryPreconditionError("Recovery requires a failed workflow run.")
        if run.investigation_state is not InvestigationState.COMPLETED:
            raise RecoveryPreconditionError(
                "Recovery requires a completed validated investigation."
            )
        try:
            report = self._repository.get_investigation_report(run_id)
        except InvestigationRecordNotFoundError as exc:
            raise RecoveryPreconditionError(
                "Recovery requires an available validated investigation report."
            ) from exc
        if report.run_id != run_id or run.canonical_failure_code is None:
            raise RecoveryPreconditionError("Stored recovery facts are inconsistent.")
        return run, report

    @staticmethod
    def _policy_input(
        run: WorkflowRun, report: InvestigationReport
    ) -> PolicyInput:
        return PolicyInput(
            canonical_error_code=run.canonical_failure_code,
            diagnosed_error_code=report.diagnosed_error_code,
            diagnosed_failure_category=report.failure_category,
            recommended_action=report.recommended_action,
            workflow_state=run.workflow_state,
            investigation_output_valid=True,
            retry=RetryMetadata(
                attempt_count=run.erp_attempt_count,
                idempotency_key=run.idempotency_key,
            ),
        )

    def _load_validated_order(self, run_id: UUID) -> ValidatedOrder:
        artifact = self._repository.get_latest_stage_artifact(
            run_id, StageArtifactType.BUSINESS_VALIDATION
        )
        if artifact.data.get("status") != "passed":
            raise ValueError("Business validation did not pass.")
        order = artifact.data.get("order")
        if not isinstance(order, dict):
            raise TypeError("Validated order is absent.")
        return ValidatedOrder.model_validate(order, strict=True)

    def _existing_execution(
        self, run_id: UUID, idempotency_key: str
    ) -> RecoveryExecutionRecord | None:
        try:
            return self._repository.get_latest_recovery_execution(
                run_id, idempotency_key
            )
        except RecoveryRecordNotFoundError:
            return None
