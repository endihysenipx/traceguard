"""Deterministic evidence-grounding validation for investigation reports."""

from collections.abc import Sequence
from uuid import UUID

from traceguard.domain.enums import EvidenceRole, EventOutcome
from traceguard.domain.models import InvestigationReport
from traceguard.investigation.runbook import LocalRunbook
from traceguard.workflow.models import TraceEvent


class InvestigationReportValidationError(ValueError):
    pass


def validate_investigation_report(
    report: InvestigationReport,
    *,
    target_run_id: UUID,
    events: Sequence[TraceEvent],
    runbook: LocalRunbook,
    retrieved_event_ids: frozenset[UUID],
    retrieved_runbook_ids: frozenset[str],
) -> None:
    if report.run_id != target_run_id:
        raise InvestigationReportValidationError(
            "Investigation report run does not match the target run."
        )

    events_by_id = {event.event_id: event for event in events}
    terminal_cause_found = False
    for evidence in report.evidence:
        event = events_by_id.get(evidence.event_id)
        if event is None or event.run_id != target_run_id:
            raise InvestigationReportValidationError(
                "Investigation evidence does not belong to the target run."
            )
        if evidence.event_id not in retrieved_event_ids:
            raise InvestigationReportValidationError(
                "Investigation evidence was not retrieved through the event tool."
            )
        if evidence.role is EvidenceRole.TERMINAL_CAUSE:
            if event.outcome is not EventOutcome.TERMINAL:
                raise InvestigationReportValidationError(
                    "Terminal-cause evidence must cite a terminal event."
                )
            terminal_cause_found = True
        if event.outcome in {EventOutcome.CONTINUED, EventOutcome.RECOVERED}:
            if evidence.role is not EvidenceRole.NON_CAUSAL_CONTEXT:
                raise InvestigationReportValidationError(
                    "Continued or recovered events may be cited only as non-causal context."
                )

    if not terminal_cause_found:
        raise InvestigationReportValidationError(
            "Investigation report requires causal terminal-event evidence."
        )
    unknown_references = set(report.runbook_references) - runbook.entry_ids
    if unknown_references:
        raise InvestigationReportValidationError(
            "Investigation report cites an unknown runbook entry."
        )
    if not set(report.runbook_references).issubset(retrieved_runbook_ids):
        raise InvestigationReportValidationError(
            "Investigation report cites runbook guidance that was not retrieved."
        )
