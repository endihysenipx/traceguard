import pytest

from traceguard.domain.enums import CanonicalErrorCode, EvidenceRole, EventOutcome
from traceguard.domain.models import EvidenceItem
from traceguard.investigation.runbook import LocalRunbook
from traceguard.investigation.validation import (
    InvestigationReportValidationError,
    validate_investigation_report,
)
from traceguard.workflow.models import EventType, PresetId

from tests.investigation.support import execute_fixture, report_for_event


def _validate(report, run, repository, retrieved_ids, runbook_ids=frozenset()):
    validate_investigation_report(
        report,
        target_run_id=run.run_id,
        events=repository.list_events(run.run_id),
        runbook=LocalRunbook(),
        retrieved_event_ids=frozenset(retrieved_ids),
        retrieved_runbook_ids=frozenset(runbook_ids),
    )


def test_terminal_evidence_passes_without_comparing_hidden_canonical_diagnosis() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    terminal = next(
        event for event in repository.list_events(run.run_id)
        if event.outcome is EventOutcome.TERMINAL
    )
    report = report_for_event(
        run.run_id,
        terminal,
        code=CanonicalErrorCode.ERP_REJECTED,
    )

    _validate(report, run, repository, {terminal.event_id})


def test_recovered_cache_warning_cannot_be_terminal_cause() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    recovered = next(
        event for event in repository.list_events(run.run_id)
        if event.event_type is EventType.CACHE_LOOKUP_FAILED
    )
    report = report_for_event(
        run.run_id,
        recovered,
        code=CanonicalErrorCode.ERP_UNAVAILABLE,
    )

    with pytest.raises(InvestigationReportValidationError, match="terminal event"):
        _validate(report, run, repository, {recovered.event_id})


def test_recovered_event_is_allowed_only_as_non_causal_context() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    events = repository.list_events(run.run_id)
    terminal = next(event for event in events if event.outcome is EventOutcome.TERMINAL)
    recovered = next(event for event in events if event.outcome is EventOutcome.RECOVERED)
    report = report_for_event(
        run.run_id, terminal, code=CanonicalErrorCode.ERP_UNAVAILABLE
    )
    report = report.model_copy(
        update={
            "evidence": report.evidence + [
                EvidenceItem(
                    event_id=recovered.event_id,
                    role=EvidenceRole.NON_CAUSAL_CONTEXT,
                    observation="The cache failure recovered and is not causal.",
                )
            ]
        }
    )

    _validate(report, run, repository, {terminal.event_id, recovered.event_id})


def test_unretrieved_or_foreign_event_evidence_is_rejected() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    terminal = next(event for event in repository.list_events(run.run_id) if event.outcome is EventOutcome.TERMINAL)
    report = report_for_event(run.run_id, terminal, code=CanonicalErrorCode.ERP_UNAVAILABLE)

    with pytest.raises(InvestigationReportValidationError, match="not retrieved"):
        _validate(report, run, repository, set())


def test_runbook_reference_must_exist_and_have_been_retrieved() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    terminal = next(event for event in repository.list_events(run.run_id) if event.outcome is EventOutcome.TERMINAL)
    report = report_for_event(
        run.run_id,
        terminal,
        code=CanonicalErrorCode.ERP_UNAVAILABLE,
        runbook_references=["RB-ERP-UNAVAILABLE"],
    )
    with pytest.raises(InvestigationReportValidationError, match="not retrieved"):
        _validate(report, run, repository, {terminal.event_id})

    _validate(
        report,
        run,
        repository,
        {terminal.event_id},
        {"RB-ERP-UNAVAILABLE"},
    )
